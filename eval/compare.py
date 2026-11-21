"""Compare two suite result files metric by metric (Assignment 03, Part B stochasticity).

    python eval/compare.py eval/results/<run1>.json eval/results/<run2>.json

Prints every numeric metric of the three levels side by side with the difference, and the
questions whose answer or abstention changed between the two runs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def numeric(block: dict) -> dict[str, float]:
    return {k: float(v) for k, v in block.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}


def main() -> int:
    if len(sys.argv) != 3:
        sys.exit("usage: python eval/compare.py RUN1.json RUN2.json")
    a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in sys.argv[1:])
    print(f"run 1: {Path(sys.argv[1]).name}\nrun 2: {Path(sys.argv[2]).name}\n")
    print("| Level | Metric | Run 1 | Run 2 | Difference |\n| --- | --- | --- | --- | --- |")
    for level in ("module", "component", "end_to_end"):
        m1, m2 = numeric(a.get(level) or {}), numeric(b.get(level) or {})
        for key in sorted(set(m1) | set(m2)):
            v1, v2 = m1.get(key), m2.get(key)
            diff = "-" if v1 is None or v2 is None else f"{v2 - v1:+.4f}"
            f1 = "-" if v1 is None else f"{v1:.4f}"
            f2 = "-" if v2 is None else f"{v2:.4f}"
            print(f"| {level} | {key} | {f1} | {f2} | {diff} |")

    q1 = {q["id"]: q for q in a.get("per_question", [])}
    q2 = {q["id"]: q for q in b.get("per_question", [])}
    changed = []
    for qid in sorted(set(q1) & set(q2)):
        x, y = q1[qid], q2[qid]
        if x.get("answered_from_context") != y.get("answered_from_context"):
            changed.append(f"{qid}: abstention changed ({x.get('answered_from_context')} -> {y.get('answered_from_context')})")
        elif (x.get("answer") or "").strip() != (y.get("answer") or "").strip():
            changed.append(f"{qid}: answer text differs")
        if [r.get("chunk_id") for r in x.get("retrieved", [])] != [r.get("chunk_id") for r in y.get("retrieved", [])]:
            changed.append(f"{qid}: retrieved chunks differ")
    print(f"\n{len(changed)} per-question differences")
    for line in changed:
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
