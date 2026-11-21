"""Trace tool (Assignment 03, Part D2): rebuild the exact context and prompt of one answer.

    python -m app.trace_tool <trace_id>                      # inside the api pod (reads /data/traces)
    kubectl exec -n rahbar deploy/api -- python -m app.trace_tool <trace_id>
    python scripts/trace.py <trace_id> --dir traces/         # on a laptop, from copied trace files

Standard library only, so it runs anywhere the trace files are.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def default_dir() -> Path:
    if os.environ.get("TRACE_DIR"):
        return Path(os.environ["TRACE_DIR"])
    return Path(os.environ.get("DATA_DIR", "/data")) / "traces"


def find(trace_id: str, folder: Path) -> dict | None:
    for path in sorted(folder.glob("*.jsonl"), reverse=True):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if trace_id in line:
                    record = json.loads(line)
                    if record.get("trace_id") == trace_id:
                        return record
    return None


def show(r: dict) -> str:
    out = [f"TRACE {r['trace_id']}   {r['timestamp']}",
           f"query           : {r['query']}",
           f"rewritten query : {r.get('rewritten_query')}",
           f"cache           : {r.get('cache')}"]
    emb, col, model = r.get("embedding", {}), r.get("collection", {}), r.get("model", {})
    out += [f"embedding       : {emb.get('model')} (dimension {emb.get('dimension')})",
            f"collection      : {col.get('name')}  index_version={col.get('index_version')}",
            f"model           : {model.get('provider')} {model.get('name')}  "
            f"temperature={model.get('temperature')} seed={model.get('seed')} num_ctx={model.get('num_ctx')}"]
    ret = r.get("retrieval", {})
    if ret:
        out += ["", f"RETRIEVAL  top_k={ret.get('top_k')}  filter={ret.get('filter')}  "
                    f"relevance_floor={ret.get('relevance_floor')}  reranker={ret.get('reranker')}"]
        sent = set(ret.get("evidence_ids", []))
        for c in ret.get("chunks", []):
            mark = "-> prompt" if c["chunk_id"] in sent else ""
            out.append(f"  {c['score']:.4f}  {c['doc_id']} v{c.get('doc_version')}  p{c.get('page')}  "
                       f"[{c.get('section')}]  {c['chunk_id']}  {mark}")
    if r.get("guardrails"):
        out += ["", "GUARDRAILS"] + [f"  {g}" for g in r["guardrails"]]
    prompt = r.get("prompt")
    if prompt:
        out += ["", f"PROMPT  sha256={prompt['sha256']}"]
        for m in prompt["messages"]:
            out += [f"----- {m['role']} -----", m["content"]]
    resp = r.get("response", {})
    out += ["", "RESPONSE", f"  answered_from_context={resp.get('answered_from_context')}  "
            f"confidence={resp.get('confidence')}  fallback={resp.get('fallback')}",
            f"  {resp.get('answer')}", f"  citations: {resp.get('citations')}",
            "", f"LATENCY (ms): {r.get('latency_ms')}"]
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="print the context and prompt behind one answer")
    parser.add_argument("trace_id")
    parser.add_argument("--dir", type=Path, default=default_dir())
    parser.add_argument("--json", action="store_true", help="print the raw record")
    args = parser.parse_args()
    record = find(args.trace_id, args.dir)
    if record is None:
        print(f"trace {args.trace_id} not found in {args.dir}", file=sys.stderr)
        return 1
    print(json.dumps(record, indent=2, ensure_ascii=False) if args.json else show(record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
