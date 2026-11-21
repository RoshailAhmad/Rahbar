"""Component level (Assignment 03, Part B): retrieval quality on the golden set.

recall@3, recall@5, MRR and nDCG@5, overall and by question type. Computed from the chunks
the api returned for each question (`retrieved` in the suite rows), so no extra calls are
needed, and any saved result file can be scored again later:

    python eval/levels/component.py eval/results/<run>.json

A retrieved chunk is relevant when it matches one of the question's (source, section) pairs
(the same matching rule as eval/run_eval.py). Questions with no relevant pairs (must-abstain)
are not scored here.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_eval import _matches  # noqa: E402


def relevance(relevant: list[dict], retrieved: list[dict]) -> list[int]:
    """1 for each retrieved chunk (in rank order) that matches a relevant pair, else 0."""
    return [int(any(_matches(gold, ref) for gold in relevant)) for ref in retrieved]


def recall_at_k(relevant: list[dict], retrieved: list[dict], k: int) -> float:
    top = retrieved[:k]
    return sum(1 for gold in relevant if any(_matches(gold, ref) for ref in top)) / len(relevant)


def reciprocal_rank(rels: list[int]) -> float:
    for rank, rel in enumerate(rels, start=1):
        if rel:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(rels: list[int], n_relevant: int, k: int = 5) -> float:
    """Binary-gain nDCG@k. The ideal ranking puts min(n_relevant, k) relevant chunks first."""
    dcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(rels[:k], start=1))
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(n_relevant, k) + 1))
    return min(dcg / ideal, 1.0) if ideal else 0.0


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def score(questions: list[dict], rows: list[dict]) -> dict:
    by_id = {q["id"]: q for q in questions}
    per_metric: dict[str, list[float]] = {"recall@3": [], "recall@5": [], "mrr": [], "ndcg@5": []}
    by_type: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        q = by_id.get(row["id"], row)
        relevant = q.get("relevant") or []
        if not relevant or row.get("error"):
            continue
        retrieved = row.get("retrieved") or []
        rels = relevance(relevant, retrieved)
        values = {"recall@3": recall_at_k(relevant, retrieved, 3), "recall@5": recall_at_k(relevant, retrieved, 5),
                  "mrr": reciprocal_rank(rels), "ndcg@5": ndcg_at_k(rels, len(relevant))}
        bucket = by_type.setdefault(q.get("type", "answerable"), {m: [] for m in per_metric})
        for metric, value in values.items():
            per_metric[metric].append(value)
            bucket[metric].append(value)
        row["component"] = {m: round(v, 4) for m, v in values.items()}
    result: dict = {m: _mean(v) for m, v in per_metric.items()}
    result["scored_questions"] = len(per_metric["mrr"])
    result["by_type"] = {t: {m: _mean(v) for m, v in b.items()} for t, b in sorted(by_type.items())}
    return result


def run(questions: list[dict], rows: list[dict], **_: object) -> dict:
    """Called by eval/suite.py after the end-to-end level has asked every question."""
    return score(questions, rows)


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit("usage: python eval/levels/component.py RESULT.json [GOLDEN.jsonl]")
    saved = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    golden = Path(sys.argv[2]) if len(sys.argv) == 3 else Path(__file__).resolve().parents[1] / "golden.jsonl"
    questions = [json.loads(line) for line in golden.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(json.dumps(score(questions, saved["per_question"]), indent=2))
