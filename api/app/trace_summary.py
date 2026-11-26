"""Monitoring summary over a time window of traces (Assignment 03, Part D3; paper 4.2.6).

    kubectl exec -n rahbar deploy/api -- python -m app.trace_summary --since 1h
    python scripts/trace_summary.py --since 24h --dir traces      # from copied trace files

Reports, for the traces in the window: the top-1 similarity distribution (min, p10, p50, p90,
max and a histogram), abstention rate, cache hit rate, fallback rate, p50/p95 latency per
stage, and injection attempts flagged by each guardrail rail. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

BUCKETS = (0.5, 0.6, 0.65, 0.69, 0.75, 0.8, 0.85, 0.9, 1.01)


def default_dir() -> Path:
    if os.environ.get("TRACE_DIR"):
        return Path(os.environ["TRACE_DIR"])
    return Path(os.environ.get("DATA_DIR", "/data")) / "traces"


def parse_since(text: str) -> timedelta:
    m = re.fullmatch(r"(\d+)([mhd])", text.strip())
    if not m:
        raise SystemExit("--since must look like 30m, 1h or 7d")
    n, unit = int(m.group(1)), m.group(2)
    return {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]


def load(folder: Path, since: timedelta) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - since
    records = []
    for path in sorted(folder.glob("*.jsonl")):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    if datetime.fromisoformat(r["timestamp"]) >= cutoff:
                        records.append(r)
                except (ValueError, KeyError):
                    continue
    return records


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(1, math.ceil(p / 100 * len(ordered))) - 1], 4)


def summarise(records: list[dict]) -> dict:
    n = len(records)
    top1 = [r["retrieval"]["chunks"][0]["score"] for r in records
            if (r.get("retrieval") or {}).get("chunks")]
    hist, low = {}, 0.0
    for edge in BUCKETS:
        label = f"{low:.2f}-{min(edge, 1.0):.2f}"
        hist[label] = sum(1 for s in top1 if low <= s < edge)
        low = edge
    hist = {"<0.50": sum(1 for s in top1 if s < BUCKETS[0]), **{k: v for k, v in list(hist.items())[1:]}}
    stages: dict[str, list[float]] = {}
    for r in records:
        for stage, ms in (r.get("latency_ms") or {}).items():
            stages.setdefault(stage, []).append(ms)
    flagged = Counter(g["rail"] for r in records for g in r.get("guardrails", [])
                      if g.get("action") in ("flagged", "excluded_from_prompt"))
    answered = [r for r in records if (r.get("response") or {}).get("answered_from_context")]
    cache_hits = sum(1 for r in records if (r.get("cache") or {}).get("hit"))
    fallbacks = sum(1 for r in records if (r.get("response") or {}).get("fallback"))
    return {
        "queries": n,
        "top1_similarity": {"count": len(top1), "min": pct(top1, 0.0001), "p10": pct(top1, 10),
                            "p50": pct(top1, 50), "p90": pct(top1, 90), "max": pct(top1, 100),
                            "histogram": hist},
        "abstention_rate": round(1 - len(answered) / n, 4) if n else None,
        "cache_hit_rate": round(cache_hits / n, 4) if n else None,
        "fallback_rate": round(fallbacks / n, 4) if n else None,
        "latency_ms": {s: {"p50": pct(v, 50), "p95": pct(v, 95)} for s, v in sorted(stages.items())},
        "injection_attempts_flagged": dict(flagged),
        "collections": dict(Counter((r.get("collection") or {}).get("name") for r in records)),
    }


def show(s: dict, window: str) -> str:
    t = s["top1_similarity"]
    lines = [f"Trace summary, last {window}: {s['queries']} queries", "",
             f"top-1 similarity  min {t['min']}  p10 {t['p10']}  p50 {t['p50']}  p90 {t['p90']}  max {t['max']}"]
    lines += [f"  {k:>10}  {'#' * v} {v}" for k, v in t["histogram"].items()]
    lines += ["", f"abstention rate   {s['abstention_rate']}",
              f"cache hit rate    {s['cache_hit_rate']}",
              f"fallback rate     {s['fallback_rate']}",
              f"injections flagged {s['injection_attempts_flagged'] or 0}",
              f"collections       {s['collections']}", "", "latency per stage (ms)   p50      p95"]
    lines += [f"  {stage:<20} {v['p50']!s:>8} {v['p95']!s:>8}" for stage, v in s["latency_ms"].items()]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="monitoring summary over recent traces")
    parser.add_argument("--since", default="1h", help="time window, e.g. 30m, 1h, 7d")
    parser.add_argument("--dir", type=Path, default=default_dir())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    records = load(args.dir, parse_since(args.since))
    if not records:
        print(f"no traces in the last {args.since} under {args.dir}", file=sys.stderr)
        return 1
    s = summarise(records)
    print(json.dumps(s, indent=2) if args.json else show(s, args.since))
    return 0


if __name__ == "__main__":
    sys.exit(main())
