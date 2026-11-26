"""Laptop wrapper for the monitoring summary (Part D3):

    kubectl cp rahbar/data-shell:/data/traces ./traces
    python scripts/trace_summary.py --since 24h --dir traces
"""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[1] / "api" / "app" / "trace_summary.py"), run_name="__main__")
