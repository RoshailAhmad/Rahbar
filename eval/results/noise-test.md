run 1: baseline.json
run 2: 20261126-105029-noise-typos.json

| Level | Metric | Run 1 | Run 2 | Difference |
| --- | --- | --- | --- | --- |
| module | cosine_gap | 0.4076 | 0.4076 | +0.0000 |
| module | determinism_max_abs_diff | 0.0000 | 0.0000 | +0.0000 |
| module | dimension | 768.0000 | 768.0000 | +0.0000 |
| module | embed_ms_per_chunk | 2543.3000 | 3147.2000 | +603.9000 |
| module | max_cosine_unrelated | 0.4582 | 0.4582 | +0.0000 |
| module | mean_cosine_paraphrase | 0.7542 | 0.7542 | +0.0000 |
| module | mean_cosine_unrelated | 0.3466 | 0.3466 | +0.0000 |
| module | min_cosine_paraphrase | 0.5839 | 0.5840 | +0.0001 |
| module | paraphrase_pairs | 15.0000 | 15.0000 | +0.0000 |
| module | unrelated_pairs | 15.0000 | 15.0000 | +0.0000 |
| component | mrr | 0.7348 | 0.6270 | -0.1078 |
| component | ndcg@5 | 0.7722 | 0.6786 | -0.0936 |
| component | recall@3 | 0.7353 | 0.6618 | -0.0735 |
| component | recall@5 | 0.8382 | 0.8088 | -0.0294 |
| component | scored_questions | 34.0000 | 34.0000 | +0.0000 |
| end_to_end | abstention_correctness | 1.0000 | 0.8000 | -0.2000 |
| end_to_end | answered_rate | 0.5128 | 0.5128 | +0.0000 |
| end_to_end | citation_validity | 1.0000 | 1.0000 | +0.0000 |
| end_to_end | citations_total | 22.0000 | 23.0000 | +1.0000 |
| end_to_end | errors | 0.0000 | 0.0000 | +0.0000 |
| end_to_end | faithfulness | 0.7500 | 0.6500 | -0.1000 |
| end_to_end | hand_labelled | 0.0000 | 0.0000 | +0.0000 |
| end_to_end | judged_answers | 20.0000 | 20.0000 | +0.0000 |
| end_to_end | latency_p50_s | 14.3030 | 12.1440 | -2.1590 |
| end_to_end | latency_p95_s | 37.6500 | 58.9870 | +21.3370 |
| end_to_end | must_abstain_total | 5.0000 | 5.0000 | +0.0000 |
| end_to_end | questions | 39.0000 | 39.0000 | +0.0000 |

50 per-question differences
  - q01: answer text differs
  - q01: retrieved chunks differ
  - q02: answer text differs
  - q03: abstention changed (True -> False)
  - q03: retrieved chunks differ
  - q06: answer text differs
  - q06: retrieved chunks differ
  - q07: answer text differs
  - q07: retrieved chunks differ
  - q08: answer text differs
  - q08: retrieved chunks differ
  - q09: answer text differs
  - q10: answer text differs
  - q11: abstention changed (True -> False)
  - q11: retrieved chunks differ
  - q12: abstention changed (True -> False)
  - q12: retrieved chunks differ
  - q13: retrieved chunks differ
  - q14: retrieved chunks differ
  - q15: retrieved chunks differ
  - q16: retrieved chunks differ
  - q17: retrieved chunks differ
  - q18: abstention changed (False -> True)
  - q19: answer text differs
  - q19: retrieved chunks differ
  - q21: answer text differs
  - q21: retrieved chunks differ
  - q22: abstention changed (False -> True)
  - q22: retrieved chunks differ
  - q23: retrieved chunks differ
  - q24: retrieved chunks differ
  - q25: answer text differs
  - q25: retrieved chunks differ
  - q26: answer text differs
  - q26: retrieved chunks differ
  - q27: retrieved chunks differ
  - q28: answer text differs
  - q28: retrieved chunks differ
  - q29: retrieved chunks differ
  - q30: retrieved chunks differ
  - q31: retrieved chunks differ
  - q32: retrieved chunks differ
  - q34: retrieved chunks differ
  - q35: answer text differs
  - q36: retrieved chunks differ
  - q37: answer text differs
  - q37: retrieved chunks differ
  - q38: retrieved chunks differ
  - q39: abstention changed (False -> True)
  - q39: retrieved chunks differ
release gate  config=eval/gate.yaml
  baseline : baseline.json
  candidate: 20261126-105029-noise-typos.json

  metric                  rule                    baseline  candidate  status
  recall@5                >= baseline - 0.02        0.8382     0.8088  FAIL
  faithfulness            >= 0.8                    0.7500     0.6500  FAIL
  latency p95 (s)         <= 60.0                  37.6500    58.9870  PASS
  citation_validity       >= 0.95                   1.0000     1.0000  PASS
  abstention_correctness  >= baseline               1.0000     0.8000  FAIL

GATE FAILED: do not release
