"""The real retriever (sections 3.2 and 4.4). Reads the index; never writes it."""

from __future__ import annotations

import re
import time
from functools import lru_cache
from typing import Any

import httpx

from ..config import Settings
from ..schemas import Passage

# A question that explicitly asks about an older version may see superseded documents.
_OLDER_VERSION = re.compile(
    r"\b(20(1\d|2[0-5])|old(er)?|previous|earlier|former|superseded|before (the )?20\d\d)\b",
    re.IGNORECASE,
)


def wants_older_version(question: str) -> bool:
    return bool(_OLDER_VERSION.search(question))


class ChromaRetriever:
    name = "chroma"

    def __init__(self, settings: Settings) -> None:
        import chromadb  # the thin client, from chromadb-client in requirements.txt
        from chromadb.config import Settings as ChromaSettings

        self.settings = settings
        self.client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port,
                                          settings=ChromaSettings(anonymized_telemetry=False))
        self._http = httpx.Client(timeout=30)
        self._version: tuple[float, str] = (0.0, "")
        # Same question twice in one request (cache check, then retrieval): embed once.
        self.embed_query = lru_cache(maxsize=256)(self._embed)  # type: ignore[method-assign]

    def _embed(self, text: str) -> tuple[float, ...]:
        """Embed with settings.embed_model, the same pinned model the indexer used."""
        response = self._http.post(f"{self.settings.ollama_url}/api/embed",
                                   json={"model": self.settings.embed_model, "input": [text]})
        response.raise_for_status()
        return tuple(response.json()["embeddings"][0])

    def _collection(self) -> Any:
        return self.client.get_collection(self.settings.collection)

    def index_version(self) -> str:
        """The index_version the indexer wrote; re-read at most every 30 s.
        The cache keys include it, so a re-index invalidates every cached answer."""
        checked, version = self._version
        if time.monotonic() - checked > 30:
            metadata = self._collection().metadata or {}
            version = str(metadata.get("index_version", "unknown"))
            self._version = (time.monotonic(), version)
        return version

    def retrieve(self, question: str, k: int) -> list[Passage]:
        vector = list(self.embed_query(question))
        # Exclude superseded documents unless the user explicitly asks about an older one.
        where = None if wants_older_version(question) else {"superseded": False}
        result = self._collection().query(
            query_embeddings=[vector], n_results=k, where=where,
            include=["documents", "metadatas", "distances"],
        )
        passages = []
        for chunk_id, text, meta, distance in zip(
            result["ids"][0], result["documents"][0], result["metadatas"][0],
            result["distances"][0],
        ):
            passages.append(Passage(
                chunk_id=chunk_id, text=text or "", source=str(meta.get("source", "")),
                section=str(meta.get("section", "")),
                page=int(meta["page"]) if meta.get("page") is not None else None,
                score=1.0 - float(distance),   # Chroma returns cosine distance
            ))
        return passages
