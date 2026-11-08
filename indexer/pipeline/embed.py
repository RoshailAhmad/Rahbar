"""Stage 4: Embed. One vector per chunk, from the pinned model only."""

from __future__ import annotations

import json
import time

import httpx

from .config import IndexerSettings

BATCH = 32


def embed(texts: list[str], settings: IndexerSettings) -> list[list[float]]:
    """Embed with settings.embed_model (the EMBED_MODEL pin) and nothing else.

    POST {ollama_url}/api/embed {"model": ..., "input": [...]} -> {"embeddings": [...]},
    in batches, because one request per chunk is slow.
    """
    vectors: list[list[float]] = []
    with httpx.Client(timeout=300) as client:
        for start in range(0, len(texts), BATCH):
            batch = texts[start:start + BATCH]
            response = client.post(f"{settings.ollama_url}/api/embed",
                                   json={"model": settings.embed_model, "input": batch})
            response.raise_for_status()
            got = response.json()["embeddings"]
            if len(got) != len(batch):
                raise RuntimeError(f"asked for {len(batch)} embeddings, got {len(got)}")
            vectors.extend(got)
            print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                              "logger": "rahbar.indexer.embed", "msg": "embedded",
                              "done": len(vectors), "total": len(texts)}), flush=True)
    return vectors
