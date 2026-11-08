# Indexing and retrieval pipeline

Corpus: 9 FAST-NUCES documents, 281 pages (see docs/CORPUS.md). Documents are baked into
the indexer image (`make stage-corpus` copies corpus/raw/ into the build context), so a
re-index of new material is: fetch, `make images`, `make index`. The API is untouched.

## Extraction
- PDFs: pdfplumber, page by page. Tables are found first and written as `col | col | col`
  rows; the prose outside the table boxes is extracted separately, so columns do not
  interleave with the text.
- Pages with fewer than 20 characters of text are treated as having no text layer and are
  OCR'd with Tesseract (pdf2image at 200 dpi), marked `ocr=True`.
- HTML: tags stripped; navigation, header, footer and scripts skipped; table rows kept as
  `a | b | c`; h1-h4 kept as `# heading` lines.
- Markdown (CI fixtures): front matter removed.

| Document | Pages OCR'd | Characters recovered |
| --- | --- | --- |
| faculty-entrepreneurship-and-technical-start-ups-policy.pdf | 8 of 8 | 11,791 |
| undergraduate-academic-rules-aug-2023.pdf | 24 of 26 | 31,701 |

We did not expect the 2023 rules to be a scan; the indexer log (`"msg": "ocr used"`) showed
it. So the old side of our version pair comes from OCR, and OCR errors there can affect
version-sensitive questions.

**A table extracted well (HTML).** The grading page's table has three columns: grade,
grade points, interpretation. After extraction each row stays together:

    A  | 4.00 | Excellent
    A- | 3.67 | Very Good
    B+ | 3.33 | Very Good
    B  | 3.00 | Good
    B- | 2.67 | Average
    C+ | 2.33 | Below Average

**A table that came out mangled (PDF).** In the 5-page prospectus the grade table sits next
to running text in a two-column layout. pdfplumber did not detect it as a table, so the
columns interleave with the prose. One extracted line reads:

    ... Absence of a credit hour means 3 hours of lab- B+ 3.33 F 1.00 maximum of 20% of the
    total work per week ...

The B+ grade points (3.33) and the attendance rule are spliced together. We could not
recover this layout; the same grades are available cleanly from the grading page, which is
the source our golden question q05 uses.

**What we could not fully recover:** two-column layouts in the prospectus and the annual
reports (reading order mixes columns); OCR quality in the 2023 rules is good enough to
retrieve on, but clause numbers and table cells there are less reliable than in the 2026
handbook.

## Cleaning
1. A line appearing on more than half the pages of a document (3+ pages) is a running
   header or footer and is removed (digits are ignored when comparing, so "Page 3" and
   "Page 4" match).
2. Lines that are only a page number are removed.
3. Words hyphenated across a line break are joined.
4. Repeated spaces and blank lines are collapsed.

**Deliberately not stripped: heading lines** such as "5.4 Academic Warning". Chunking splits
on them, every chunk records its heading as `section`, and citations name it.

## Chunking
Structure-aware: split at headings (Markdown `#`, numbered clauses in Title Case, short
ALL-CAPS lines), then pack paragraphs up to the size limit, splitting long paragraphs by
sentence. Each new chunk in a section starts with the last `overlap` words of the previous
one; overlap never crosses a section boundary. The heading is prefixed to each chunk's text.
**Unit: words**, not model tokens (nomic-embed-text sees roughly 1.3 tokens per word).

A real bug we fixed: the first heading rule accepted numbered list sentences such as "14
Political activities or campaigns are strictly prohibited within" as section titles. A
numbered line is now a heading only if it reads like a title (mostly capitalised words,
not ending on "within", "the", ...). Found from a citation in the UI. With the fix, the
same corpus at 400/50 produces 415 chunks instead of 569: fewer false section breaks.

**Known limitations of the heading rule**
- Table-of-contents lines end in a page number and are taken as headings, e.g.
  "9 Policy on Retake Examination 31". Clause 1.21 (attendance) ended up in a chunk under
  that label instead of "3 Attendance Requirements", so golden questions q09, q11 and q15
  point at it, because that is where the answer text actually is. Next step: skip lines
  that end in a page number.
- Sub-clauses such as 5.4 are not separate sections; they sit inside
  "5 Academic Assessment". Much of the prospectus falls under "Preamble" and much of the
  Student Handbook under one large "Code Of Conduct" section.

Recall@k only measures retrieval, so the 250/30 and 600/80 runs used the stub generator
(`LLM_PROVIDER=stub`), which takes seconds per run instead of a minute per question. Each
run re-indexed the full corpus (OCR included) inside the cluster, then ran all 15 golden
questions.

| Size (words) | Overlap (words) | recall@3 | recall@5 | Chunks stored | CI gate |
| --- | --- | --- | --- | --- | --- |
| 250 | 30 | 0.88 | 0.92 | 562 | passed |
| **400** | **50** | 0.81 | **0.96** | 415 | passed (baseline) |
| 600 | 80 | 0.65 | 0.81 | 353 | **failed**: recall@5 more than 5 points below baseline |

**Shipped: size 400, overlap 50 words, giving 415 chunks.**

