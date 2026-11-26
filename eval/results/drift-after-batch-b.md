run 1: baseline.json
run 2: 20261126-155957-after-batch-b.json

| Level | Metric | Run 1 | Run 2 | Difference |
| --- | --- | --- | --- | --- |
| module | cosine_gap | 0.4076 | 0.4076 | +0.0000 |
| module | determinism_max_abs_diff | 0.0000 | 0.0000 | +0.0000 |
| module | dimension | 768.0000 | 768.0000 | +0.0000 |
| module | embed_ms_per_chunk | 2543.3000 | 3645.6000 | +1102.3000 |
| module | max_cosine_unrelated | 0.4582 | 0.4582 | +0.0000 |
| module | mean_cosine_paraphrase | 0.7542 | 0.7542 | +0.0000 |
| module | mean_cosine_unrelated | 0.3466 | 0.3466 | +0.0000 |
| module | min_cosine_paraphrase | 0.5839 | 0.5840 | +0.0001 |
| module | paraphrase_pairs | 15.0000 | 15.0000 | +0.0000 |
| module | unrelated_pairs | 15.0000 | 15.0000 | +0.0000 |
| component | mrr | 0.7348 | 0.7789 | +0.0441 |
| component | ndcg@5 | 0.7722 | 0.8202 | +0.0480 |
| component | recall@3 | 0.7353 | 0.7941 | +0.0588 |
| component | recall@5 | 0.8382 | 0.8971 | +0.0589 |
| component | scored_questions | 34.0000 | 34.0000 | +0.0000 |
| end_to_end | abstention_correctness | 1.0000 | 1.0000 | +0.0000 |
| end_to_end | answered_rate | 0.5128 | 0.5897 | +0.0769 |
| end_to_end | citation_validity | 1.0000 | 1.0000 | +0.0000 |
| end_to_end | citations_total | 22.0000 | 26.0000 | +4.0000 |
| end_to_end | errors | 0.0000 | 0.0000 | +0.0000 |
| end_to_end | faithfulness | 0.7500 | 0.7619 | +0.0119 |
| end_to_end | hand_labelled | 0.0000 | 0.0000 | +0.0000 |
| end_to_end | judged_answers | 20.0000 | 21.0000 | +1.0000 |
| end_to_end | latency_p50_s | 14.3030 | 0.2700 | -14.0330 |
| end_to_end | latency_p95_s | 37.6500 | 34.9240 | -2.7260 |
| end_to_end | must_abstain_total | 5.0000 | 5.0000 | +0.0000 |
| end_to_end | questions | 39.0000 | 39.0000 | +0.0000 |

27 per-question differences
  - q02: answer text differs
  - q03: answer text differs
  - q07: answer text differs
  - q08: answer text differs
  - q09: answer text differs
  - q09: retrieved chunks differ
  - q10: answer text differs
  - q11: answer text differs
  - q12: answer text differs
  - q12: retrieved chunks differ
  - q14: retrieved chunks differ
  - q15: retrieved chunks differ
  - q17: retrieved chunks differ
  - q20: retrieved chunks differ
  - q21: answer text differs
  - q22: abstention changed (False -> True)
  - q22: retrieved chunks differ
  - q23: abstention changed (False -> True)
  - q23: retrieved chunks differ
  - q24: answer text differs
  - q25: answer text differs
  - q30: retrieved chunks differ
  - q36: abstention changed (False -> True)
  - q36: retrieved chunks differ
  - q37: answer text differs
  - q38: retrieved chunks differ
  - q39: answer text differs
