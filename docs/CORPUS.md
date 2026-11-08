# Corpus

Source: FAST-NUCES public website (nu.edu.pk), public pages only · Documents: 9 · Pages: 281 (279 PDF pages + 2 HTML pages)

The PDFs are not committed. `corpus/MANIFEST.md` lists every URL with its SHA-256, and
`corpus/fetch.py` downloads them again (`python corpus/fetch.py`, then `python corpus/fetch.py --verify`).

| File | Pages | doc_version | superseded |
| --- | --- | --- | --- |
| academic-rules-handbook-jun-2026.pdf | 53 | 2026-06 | false |
| undergraduate-academic-rules-aug-2023.pdf | 26 | 2023-08 | true |
| prospectus-2026-academic-rules-and-regulations.pdf | 5 | 2026 | false |
| student-handbook-jun-2026.pdf | 64 | 2026-06 | false |
| annual-report-2019-20.pdf | see note | 2019-20 | false |
| annual-report-2023-24.pdf | see note | 2023-24 | false |
| faculty-entrepreneurship-and-technical-start-ups-policy.pdf | 8 | 2022-05 | false |
| fee-structure-page.html | 1 | 2026-27 | false |
| grading-page.html | 1 | 2026 | false |

Note: the two annual reports together make up the remaining 123 PDF pages (279 in total).

| # | Required property | Document(s) that provide it | Evidence or notes |
| --- | --- | --- | --- |
| 1 | At least 6 documents, 40 pages | All 9 files above | 9 documents, 281 pages in total (279 PDF + 2 HTML). |
| 2 | Two versions of one policy | `undergraduate-academic-rules-aug-2023.pdf` (old) and `academic-rules-handbook-jun-2026.pdf` (current); the 5-page prospectus rules restate the 2026 rules with different clause numbers | The 2026 handbook supersedes the 2023 rules. `corpus/sources.yaml` sets `superseded: true` and `doc_version: "2023-08"` on the old one; `fetch.py` copies this into `_index.json`, the indexer stores `doc_version` and `superseded` on every chunk, and the retriever filters out `superseded: true` unless the question explicitly asks about an older version. |
| 3 | Scanned, image-only PDF | `faculty-entrepreneurship-and-technical-start-ups-policy.pdf` | pdfplumber extracts 0 characters on all 8 pages (`[0, 0, 0, 0, 0, 0, 0, 0]`), so the file has no text layer. The indexer detects empty pages and OCRs them with Tesseract inside the indexer image. |
| 4 | A table with real information | `fee-structure-page.html`, `grading-page.html`, `annual-report-2019-20.pdf`, `annual-report-2023-24.pdf` | Tuition per credit hour, miscellaneous fees and the refund timeline; grade letters and grade points; faculty, graduates and publications by campus. Extraction writes each table row as `col1 | col2 | col3` so the columns stay together. |
| 5 | Long definitions | `student-handbook-jun-2026.pdf` | The Generative AI policy runs over several numbered sub-sections with long definitions; a fixed-size chunker would cut them in half, so we chunk by section heading first, then paragraph, then sentence. |
| 6 | A deliberately absent topic | Hostel and transport rules: the prospectus's "Transport and Hostel Facilities" PDF is deliberately left out | Students plausibly ask about hostel rules, fees and room applications. The Student Handbook only mentions that hostels exist, so the system must decline (golden questions q13 and q14, `must_abstain: true`). |
| 7 | Exact-term content | `academic-rules-handbook-jun-2026.pdf`, `prospectus-2026-academic-rules-and-regulations.pdf`, `fee-structure-page.html` | Clause numbers (attendance 1.21 in the handbook but clause 1 in the prospectus; academic warning 5.4), the CGPA threshold 2.00, and fees per credit hour. Embeddings blur exact terms like these, which is why exact-term recall is reported separately in `docs/PIPELINE.md`. |