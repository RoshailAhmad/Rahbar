"""Release gate tests (A3 Part C2): no cluster, no model, no network."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gate import check  # noqa: E402

CFG = {"max_recall5_drop": 0.02, "min_faithfulness": 0.8, "max_p95_seconds": 60,
       "min_citation_validity": 0.95, "on_missing_metric": "skip"}


def result(recall5=0.90, faith=0.9, p95=30.0, cit=1.0, abst=1.0):
    return {"component": {"recall@5": recall5},
            "end_to_end": {"faithfulness": faith, "latency_p95_s": p95,
                           "citation_validity": cit, "abstention_correctness": abst}}


def statuses(rows):
    return {r["metric"]: r["status"] for r in rows}


def test_identical_candidate_passes():
    assert all(r["status"] == "PASS" for r in check(result(), result(), CFG))


def test_recall_drop_of_more_than_two_points_fails():
    assert statuses(check(result(recall5=0.90), result(recall5=0.87), CFG))["recall@5"] == "FAIL"


def test_recall_drop_of_two_points_passes():
    assert statuses(check(result(recall5=0.90), result(recall5=0.88), CFG))["recall@5"] == "PASS"


def test_lower_abstention_than_baseline_fails():
    s = statuses(check(result(abst=1.0), result(abst=0.8), CFG))
    assert s["abstention_correctness"] == "FAIL"


def test_slow_p95_fails():
    assert statuses(check(result(), result(p95=75.0), CFG))["latency p95 (s)"] == "FAIL"


def test_missing_faithfulness_is_skipped_or_failed_by_config():
    assert statuses(check(result(), result(faith=None), CFG))["faithfulness"] == "SKIP"
    strict = {**CFG, "on_missing_metric": "fail"}
    assert statuses(check(result(), result(faith=None), strict))["faithfulness"] == "FAIL"


def test_recall_falls_back_to_per_question_values():
    base = {"end_to_end": {}, "per_question": [{"recall@5": 1.0}, {"recall@5": 0.5}, {"recall@5": None}]}
    rows = check(base, base, CFG)
    assert rows[0]["baseline"] == 0.75 and rows[0]["status"] == "PASS"
