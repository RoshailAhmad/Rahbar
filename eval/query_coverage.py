"""Query coverage check (Assignment 03, Part E2/E4; RAGOps paper 4.2.7).

For every live query, find the most similar golden question (cosine of the pinned
EMBED_MODEL's embeddings). A live query is covered when that similarity is at or above
--threshold. Coverage = covered / live queries. Uncovered queries are listed, grouped by
topic. Exit code 1 when coverage is below --target (the paper's example flags a gap when
fewer than 85% of live queries reach the score), so CI or a Job can fail on it.

    python eval/query_coverage.py                            # threshold 0.80, target 0.85
    python eval/query_coverage.py --threshold 0.75 --label after-e4
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
Embedder = Callable[[list[str]], list[list[float]]]


def ollama_embedder(url: str | None = None, model: str | None = None) -> Embedder:
    base = (url or os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
    name = model or os.environ.get("EMBED_MODEL", "nomic-embed-text")

    def embed(texts: list[str]) -> list[list[float]]:
        with httpx.Client(timeout=300.0) as client:
            response = client.post(f"{base}/api/embed", json={"model": name, "input": texts})
            response.raise_for_status()
            return response.json()["embeddings"]

    return embed


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def coverage(live: list[dict], golden: list[dict], embed: Embedder, threshold: float) -> dict:
    live_vecs = embed([q["query"] for q in live])
    gold_vecs = embed([g["question"] for g in golden])
    rows = []
    for q, v in zip(live, live_vecs):
        scores = [cosine(v, g) for g in gold_vecs]
        best = max(range(len(scores)), key=scores.__getitem__)
        rows.append({"id": q["id"], "query": q["query"], "topic": q.get("topic", "unlabelled"),
                     "nearest_golden": golden[best]["id"], "nearest_question": golden[best]["question"],
                     "similarity": round(scores[best], 4), "covered": scores[best] >= threshold})
    covered = sum(r["covered"] for r in rows)
    groups: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        if not r["covered"]:
            groups[r["topic"]].append(r["id"])
    return {"threshold": threshold, "live_queries": len(rows), "golden_questions": len(golden),
            "covered": covered, "coverage": round(covered / len(rows), 4) if rows else 0.0,
            "uncovered_by_topic": dict(sorted(groups.items(), key=lambda kv: -len(kv[1]))), "rows": rows}


def report_md(result: dict, target: float) -> str:
    lines = [f"# Query coverage ({result['label']})", "",
             f"Threshold {result['threshold']}, target {target:.0%}: **{result['covered']}/{result['live_queries']} "
             f"= {result['coverage']:.1%}** covered ({result['golden_questions']} golden questions).", "",
             "| Uncovered topic | Queries |", "| --- | --- |"]
    for topic, ids in result["uncovered_by_topic"].items():
        lines.append(f"| {topic} | {len(ids)}: {', '.join(ids)} |")
    lines += ["", "| Live query | Nearest golden | Similarity | Covered |", "| --- | --- | --- | --- |"]
    for r in sorted(result["rows"], key=lambda r: r["similarity"]):
        lines.append(f"| {r['id']} {r['query']} | {r['nearest_golden']} | {r['similarity']:.3f} | "
                     f"{'yes' if r['covered'] else 'NO'} |")
    return "\n".join(lines) + "\n"


def main(embed: Embedder | None = None) -> int:
    parser = argparse.ArgumentParser(description="query coverage of the golden set")
    parser.add_argument("--live", type=Path, default=HERE / "live_queries.jsonl")
    parser.add_argument("--golden", type=Path, default=HERE / "golden.jsonl")
    parser.add_argument("--threshold", type=float, default=float(os.environ.get("COVERAGE_THRESHOLD", "0.80")))
    parser.add_argument("--target", type=float, default=float(os.environ.get("COVERAGE_TARGET", "0.85")))
    parser.add_argument("--label", default="run")
    parser.add_argument("--out-dir", type=Path, default=HERE / "results")
    parser.add_argument("--ollama", help="Ollama URL (default: $OLLAMA_URL)")
    args = parser.parse_args()

    result = coverage(read_jsonl(args.live), read_jsonl(args.golden), embed or ollama_embedder(args.ollama),
                      args.threshold)
    result["label"] = args.label
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    out = args.out_dir / f"coverage-{stamp}-{args.label}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    md = report_md(result, args.target)
    out.with_suffix(".md").write_text(md, encoding="utf-8")
    print(md.split("\n| Live query")[0])
    print(f"written: {out}")
    if result["coverage"] < args.target:
        print(f"COVERAGE {result['coverage']:.1%} IS BELOW THE TARGET {args.target:.0%}: expand the golden set")
        return 1
    print(f"coverage {result['coverage']:.1%} meets the target {args.target:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
