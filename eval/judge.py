"""Faithfulness judge (Assignment 03, Part B, end-to-end level).

An LLM (qwen2.5 via Ollama, temperature 0, fixed seed) reads the retrieved context and the
answer and says whether every factual claim in the answer is supported by that context.
faithfulness = supported answers / judged answers. Abstentions and errors are not judged.

Hand labels: eval/hand_labels.jsonl, one line per labelled answer:
    {"id": "q01", "supported": true, "labeller": "roshail"}
The suite reports how often the judge agrees with them.

    python eval/judge.py --export eval/results/<run>.json   # writes eval/to_label.md for hand labelling
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "supported": {"type": "boolean"},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["supported", "unsupported_claims"],
}

PROMPT = """You check answers for faithfulness. Use ONLY the CONTEXT below.
An answer is supported when every factual claim in it (numbers, rules, conditions, names)
is stated in or directly follows from the CONTEXT. Wording may differ. Background knowledge
does not count. If any claim is missing from or contradicts the CONTEXT, it is not supported.

CONTEXT:
{context}

QUESTION: {question}

ANSWER: {answer}

Reply with JSON: {{"supported": true|false, "unsupported_claims": [...]}}"""


def _context(row: dict, max_passages: int) -> str:
    parts = []
    for i, ref in enumerate(row.get("retrieved", [])[:max_passages], start=1):
        parts.append(f"[{i}] {ref.get('source')} / {ref.get('section')}\n{ref.get('text') or ''}")
    return "\n\n".join(parts)


def judge_one(client: httpx.Client, ollama: str, model: str, seed: int, row: dict, max_passages: int) -> dict:
    content = PROMPT.format(context=_context(row, max_passages), question=row["question"], answer=row["answer"])
    response = client.post(f"{ollama}/api/chat", json={
        "model": model, "stream": False, "format": VERDICT_SCHEMA,
        "messages": [{"role": "user", "content": content}],
        "options": {"temperature": 0, "seed": seed, "num_ctx": 4096},
    })
    response.raise_for_status()
    return json.loads(response.json()["message"]["content"])


def load_hand_labels(path: Path) -> dict[str, bool]:
    if not path.exists():
        return {}
    labels = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            labels[item["id"]] = bool(item["supported"])
    return labels


def judge_rows(rows: list[dict], seed: int, ollama: str | None = None, model: str | None = None,
               labels_path: Path = HERE / "hand_labels.jsonl", max_passages: int = 3) -> dict:
    """Adds row['judge'] to every answered row and returns the faithfulness metrics."""
    ollama = (ollama or os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
    model = model or os.environ.get("JUDGE_MODEL", os.environ.get("LLM_MODEL", "qwen2.5:1.5b"))
    judged = supported = 0
    with httpx.Client(timeout=300.0) as client:
        for row in rows:
            if not row.get("answered_from_context") or row.get("error") or not row.get("answer"):
                continue
            try:
                verdict = judge_one(client, ollama, model, seed, row, max_passages)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                row["judge"] = {"error": f"{type(exc).__name__}: {exc}"}
                continue
            row["judge"] = verdict
            judged += 1
            supported += int(bool(verdict.get("supported")))
            print(f"  judge {row['id']:<6} {'SUPPORTED' if verdict.get('supported') else 'NOT SUPPORTED'}")

    labels = load_hand_labels(labels_path)
    both = [r for r in rows if r["id"] in labels and "supported" in (r.get("judge") or {})]
    agree = sum(1 for r in both if bool(r["judge"]["supported"]) == labels[r["id"]])
    return {
        "faithfulness": round(supported / judged, 4) if judged else None,
        "judged_answers": judged,
        "judge_model": model,
        "hand_labelled": len(both),
        "judge_agreement": round(agree / len(both), 4) if both else None,
    }


def export_for_labelling(result_path: Path, out: Path) -> None:
    rows = json.loads(result_path.read_text(encoding="utf-8"))["per_question"]
    lines = ["# Hand-label these answers (supported = every claim is in the context)", ""]
    for row in rows:
        if not row.get("answered_from_context"):
            continue
        lines += [f"## {row['id']}: {row['question']}", "", f"**Answer:** {row['answer']}", "",
                  f"**Judge said:** {(row.get('judge') or {}).get('supported')}", "", "**Context:**", "",
                  _context(row, 3), "", "---", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"written {out}: label at least 8 answers into eval/hand_labels.jsonl")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="faithfulness judge helpers")
    parser.add_argument("--export", type=Path, required=True, help="a suite result file")
    parser.add_argument("--out", type=Path, default=HERE / "to_label.md")
    args = parser.parse_args()
    export_for_labelling(args.export, args.out)
    sys.exit(0)
