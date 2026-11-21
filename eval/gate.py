"""Release gate (Assignment 03, Part C2): pass or fail a candidate against the baseline.

    python eval/gate.py --baseline eval/results/<base>.json --candidate eval/results/<cand>.json
    python eval/gate.py ... --config /config/gate.yaml --out /data/results/gate-<label>.json

Reads the thresholds from eval/gate.yaml (on the cluster: ConfigMap gate-config, mounted
as a file). Prints one row per rule and exits 0 when every rule passes, 1 when any fails.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def metric(result: dict, name: str) -> float | None:
    """Read one metric from a suite result file (eval/suite.py)."""
    e2e = result.get("end_to_end") or {}
    component = result.get("component") or {}
    if name == "recall@5":
        if component.get("recall@5") is not None:
            return float(component["recall@5"])
        # until Mehak's component level lands: mean per-question recall@5 from end_to_end
        per_q = [q["recall@5"] for q in result.get("per_question", []) if q.get("recall@5") is not None]
        return _mean(per_q)
    if name == "p95":
        return e2e.get("latency_p95_s")
    return e2e.get(name)


def check(baseline: dict, candidate: dict, cfg: dict) -> list[dict]:
    """One dict per rule: name, rule text, baseline value, candidate value, status."""
    rows: list[dict] = []
    missing = cfg.get("on_missing_metric", "skip")

    def add(name: str, rule: str, base: float | None, cand: float | None, ok: bool | None) -> None:
        if ok is None:
            status = "FAIL" if missing == "fail" else "SKIP"
        else:
            status = "PASS" if ok else "FAIL"
        rows.append({"metric": name, "rule": rule, "baseline": base, "candidate": cand, "status": status})

    b, c = metric(baseline, "recall@5"), metric(candidate, "recall@5")
    drop = float(cfg["max_recall5_drop"])
    add("recall@5", f">= baseline - {drop}", b, c,
        None if b is None or c is None else c >= b - drop - 1e-9)

    c = metric(candidate, "faithfulness")
    floor = float(cfg["min_faithfulness"])
    add("faithfulness", f">= {floor}", metric(baseline, "faithfulness"), c,
        None if c is None else c >= floor)

    c = metric(candidate, "p95")
    ceiling = float(cfg["max_p95_seconds"])
    add("latency p95 (s)", f"<= {ceiling}", metric(baseline, "p95"), c,
        None if c is None else c <= ceiling)

    c = metric(candidate, "citation_validity")
    floor = float(cfg["min_citation_validity"])
    add("citation_validity", f">= {floor}", metric(baseline, "citation_validity"), c,
        None if c is None else c >= floor)

    b, c = metric(baseline, "abstention_correctness"), metric(candidate, "abstention_correctness")
    add("abstention_correctness", ">= baseline", b, c,
        None if b is None or c is None else c >= b - 1e-9)
    return rows


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"


def main() -> int:
    parser = argparse.ArgumentParser(description="RAHBAR release gate")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path(os.environ.get("GATE_CONFIG", HERE / "gate.yaml")))
    parser.add_argument("--out", type=Path, help="also write the decision as JSON")
    args = parser.parse_args()

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    rows = check(baseline, candidate, cfg)
    passed = all(r["status"] != "FAIL" for r in rows)

    print(f"release gate  config={args.config}")
    print(f"  baseline : {args.baseline.name}\n  candidate: {args.candidate.name}\n")
    print(f"  {'metric':<24}{'rule':<22}{'baseline':>10}{'candidate':>11}  status")
    for r in rows:
        print(f"  {r['metric']:<24}{r['rule']:<22}{_fmt(r['baseline']):>10}{_fmt(r['candidate']):>11}  {r['status']}")
    print(f"\nGATE {'PASSED: release' if passed else 'FAILED: do not release'}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"passed": passed, "config": cfg, "rules": rows,
                                        "baseline": str(args.baseline), "candidate": str(args.candidate)},
                                       indent=2), encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
