"""Entry point of the evaluation Job (Assignment 03, Part F2): suite, then release gate.

Environment (from k8s/eval-job.yaml):
  EVAL_API      the api to evaluate, e.g. http://api:8000 or http://api-candidate:8000
  EVAL_LABEL    label in the result file name, e.g. baseline, candidate-c250
  RESULTS_DIR   where result files go (the data-lake PVC: /data/results)
  BASELINE      the baseline result file (default RESULTS_DIR/baseline.json)
  GATE_CONFIG   the gate thresholds (ConfigMap gate-config mounted at /config/gate.yaml)

Exit code: the gate's (0 pass, 1 fail). With no baseline yet, this run becomes the baseline.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    api = os.environ.get("EVAL_API", "http://api:8000")
    label = os.environ.get("EVAL_LABEL", "job")
    results = Path(os.environ.get("RESULTS_DIR", "/data/results"))
    baseline = Path(os.environ.get("BASELINE", results / "baseline.json"))
    gate_config = os.environ.get("GATE_CONFIG", str(HERE / "gate.yaml"))
    results.mkdir(parents=True, exist_ok=True)

    cmd = [sys.executable, str(HERE / "suite.py"), "--api", api, "--label", label, "--out-dir", str(results)]
    if os.environ.get("EVAL_GOLDEN"):
        cmd += ["--golden", os.environ["EVAL_GOLDEN"]]
    if os.environ.get("EVAL_NO_JUDGE") == "1":
        cmd.append("--no-judge")
    print("running:", " ".join(cmd), flush=True)
    code = subprocess.call(cmd)
    if code != 0:
        print(f"suite failed with exit code {code}", flush=True)
        return code

    newest = max(results.glob(f"*-{label}.json"), key=lambda p: p.stat().st_mtime)
    if not baseline.exists():
        shutil.copyfile(newest, baseline)
        print(f"no baseline yet: {newest.name} is now the baseline ({baseline})", flush=True)
        return 0

    gate_out = results / f"gate-{newest.stem}.json"
    cmd = [sys.executable, str(HERE / "gate.py"), "--baseline", str(baseline), "--candidate", str(newest),
           "--config", gate_config, "--out", str(gate_out)]
    print("running:", " ".join(cmd), flush=True)
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
