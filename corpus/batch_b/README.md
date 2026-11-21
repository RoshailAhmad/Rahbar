# Batch B: planted problems

Built by `make_batch_b.py`. The clean documents (b07-b10 text) were written by the group.

| File | Planted problem | Check that should catch it |
| --- | --- | --- |
| b01-grading-page-copy.html | exact duplicate of corpus grading-page.html | uniqueness (SHA-256) |
| b02-grading-page-mirror.html | exact duplicate of corpus grading-page.html and of b01 | uniqueness (SHA-256) |
| b03-exam-hall-rules-reposted.md | near-duplicate of b08 (a few words changed) | uniqueness (embedding similarity) |
| b04-academic-rules-truncated.pdf | truncated PDF (first 60% of the bytes) | quality / completeness |
| b05-untitled-notes.md | missing metadata: no name/title, no doc_version, no date | completeness |
| b06-fee-structure-2027-28.html | newer version of corpus fee-structure-page.html (2026-27) | recency (old fee page archived) |
| b07-library-borrowing-rules.md | contains an injected instruction (section 2) | none at verification: D4 retrieval guardrail |
| b08-exam-hall-rules.md | clean | none (should pass) |
| b09-student-societies-guide.md | clean | none (should pass) |
| b10-campus-it-services.md | clean | none (should pass) |
