"""Module level (Assignment 03, Part B): embedding quality of the pinned EMBED_MODEL.

  - mean cosine of 15+ paraphrase pairs vs 15+ unrelated pairs, and the gap between them
  - embedding time per chunk (a batch of real-sized chunks, timed)
  - determinism: embed the same texts twice and report the largest absolute difference

Pairs live in eval/module_pairs.jsonl. Embeddings come from Ollama /api/embed (OLLAMA_URL,
EMBED_MODEL), or from an `embed` function passed in (the tests pass a fake one).

    python eval/levels/module.py          # prints the metrics as JSON
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parents[1]
PAIRS = HERE / "module_pairs.jsonl"
Embedder = Callable[[list[str]], list[list[float]]]

# realistic chunk-sized text for the timing test (about 400 words, like a stored chunk)
SAMPLE_CHUNK = ("Students are required to maintain full attendance in lectures, labs and tutorials. "
                "Absence of up to a fifth of the classes may be condoned for genuine reasons. ") * 25


def ollama_embedder(ollama: str | None = None, model: str | None = None) -> Embedder:
    url = (ollama or os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
    name = model or os.environ.get("EMBED_MODEL", "nomic-embed-text")

    def embed(texts: list[str]) -> list[list[float]]:
        with httpx.Client(timeout=300.0) as client:
            response = client.post(f"{url}/api/embed", json={"model": name, "input": texts})
            response.raise_for_status()
            return response.json()["embeddings"]

    return embed


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def load_pairs(path: Path = PAIRS) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def measure(embed: Embedder, pairs: list[dict], timing_chunks: int = 10) -> dict:
    texts = sorted({p["a"] for p in pairs} | {p["b"] for p in pairs})
    first = dict(zip(texts, embed(texts)))
    second = dict(zip(texts, embed(texts)))  # determinism: the same texts again
    max_diff = max(abs(x - y) for t in texts for x, y in zip(first[t], second[t]))

    sims: dict[str, list[float]] = {"paraphrase": [], "unrelated": []}
    for p in pairs:
        sims[p["kind"]].append(cosine(first[p["a"]], first[p["b"]]))
    para = sum(sims["paraphrase"]) / len(sims["paraphrase"])
    unrel = sum(sims["unrelated"]) / len(sims["unrelated"])

    chunks = [f"{i}. {SAMPLE_CHUNK}" for i in range(timing_chunks)]
    started = time.perf_counter()
    embed(chunks)
    per_chunk_ms = (time.perf_counter() - started) * 1000 / timing_chunks

    return {
        "embed_model": os.environ.get("EMBED_MODEL", "nomic-embed-text"),
        "dimension": len(next(iter(first.values()))),
        "paraphrase_pairs": len(sims["paraphrase"]),
        "unrelated_pairs": len(sims["unrelated"]),
        "mean_cosine_paraphrase": round(para, 4),
        "mean_cosine_unrelated": round(unrel, 4),
        "cosine_gap": round(para - unrel, 4),
        "min_cosine_paraphrase": round(min(sims["paraphrase"]), 4),
        "max_cosine_unrelated": round(max(sims["unrelated"]), 4),
        "embed_ms_per_chunk": round(per_chunk_ms, 1),
        "determinism_max_abs_diff": max_diff,
    }


def run(ollama: str | None = None, embed: Embedder | None = None, **_: object) -> dict:
    """Called by eval/suite.py."""
    return measure(embed or ollama_embedder(ollama), load_pairs())


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
    sys.exit(0)
