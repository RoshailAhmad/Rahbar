"""Incremental update of the retrieval sources (Assignment 03, Part A2; paper 4.2.3-4.2.4).

Instead of dropping and rebuilding the collection, the index is synced with the data lake:

  unchanged document (same content_hash)   -> 0 chunks embedded
  superseded flag changed (archive/restore) -> chunk metadata updated, 0 chunks embedded
  new document                              -> chunked, embedded, added
  changed document (same doc_id, new hash)  -> its old chunks deleted, new ones added
  document no longer in the lake            -> all its chunks deleted (no orphans)

Every chunk carries doc_id and content_hash, so all of this is decided per document. When
anything changes, the collection's index_version is bumped, which invalidates the api's
semantic cache. The embedding model and dimension (the A2 pin) are kept in the metadata.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import Chunk

BATCH = 500


@dataclass
class LakeDoc:
    doc_id: str
    path: str
    sha256: str
    doc_version: str
    superseded: bool


def existing_by_doc(collection: Any) -> dict[str, dict]:
    """doc_id -> {"hash": content_hash, "superseded": bool, "ids": [...], "metas": [...]}"""
    data = collection.get(include=["metadatas"])
    found: dict[str, dict] = {}
    for chunk_id, meta in zip(data["ids"], data["metadatas"]):
        doc_id = (meta or {}).get("doc_id") or "unknown"
        entry = found.setdefault(doc_id, {"hash": meta.get("content_hash"), "superseded": meta.get("superseded"),
                                          "ids": [], "metas": []})
        entry["ids"].append(chunk_id)
        entry["metas"].append(meta)
    return found


def counts_by_doc(collection: Any) -> dict[str, int]:
    return {doc_id: len(e["ids"]) for doc_id, e in sorted(existing_by_doc(collection).items())}


def sync(collection: Any, docs: list[LakeDoc], make_chunks: Callable[[LakeDoc], list[Chunk]],
         embed: Callable[[list[str]], list[list[float]]], embed_model: str) -> dict[str, Any]:
    existing = existing_by_doc(collection)
    stats = {"unchanged": 0, "metadata_updated": 0, "added": 0, "replaced": 0, "deleted": 0,
             "chunks_embedded": 0, "chunks_deleted": 0}
    dimension = (collection.metadata or {}).get("dimension")
    written: set[str] = set()  # ids rewritten in this run, never deleted as orphans below

    for doc in docs:
        old = existing.get(doc.doc_id)
        if old and old["hash"] == doc.sha256:
            if bool(old["superseded"]) != doc.superseded:
                metas = [{**m, "superseded": doc.superseded} for m in old["metas"]]
                collection.update(ids=old["ids"], metadatas=metas)
                stats["metadata_updated"] += 1
            else:
                stats["unchanged"] += 1
            continue
        chunks = make_chunks(doc)
        if not chunks:
            continue
        vectors = embed([c.text for c in chunks])
        dimension = len(vectors[0])
        if old:
            collection.delete(where={"doc_id": doc.doc_id})
            stats["chunks_deleted"] += len(old["ids"])
            stats["replaced"] += 1
        else:
            stats["added"] += 1
        for start in range(0, len(chunks), BATCH):
            part = chunks[start:start + BATCH]
            collection.upsert(
                ids=[c.id for c in part],
                documents=[c.text for c in part],
                embeddings=vectors[start:start + BATCH],
                metadatas=[{**c.metadata(), "doc_id": doc.doc_id, "content_hash": doc.sha256,
                            "superseded": doc.superseded} for c in part],
            )
            written.update(c.id for c in part)
        stats["chunks_embedded"] += len(chunks)

    wanted = {d.doc_id for d in docs}
    for doc_id, old in existing.items():
        if doc_id not in wanted:  # deleted from the lake: remove every chunk, leave no orphans
            # An id an older index shares with a chunk just written was overwritten by the
            # upsert above; deleting it would drop the new chunk (found migrating from A2).
            stale = [i for i in old["ids"] if i not in written]
            if stale:
                collection.delete(ids=stale)
            stats["deleted"] += 1
            stats["chunks_deleted"] += len(stale)

    changed = any(stats[k] for k in ("metadata_updated", "added", "replaced", "deleted"))
    if changed:
        collection.modify(metadata={"embed_model": embed_model, "dimension": dimension,
                                    "index_version": time.strftime("%Y%m%d%H%M%S", time.gmtime())})
    stats["index_version_bumped"] = changed
    stats["total_chunks"] = int(collection.count())
    return stats


def open_collection(client: Any, name: str, embed_model: str) -> Any:
    """The existing collection, or a new cosine one carrying the embedding pin."""
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine", "embed_model": embed_model, "dimension": 0,
                  "index_version": time.strftime("%Y%m%d%H%M%S", time.gmtime())},
    )
