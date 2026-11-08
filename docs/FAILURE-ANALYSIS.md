# Failure analysis

Four stages broken (on purpose, or found for real while building), each with its symptom,
the diagnosis, the stage, how we would have noticed it without causing it, and the remedy.
From the RAG lecture: only F is the model's fault, so check A to E first.

## A · Extraction: the scanned PDF indexed without OCR
**How it broke.** On Mehak's laptop the indexer ran without Tesseract and Poppler, so the
OCR step logged "ocr unavailable" and the scanned
`faculty-entrepreneurship-and-technical-start-ups-policy.pdf` (8 pages, no text layer:
pdfplumber returned 0 characters on every page) went into the index almost empty.

**Symptom.** Golden question q08 ("What is the policy on faculty starting a technical
start-up?") retrieved annual-report chunks instead: its top score was only 0.646 and none
of the top 5 came from the policy document. The system either declined or answered from
the wrong document.

**Diagnosis.** Stage A, extraction: the document was in the corpus but its text was not.
In the cluster image, which has Tesseract, the indexer logged
`"msg": "ocr used", "pages": [1..8], "recovered_chars": 11791` for that file, and q08
reached recall@5 = 1.0. The same run showed the 2023 academic rules were also a scan
(24 of 26 pages OCR'd, 31,701 characters).

**How we would have noticed without causing it.** The indexer's per-document log: a
document with very few chunks for its page count (`"chunked" ... "chunks"`), or no
`"ocr used"` line for a known scan; and recall@5 for the question that targets it.

**Remedy.** OCR pages with fewer than 20 characters of text (pdf2image + Tesseract,
installed in the indexer image); count chunks per document after every index.

## B · Chunking: chunks too large (600/80), and headings misdetected
**How it broke.** We re-indexed with CHUNK_SIZE 600 and CHUNK_OVERLAP 80 words instead of
the shipped 400/50, and re-ran the golden set.

**Symptom.** recall@3 fell from 0.81 to 0.65 and recall@5 from 0.96 to 0.81, and
`eval/run_eval.py` failed the gate: "recall@5 0.808 is more than 5 points below the
baseline 0.962".

**Diagnosis.** Stage B, chunking: a 600-word chunk mixes several clauses, so its single
vector is a blur of all of them and the specific clause the question asks about no longer
stands out. A real chunking bug showed the other side of stage B: the first heading rule
took numbered list sentences ("14 Political activities or campaigns are strictly
prohibited within") as section titles, and that text appeared as a citation in the UI.

**How we would have noticed without causing it.** recall@5 against the committed baseline
(the CI gate does this on every pull request); the `section` names in `retrieved` and in
the per-request log line.

**Remedy.** Ship 400/50, chosen from the three measured configurations in
docs/PIPELINE.md; a numbered line counts as a heading only if it reads like a title.

## C · Retrieval: TOP_K = 1
**How it broke.** We set TOP_K to 1 in the ConfigMap, restarted the api and re-ran the
golden set.

**Symptom.** recall@3 0.731 and recall@5 0.7308 (baseline 0.81 / 0.96); answered rate 0.6
(baseline 0.73). The gate failed on recall@5.

**Diagnosis.** Stage C, retrieval: with one passage, every question whose best evidence
ranks second to fifth loses it. Our exact-term questions are hit hardest: in the baseline,
q11 (clause 1.21) and q05 (B+) only find their passage at rank 4-5. When the single passage
is below the relevance floor, the api abstains.

**How we would have noticed without causing it.** recall@k in eval/results.json, a rising
`rahbar_abstentions_total`, and the per-request log line listing a single chunk id.

**Remedy.** TOP_K back to 5. We retrieve 5 for measurement and send the best 3
(LLM_PASSAGES) to the model to keep answers fast.

## F · Generation: the model invented an answer
**How it broke.** With llama3.2:1b, a 0.35 relevance floor and no grounding guards, we
asked the must-abstain question "What are the hostel rules for female students?".

**Symptom.** A confident, invented answer: girls and boys may not sit together in
dormitories, hostel authorities take disciplinary action, and so on. It ended with "the
hostel rules are not covered by the student handbook", contradicting itself. A second
symptom from the same model: a correct answer ("2.0") returned with
`answered_from_context: false` and no citations.

**Diagnosis.** Stage F, generation, but only after checking A to E: retrieval had found a
loosely related Student Handbook passage (score 0.68) about seating rules, it passed the
too-low floor, and a 1B model filled the gap from general knowledge. The corpus has no
hostel document, on purpose.

**How we would have noticed without causing it.** Abstention correctness below 100% in
eval/results.json (the gate requires 100%); answers whose own text says "not covered".

**Remedy.** A relevance floor of 0.69, chosen from the scores of every golden question;
grounding guards (an answer that cites nothing retrieved, or admits the evidence does not
cover the question, becomes an abstention); a worked example in the prompt; and
qwen2.5:1.5b, which follows the answer schema reliably. In the baseline, abstention
correctness is 1.0.