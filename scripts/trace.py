"""Laptop wrapper for the trace tool (Part D2):

    kubectl cp rahbar/data-shell:/data/traces ./traces
    python scripts/trace.py <trace_id> --dir traces
"""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[1] / "api" / "app" / "trace_tool.py"), run_name="__main__")