**Why we shipped 400/50.** It has the highest recall@5 (0.96), the number the CI gate
protects and the number that decides whether the right passage reaches the model at all
(we retrieve 5). 250/30 ranks the right chunk higher more often (recall@3 0.88), but it
splits clauses across more pieces, so some questions lose their second relevant section
from the top 5 (recall@5 0.92), and it stores 35% more chunks (562 vs 415). 600/80 is
clearly worse on both: one 600-word chunk mixes several clauses into one vector, so the
specific clause stops standing out, and the gate failed it. If we sent only the top 3
passages to the model and measured nothing else, 250/30 would be the better choice; with 5
retrieved, 400/50 wins.

Storage amplification = stored words / original words = 87,923 / 79,073 =
**1.11** at 400/50. The overlap (50 words per extra chunk) and the heading prefixed to
every chunk push it above 1. Measured locally without OCR, so the two scanned PDFs
contribute almost no words to either side.

## Embedding
- Model: **nomic-embed-text**, **768** dimensions, served by Ollama.
- The pin lives in one place: `EMBED_MODEL` in `k8s/base/configmap.yaml`, read by both the
  indexer Job and the api.
- The indexer writes `embed_model`, `dimension` and `index_version` into the Chroma
  collection metadata. The api's `/readyz` compares `embed_model` with its own EMBED_MODEL
  and returns 503, logging both values, on a mismatch.

## Retrieval and grounding
- TOP_K = 5 passages are retrieved (and reported, so recall@5 is measurable); the best
  LLM_PASSAGES = 3 that clear the relevance floor go to the model.
- Superseded documents are filtered out (`where={"superseded": False}`) unless the
  question names an older year or version.
- **Relevance floor = 0.69**, chosen from the top retrieval score of every golden
  question:

  | | Top score |
  | --- | --- |
  | Must-abstain q13 (hostel rules) | 0.684 |
  | Must-abstain q14 (hostel fee) | 0.658 |
  | Answerable questions | 0.646 to 0.821 (most 0.70 to 0.82) |

  nomic-embed-text compresses cosine similarity into roughly 0.6 to 0.85, so the two groups
  overlap. 0.69 is the lowest value that blocks both must-abstain questions before the
  model is called, which the gate requires at 100%. The cost: q05 (B+, 0.676) and the
  injection probe q15 (0.646) are declined instead of answered. That does not fail the
  gate, and declining the injection probe is a safe outcome.
- Grounding guards: an answer that cites nothing we retrieved, or that admits in its own
  text that the evidence does not cover the question, is converted to an abstention.
  Found from a real failure: the 1B model invented hostel rules from a loosely related
  passage, then said the handbook does not cover hostels.
- Citations are matched tolerantly: same document (ignoring case, path, extension) and a
  section that matches after normalising, by prefix, or as the only passage from that
  document. The citation shown is rewritten to the retrieved chunk's exact source,
  section and page. Found when a correct answer was declined because the model reworded
  a section name.
- Effect of TOP_K, measured: with TOP_K = 1, recall@3 and recall@5 both fell to 0.73 and
  the answered rate to 0.60 (baseline 0.81 / 0.96 / 0.73); the gate failed.

## Generation
- Ollama on the host, temperature 0.1, `format` = the Answer JSON schema, then Pydantic
  validation, one retry, and a safe fallback (never a 500).
- Measured on a laptop CPU: llama3.2:3b read prompts at ~18 tokens/s and generated at
  ~9 tokens/s; a 5-passage prompt (~3,200 tokens) took ~3.5 minutes and timed out.
  Asking Ollama for an 8,192-token context made it reload the model and time out too.
- Shipped: qwen2.5:1.5b, 3 passages, LLM_NUM_CTX 4096, a 300 s timeout: about 19 s per
  question on average over the golden set, 12-46 s when the model actually runs (declines
  below the relevance floor return in under a second). llama3.2:1b sometimes answered
  correctly but set answered_from_context to false; a worked example in the prompt and
  qwen2.5:1.5b fixed that.
- At temperature 1.2 (failure analysis), three runs of the same question gave three
  differently worded but correct answers ("below 2.00") with no validation failures:
  schema-constrained decoding kept the JSON valid even at high temperature, and only the
  wording drifted. We keep 0.1 because answers should be repeatable.

## Semantic cache
Redis, keyed by `index_version` (see ADR 0003). Thresholds tried:

| Threshold | Paraphrase hit? | False hit? |
| --- | --- | --- |
| 0.88 | not tested | not tested: 0.92 already produced false hits |
| 0.92 | yes | **yes**: q02, q03 and q04 were served q01's CGPA answer |
| 0.95 | yes ("What CGPA..." vs "Which CGPA...") | no: all 15 golden questions got their own answers |

Shipped 0.95: the lowest threshold we tried with zero false hits that still catches a real
paraphrase. The false hit that ruled out 0.92: q02 (prerequisite), q03 (consecutive
warning) and q04 (summer credit hours) were all served q01's cached CGPA answer, in under
half a second each, because they share most of their wording ("student", "academic",
"semester").

## Evaluation method
A golden (source, section) pair matches a retrieved passage when the document is the same
and the golden section appears inside the retrieved section, ignoring case and punctuation.
So "5.4" matches "5.4 Academic Warning" and "refund" matches "Fee Refund Policy". An empty
golden section matches any chunk of that document (used for the short scanned policy).
recall@k is the share of a question's relevant pairs found in the top k; must-abstain
questions have no relevant pairs, are excluded from recall, and are scored by abstention
correctness instead.