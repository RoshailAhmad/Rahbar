"""Stage 5: Store. The only code in the whole system that writes to Chroma."""

from __future__ import annotations

import time
from typing import Any

from .config import IndexerSettings
from .models import Chunk

BATCH = 500


def get_client(settings: IndexerSettings) -> Any:
    import chromadb  # the thin client, from chromadb-client in requirements.txt
    from chromadb.config import Settings as ChromaSettings

    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port,
                               settings=ChromaSettings(anonymized_telemetry=False))


def store(chunks: list[Chunk], vectors: list[list[float]], settings: IndexerSettings,
          client: Any = None) -> int:
    """Rebuild the collection with every chunk, its vector and metadata.

    The collection metadata records the embedding model and vector dimension (the pin
    the api checks in /readyz, section 4.4) and an index_version timestamp that the
    api's cache keys include, so a re-index invalidates every cached answer.
    The old collection is dropped first: for a few seconds the api's readiness reports
    an empty index and pods leave the Service, which is acceptable at this scale.
    """
    if not chunks or len(chunks) != len(vectors):
        raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
    client = client or get_client(settings)
    try:
        client.delete_collection(settings.collection)
    except Exception:  # the collection did not exist yet
        pass
    collection = client.create_collection(
        name=settings.collection,
        metadata={
            "hnsw:space": "cosine",
            "embed_model": settings.embed_model,
            "dimension": len(vectors[0]),
            "index_version": time.strftime("%Y%m%d%H%M%S", time.gmtime()),
        },
    )
    for start in range(0, len(chunks), BATCH):
        part = chunks[start:start + BATCH]
        collection.add(
            ids=[c.id for c in part],
            documents=[c.text for c in part],
            embeddings=vectors[start:start + BATCH],
            metadatas=[c.metadata() for c in part],
        )
    return int(collection.count())
