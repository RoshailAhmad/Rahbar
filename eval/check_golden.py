"""Check eval/golden.jsonl against the Assignment 03 Part B rules.

    python eval/check_golden.py            # exit 0 when every rule holds, 1 otherwise
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PATH = Path(__file__).resolve().parent / "golden.jsonl"
RULES = [
    ("at least 25 questions", lambda q: True, 25),
    ("at least 15 answerable", lambda q: q["type"] == "answerable", 15),
    ("at least 5 unanswerable", lambda q: q["type"] == "unanswerable", 5),
    ("at least 5 hard", lambda q: q["type"] == "hard", 5),
    ("at least 8 written by hand (source: human)", lambda q: q["source"] == "human", 8),
    ("at least 8 synthetic reviewed by hand", lambda q: q["source"] == "synthetic" and q["reviewed"], 8),
]


def main() -> int:
    questions, problems = [], []
    for n, line in enumerate(PATH.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            questions.append(json.loads(line))
        except json.JSONDecodeError as exc:
            problems.append(f"line {n}: not valid JSON ({exc.msg})")
    ids = [q.get("id") for q in questions]
    problems += [f"duplicate id {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for q in questions:
        for key in ("id", "question", "type", "source", "reviewed"):
            if key not in q:
                problems.append(f"{q.get('id')}: missing field '{key}'")
        if "TODO" in q.get("question", ""):
            problems.append(f"{q['id']}: question still says TODO")
        if q.get("type") in ("answerable", "hard"):
            if not q.get("doc_id"):
                problems.append(f"{q['id']}: answerable but no ground-truth doc_id")
            if q.get("page") is None:
                problems.append(f"{q['id']}: answerable but no ground-truth page")
            if not q.get("relevant"):
                problems.append(f"{q['id']}: answerable but no 'relevant' (source, section) list")
        if q.get("source") == "synthetic" and not q.get("reviewed"):
            problems.append(f"{q['id']}: synthetic and not reviewed yet (review it, then set reviewed: true)")

    print(f"{len(questions)} questions in {PATH.name}")
    ok = True
    for name, keep, minimum in RULES:
        count = sum(1 for q in questions if keep(q))
        status = "OK  " if count >= minimum else "FAIL"
        ok &= count >= minimum
        print(f"  {status} {name}: {count}")
    if problems:
        print(f"\n{len(problems)} things to fix:")
        for p in problems:
            print(f"  - {p}")
    return 0 if ok and not problems else 1


if __name__ == "__main__":
    sys.exit(main())
