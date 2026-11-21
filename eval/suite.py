"""RAHBAR evaluation suite (Assignment 03, Part B): one command, three levels.

    python eval/suite.py --api http://127.0.0.1:8081 --host rahbar.local --label baseline

Writes <out-dir>/<YYYYmmdd-HHMMSS>-<label>.json and a .md summary table next to it.
  module      embedding quality (eval/levels/module.py, Mehak)       -> "pending" until it exists
  component   retrieval quality (eval/levels/component.py, Mehak)    -> "pending" until it exists
  end_to_end  answers through the live API: abstention, citations, latency (this file)
The release gate is a separate step: eval/gate.py compares two result files.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_eval import ask, citation_validity, recall_at_k  # noqa: E402


def load_golden(path: Path) -> list[dict]:
    """eval/golden.jsonl (one JSON object per line) or the A2 golden.yaml."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        questions = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        questions = (yaml.safe_load(text) or {}).get("questions") or []
    if not questions:
        sys.exit(f"no questions in {path}")
    for q in questions:
        q.setdefault("type", "answerable")
        q["must_abstain"] = bool(q.get("must_abstain")) or q["type"] in ("abstain", "unanswerable")
        q.setdefault("relevant", [])
    return questions


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile: p95 of 25 values is the 24th smallest."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return round(ordered[rank - 1], 3)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def run_level(name: str, **kwargs) -> dict:
    """Call eval/levels/<name>.py:run(**kwargs) if it exists yet."""
    try:
        module = importlib.import_module(f"levels.{name}")
    except ModuleNotFoundError:
        return {"status": "pending"}
    try:
        return {"status": "ok", **module.run(**kwargs)}
    except Exception as exc:  # one level failing must not lose the other two
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


def end_to_end(client: httpx.Client, api: str, questions: list[dict]) -> tuple[dict, list[dict]]:
    rows, seconds = [], []
    total_cit = valid_cit = abstain_total = abstain_ok = 0
    for q in questions:
        started = time.perf_counter()
        try:
            response = ask(client, api, q["question"])
            error = None
        except httpx.HTTPError as exc:
            response, error = {}, f"{type(exc).__name__}: {exc}"
        elapsed = round(time.perf_counter() - started, 3)
        seconds.append(elapsed)
        answered = bool(response.get("answered_from_context"))
        citations = response.get("citations") or []
        validity = citation_validity(response)
        if validity is not None:
            total_cit += len(citations)
            valid_cit += round(validity * len(citations))
        if q["must_abstain"]:
            abstain_total += 1
            abstain_ok += int(not answered)
        retrieved = response.get("retrieved") or []
        rows.append({
            "id": q["id"], "type": q["type"], "question": q["question"],
            "must_abstain": q["must_abstain"], "answered_from_context": answered,
            "answer": response.get("answer"), "citations": citations,
            "citation_validity": validity, "retrieved": retrieved,
            "recall@5": recall_at_k(q["relevant"], retrieved, 5),
            "cached": bool(response.get("cached")), "request_id": response.get("request_id"),
            "seconds": elapsed, "error": error,
        })
        print(f"  {q['id']:<6} {elapsed:>7.2f}s  {'ANS' if answered else 'ABS'}  {q['question'][:55]}")

    metrics = {
        "status": "ok",
        "questions": len(questions),
        "abstention_correctness": round(abstain_ok / abstain_total, 4) if abstain_total else None,
        "must_abstain_total": abstain_total,
        "citation_validity": round(valid_cit / total_cit, 4) if total_cit else None,
        "citations_total": total_cit,
        "answered_rate": _mean([float(r["answered_from_context"]) for r in rows]),
        "latency_p50_s": percentile(seconds, 50),
        "latency_p95_s": percentile(seconds, 95),
        "errors": sum(1 for r in rows if r["error"]),
        "faithfulness": None,  # Phase 2: LLM judge + hand labels
    }
    return metrics, rows


def config_snapshot(client: httpx.Client, api: str, args: argparse.Namespace) -> dict:
    snap = {
        "label": args.label, "api": api, "golden": str(args.golden), "seed": args.seed,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "embed_model": os.environ.get("EMBED_MODEL"), "collection": os.environ.get("CHROMA_COLLECTION"),
    }
    try:
        snap["git_sha"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, check=False,
                                         text=True, cwd=HERE, timeout=5).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        snap["git_sha"] = None
    try:  # the api reports its collection, chunk count and embedding model on /readyz
        snap["readyz"] = client.get(f"{api}/readyz").json()
    except (httpx.HTTPError, ValueError):
        snap["readyz"] = None
    return snap


def _fmt(value) -> str:
    if value is None:
        return "-"
    return f"{value:.4f}" if isinstance(value, float) else str(value)


def summary_md(result: dict) -> str:
    lines = [f"# Eval: {result['config']['label']} ({result['config']['timestamp']})", "",
             "| Level | Metric | Value |", "| --- | --- | --- |"]
    for level in ("module", "component", "end_to_end"):
        block = result[level]
        if block.get("status") != "ok":
            lines.append(f"| {level} | status | {block.get('status')} {block.get('error', '')} |")
            continue
        for key, value in block.items():
            if key != "status" and not isinstance(value, (dict, list)):
                lines.append(f"| {level} | {key} | {_fmt(value)} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="RAHBAR three-level evaluation suite")
    parser.add_argument("--api", required=True, help="e.g. http://127.0.0.1:8081 or http://api:8000")
    parser.add_argument("--host", help="Host header for the Ingress, e.g. rahbar.local")
    parser.add_argument("--golden", type=Path, default=HERE / "golden.jsonl")
    parser.add_argument("--label", default="run")
    parser.add_argument("--out-dir", type=Path, default=Path(os.environ.get("RESULTS_DIR", HERE / "results")))
    parser.add_argument("--seed", type=int, default=int(os.environ.get("EVAL_SEED", "42")))
    args = parser.parse_args()
    if not args.golden.exists() and args.golden.name == "golden.jsonl":
        args.golden = HERE / "golden.yaml"  # until Mehak's golden.jsonl lands

    random.seed(args.seed)
    api = args.api.rstrip("/")
    questions = load_golden(args.golden)
    headers = {"Host": args.host} if args.host else {}
    with httpx.Client(timeout=360.0, headers=headers) as client:
        config = config_snapshot(client, api, args)
        print(f"suite '{args.label}': {len(questions)} questions against {api}")
        module = run_level("module", seed=args.seed)
        component = run_level("component", questions=questions, client=client, api=api)
        e2e, rows = end_to_end(client, api, questions)

    result = {"config": config, "module": module, "component": component,
              "end_to_end": e2e, "per_question": rows}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    out = args.out_dir / f"{stamp}-{args.label}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    md = summary_md(result)
    out.with_suffix(".md").write_text(md, encoding="utf-8")
    print("\n" + md + f"\nwritten: {out}\n         {out.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
