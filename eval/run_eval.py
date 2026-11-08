#!/usr/bin/env python3
"""Score a running RAHBAR against a golden set, and gate CI on the result (section 5).

    python eval/run_eval.py --api http://<ingress>                 # your corpus
    python eval/run_eval.py --api ... --golden eval/fixtures/golden.fixture.yaml
    python eval/run_eval.py --api ... --update-baseline            # after a deliberate improvement

Exit code 0 when every gate passes, 1 when any fails. CI relies on that exit code.

Given: talking to the API, reading the golden set, writing results.json, the exit
code. Yours: the four functions marked STARTER-TODO. They are the evaluation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent

# The gate from section 5.4. Change these only with a reason written in docs/PIPELINE.md.
MAX_RECALL5_DROP = 0.05        # recall@5 may fall at most 5 points below the baseline
MIN_CITATION_VALIDITY = 0.95   # at least 95% of citations must match retrieved passages
REQUIRED_ABSTENTION = 1.0      # every must-abstain question must be declined


def load_golden(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    questions = data.get("questions") or []
    if not questions:
        sys.exit(f"no questions in {path}")
    return questions


def ask(client: httpx.Client, api: str, question: str) -> dict:
    """POST one question and return the AskResponse as a dict (see api/app/schemas.py)."""
    response = client.post(f"{api.rstrip('/')}/api/ask", json={"question": question})
    response.raise_for_status()
    return response.json()


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9.]+", " ", (text or "").lower()).strip()


def _source_key(source: str | None) -> str:
    name = (source or "").replace("\\", "/").rsplit("/", 1)[-1]
    return _norm(re.sub(r"\.(pdf|html?|md|txt)$", "", name, flags=re.IGNORECASE))


def _matches(gold: dict, ref: dict) -> bool:
    """A golden (source, section) pair matches a retrieved passage when the document is
    the same and the golden section appears in the retrieved section, case- and
    punctuation-insensitively. So "5.4" matches "5.4 Academic Warning" and "refund"
    matches "3. Refunds". An empty golden section matches any chunk of that document.
    (Documented in docs/PIPELINE.md.)"""
    if _source_key(gold.get("source")) != _source_key(ref.get("source")):
        return False
    wanted = _norm(gold.get("section"))
    return not wanted or wanted in _norm(ref.get("section"))


def recall_at_k(relevant: list[dict], retrieved: list[dict], k: int) -> float | None:
    """Fraction of the relevant (source, section) pairs found in the top k retrieved.
    Return None when the question has no relevant passages (must-abstain questions)."""
    if not relevant:
        return None
    top = retrieved[:k]
    found = sum(1 for gold in relevant if any(_matches(gold, ref) for ref in top))
    return found / len(relevant)


def citation_validity(response: dict) -> float | None:
    """Fraction of the response's citations that match a passage in response['retrieved'].
    Return None when there are no citations."""
    citations = response.get("citations") or []
    if not citations:
        return None
    retrieved = {(r.get("source"), r.get("section")) for r in response.get("retrieved") or []}
    valid = sum(1 for c in citations if (c.get("source"), c.get("section")) in retrieved)
    return valid / len(citations)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarise(rows: list[dict]) -> dict:
    """Overall recall@3, recall@5, citation validity and abstention correctness, plus
    recall@5 broken down by question type. This dict becomes results.json."""
    per_question = []
    r3: list[float] = []
    r5: list[float] = []
    by_type: dict[str, dict[str, list[float]]] = {}
    total_citations = valid_citations = 0
    abstain_total = abstain_correct = 0

    for row in rows:
        response = row["response"]
        retrieved = response.get("retrieved") or []
        rec3 = recall_at_k(row["relevant"], retrieved, 3)
        rec5 = recall_at_k(row["relevant"], retrieved, 5)
        if rec3 is not None and rec5 is not None:
            r3.append(rec3)
            r5.append(rec5)
            bucket = by_type.setdefault(row["type"], {"recall@3": [], "recall@5": []})
            bucket["recall@3"].append(rec3)
            bucket["recall@5"].append(rec5)

        citations = response.get("citations") or []
        validity = citation_validity(response)
        if validity is not None:
            total_citations += len(citations)
            valid_citations += round(validity * len(citations))

        answered = bool(response.get("answered_from_context"))
        if row["must_abstain"]:
            abstain_total += 1
            abstain_correct += int(not answered)

        expect = row.get("expect")
        per_question.append({
            "id": row["id"], "type": row["type"], "recall@3": rec3, "recall@5": rec5,
            "answered_from_context": answered, "must_abstain": row["must_abstain"],
            "citations": len(citations), "citation_validity": validity,
            "expect_found": (str(expect).lower() in str(response.get("answer", "")).lower()
                             if expect else None),
            "cached": bool(response.get("cached", False)), "seconds": row.get("seconds"),
            "top_retrieved": [f"{r.get('source')} | {r.get('section')} | {r.get('score')}"
                              for r in retrieved[:3]],
        })

    return {
        "recall@3": _mean(r3),
        "recall@5": _mean(r5),
        "recall_by_type": {t: {k: _mean(v) for k, v in b.items()}
                           for t, b in sorted(by_type.items())},
        # Micro-average over all citations; 1.0 when the run produced no citations at all.
        "citation_validity": round(valid_citations / total_citations, 4)
                             if total_citations else 1.0,
        "citations_total": total_citations,
        "abstention_correctness": round(abstain_correct / abstain_total, 4)
                                  if abstain_total else 1.0,
        "must_abstain_total": abstain_total,
        "answered_rate": _mean([float(bool(r["response"].get("answered_from_context")))
                                for r in rows]),
        "mean_seconds": _mean([float(r.get("seconds") or 0) for r in rows]),
        "per_question": per_question,
    }


def gate(results: dict, baseline: dict | None) -> list[str]:
    """Return one message per failed gate (section 5.4); an empty list means pass."""
    failures = []
    recall5 = results.get("recall@5") or 0.0
    if baseline and baseline.get("recall@5") is not None:
        floor = baseline["recall@5"] - MAX_RECALL5_DROP
        if recall5 < floor - 1e-9:
            failures.append(f"recall@5 {recall5:.3f} is more than "
                            f"{MAX_RECALL5_DROP * 100:.0f} points below the baseline "
                            f"{baseline['recall@5']:.3f}")
    if results.get("abstention_correctness", 1.0) < REQUIRED_ABSTENTION:
        answered = [q["id"] for q in results.get("per_question", [])
                    if q["must_abstain"] and q["answered_from_context"]]
        failures.append(f"must-abstain questions answered from context: {answered}")
    if results.get("citation_validity", 1.0) < MIN_CITATION_VALIDITY:
        failures.append(f"citation validity {results['citation_validity']:.3f} is below "
                        f"{MIN_CITATION_VALIDITY:.2f}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate RAHBAR against a golden set.")
    parser.add_argument("--api", required=True, help="base URL, e.g. http://192.168.49.2")
    parser.add_argument("--host", help="Host header, when your Ingress rule names a host")
    parser.add_argument("--golden", type=Path, default=HERE / "golden.yaml")
    parser.add_argument("--baseline", type=Path, default=HERE / "baseline.json")
    parser.add_argument("--out", type=Path, default=HERE / "results.json")
    parser.add_argument("--update-baseline", action="store_true",
                        help="write these results as the new baseline")
    args = parser.parse_args()

    questions = load_golden(args.golden)
    rows = []
    headers = {"Host": args.host} if args.host else {}
    with httpx.Client(timeout=360.0, headers=headers) as client:
        for q in questions:
            started = time.perf_counter()
            response = ask(client, args.api, q["question"])
            rows.append({
                "id": q["id"], "type": q.get("type", "ordinary"),
                "must_abstain": bool(q.get("must_abstain", False)),
                "relevant": q.get("relevant") or [],
                "expect": q.get("expect"),
                "response": response,
                "seconds": round(time.perf_counter() - started, 2),
            })
            print(f"  {q['id']:<5} {rows[-1]['seconds']:>6.2f}s  {q['question'][:60]}")

    try:
        results = summarise(rows)
        baseline = json.loads(args.baseline.read_text()) if args.baseline.exists() else None
        failures = gate(results, baseline)
    except NotImplementedError as exc:
        print(f"\nnot implemented yet: {exc}")
        return 2

    results["golden"] = str(args.golden)
    results["questions"] = len(rows)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nresults written to {args.out}")
    if args.update_baseline:
        args.baseline.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"baseline updated: {args.baseline}")

    if failures:
        print("\nGATE FAILED")
        for message in failures:
            print(f"  - {message}")
        return 1
    print("\ngate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
