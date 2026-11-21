"""Noise test input (Assignment 03, Part B): the golden set with typos in every question.

    python eval/make_typos.py                      # writes eval/golden_typos.jsonl (seed 42)
    make eval-suite ... LABEL=noise-typos GOLDEN=eval/golden_typos.jsonl

Each word of 4+ letters gets one typo (swap, drop or double a letter) with probability 0.3.
Clause numbers and other tokens with digits are left alone. Same seed, same typos.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent


def typo(word: str, rng: random.Random) -> str:
    i = rng.randrange(1, len(word) - 1)
    kind = rng.choice(["swap", "drop", "double"])
    if kind == "swap":
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    if kind == "drop":
        return word[:i] + word[i + 1:]
    return word[:i] + word[i] + word[i:]


def noisy(question: str, rng: random.Random, rate: float) -> str:
    words = question.split(" ")
    return " ".join(typo(w, rng) if len(w) >= 4 and w.isalpha() and rng.random() < rate else w for w in words)


def main() -> int:
    parser = argparse.ArgumentParser(description="golden set with typos")
    parser.add_argument("--golden", type=Path, default=HERE / "golden.jsonl")
    parser.add_argument("--out", type=Path, default=HERE / "golden_typos.jsonl")
    parser.add_argument("--rate", type=float, default=0.3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    lines = []
    for line in args.golden.read_text(encoding="utf-8").splitlines():
        if line.strip():
            q = json.loads(line)
            q["original_question"] = q["question"]
            q["question"] = noisy(q["question"], rng, args.rate)
            lines.append(json.dumps(q, ensure_ascii=False))
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} questions with typos to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
