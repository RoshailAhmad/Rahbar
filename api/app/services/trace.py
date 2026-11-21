"""Trace records (Assignment 03, Part D1/D4; RAGOps paper 3.2.3, 5.1, Table 2).

Every query writes ONE JSON line: what was asked, which index and embedding model answered,
which chunks (with document ids, versions and scores) were retrieved under which filter,
the exact prompt (and its hash), the model and its parameters, the response and citations,
every guardrail action, the latency of each stage, and whether the cache was hit.

The line goes to stdout (so `kubectl logs` shows it) and is appended to
TRACE_DIR/traces-YYYYMMDD.jsonl on the data-lake PVC (so the report scripts can read it).
Writing a trace never breaks an answer: a failed file write is logged and ignored.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("rahbar.trace")

# Retrieval rail (paper 3.2.3): text that tries to give the model instructions.
_INJECTION = re.compile(
    r"(ignore|disregard|forget|override)\s+(all\s+|any\s+|the\s+|your\s+)?(previous|prior|above|earlier)?\s*"
    r"(instructions|rules|prompts?|directions)"
    r"|you are now\b|act as (an?|the)\b|system prompt|reveal (your|the) (prompt|instructions)",
    re.IGNORECASE,
)


def injection_pattern(text: str) -> str | None:
    match = _INJECTION.search(text or "")
    return match.group(0) if match else None


def trace_dir() -> Path | None:
    explicit = os.environ.get("TRACE_DIR")
    if explicit:
        return Path(explicit)
    data = os.environ.get("DATA_DIR")
    return Path(data) / "traces" if data else None


class Trace:
    def __init__(self, trace_id: str, query: str) -> None:
        self.started = time.perf_counter()
        self.record: dict[str, Any] = {
            "trace_id": trace_id,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "query": query,
            "rewritten_query": None,       # RAHBAR does not rewrite queries
            "guardrails": [],
            "latency_ms": {},
            "cache": {"hit": False},
        }

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            ms = (time.perf_counter() - start) * 1000
            self.record["latency_ms"][name] = round(self.record["latency_ms"].get(name, 0.0) + ms, 1)

    def guardrail(self, rail: str, action: str, **details: Any) -> None:
        self.record["guardrails"].append({"rail": rail, "action": action, **details})

    def set(self, **fields: Any) -> None:
        self.record.update(fields)

    def prompt(self, messages: list[dict[str, str]]) -> None:
        blob = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        self.record["prompt"] = {"sha256": hashlib.sha256(blob.encode("utf-8")).hexdigest(),
                                 "messages": messages}

    def finish(self) -> dict[str, Any]:
        self.record["latency_ms"]["total"] = round((time.perf_counter() - self.started) * 1000, 1)
        line = json.dumps(self.record, ensure_ascii=False, default=str)
        sys.stdout.write(line + "\n")      # one JSON line on stdout: kubectl logs
        sys.stdout.flush()
        folder = trace_dir()
        if folder is not None:
            try:
                folder.mkdir(parents=True, exist_ok=True)
                name = f"traces-{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
                with open(folder / name, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError as exc:
                log.warning("trace file write failed", extra={"error": str(exc)})
        return self.record
