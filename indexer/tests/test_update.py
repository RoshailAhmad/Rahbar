"""Part A2 incremental update, with an in-memory collection and a fake embedder.

Shows the four required behaviours: an unchanged corpus embeds 0 chunks; a changed document
replaces only its own chunks; a deleted document leaves no orphans (count by doc_id); a
superseded version is excluded through metadata and can be restored.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.ingest import apply_requests, load_registry, save_registry
from pipeline.models import Chunk
from pipeline.update import LakeDoc, counts_by_doc, sync


class FakeCollection:
    """The handful of Chroma calls update.py uses, in memory."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.metadata = {"embed_model": "fake", "dimension": 0, "index_version": "0"}
        self.embedded = 0

    def get(self, include=None):
        ids = list(self.rows)
        return {"ids": ids, "metadatas": [self.rows[i]["meta"] for i in ids]}

    def add(self, ids, documents, embeddings, metadatas):
        # Like Chroma: add() silently skips ids that already exist.
        for i, d, e, m in zip(ids, documents, embeddings, metadatas):
            self.rows.setdefault(i, {"doc": d, "vec": e, "meta": m})

    def upsert(self, ids, documents, embeddings, metadatas):
        for i, d, e, m in zip(ids, documents, embeddings, metadatas):
            self.rows[i] = {"doc": d, "vec": e, "meta": m}

    def update(self, ids, metadatas):
        for i, m in zip(ids, metadatas):
            self.rows[i]["meta"] = m

    def delete(self, ids=None, where=None):
        if where:
            ids = [i for i, r in self.rows.items() if all(r["meta"].get(k) == v for k, v in where.items())]
        for i in ids or []:
            self.rows.pop(i, None)

    def modify(self, metadata):
        self.metadata = metadata

    def count(self):
        return len(self.rows)


TEXTS = {"rules": "attendance warning summer", "fees": "tuition refund deposit", "guide": "societies events"}


def make_chunks(doc: LakeDoc) -> list[Chunk]:
    words = Path(doc.path).read_text(encoding="utf-8").split()
    return [Chunk(id=f"{doc.doc_id}:{n}", text=w, source=Path(doc.path).name, section="S", page=1,
                  doc_version=doc.doc_version, superseded=doc.superseded) for n, w in enumerate(words)]


def make_embed(coll: FakeCollection):
    def embed(texts):
        coll.embedded += len(texts)
        return [[float(len(t)), 1.0] for t in texts]
    return embed


def docs_from(tmp: Path, texts: dict[str, str], superseded: set[str] | None = None) -> list[LakeDoc]:
    out = []
    for doc_id, text in texts.items():
        path = tmp / f"{doc_id}.md"
        path.write_text(text, encoding="utf-8")
        out.append(LakeDoc(doc_id=doc_id, path=str(path), sha256=str(hash(text)), doc_version="1",
                           superseded=doc_id in (superseded or set())))
    return out


def test_unchanged_corpus_embeds_zero_chunks(tmp_path: Path) -> None:
    coll = FakeCollection()
    first = sync(coll, docs_from(tmp_path, TEXTS), make_chunks, make_embed(coll), "fake")
    assert first["chunks_embedded"] == 8 and first["added"] == 3
    version = coll.metadata["index_version"]
    again = sync(coll, docs_from(tmp_path, TEXTS), make_chunks, make_embed(coll), "fake")
    assert again["chunks_embedded"] == 0 and again["unchanged"] == 3
    assert coll.metadata["index_version"] == version  # nothing changed: the cache stays valid


def test_changed_document_replaces_only_its_own_chunks(tmp_path: Path) -> None:
    coll = FakeCollection()
    sync(coll, docs_from(tmp_path, TEXTS), make_chunks, make_embed(coll), "fake")
    before = {i: r for i, r in coll.rows.items() if r["meta"]["doc_id"] != "fees"}
    changed = {**TEXTS, "fees": "tuition refund deposit transfer fine"}
    stats = sync(coll, docs_from(tmp_path, changed), make_chunks, make_embed(coll), "fake")
    assert stats["replaced"] == 1 and stats["chunks_embedded"] == 5 and stats["unchanged"] == 2
    assert {i: r for i, r in coll.rows.items() if r["meta"]["doc_id"] != "fees"} == before
    assert counts_by_doc(coll)["fees"] == 5


def test_deleted_document_leaves_no_orphan_chunks(tmp_path: Path) -> None:
    coll = FakeCollection()
    sync(coll, docs_from(tmp_path, TEXTS), make_chunks, make_embed(coll), "fake")
    remaining = {k: v for k, v in TEXTS.items() if k != "guide"}
    stats = sync(coll, docs_from(tmp_path, remaining), make_chunks, make_embed(coll), "fake")
    assert stats["deleted"] == 1 and stats["chunks_embedded"] == 0
    assert "guide" not in counts_by_doc(coll)
    assert all(r["meta"]["doc_id"] != "guide" for r in coll.rows.values())


def test_superseded_is_metadata_only_and_restorable(tmp_path: Path) -> None:
    coll = FakeCollection()
    sync(coll, docs_from(tmp_path, TEXTS), make_chunks, make_embed(coll), "fake")
    archived = sync(coll, docs_from(tmp_path, TEXTS, superseded={"fees"}), make_chunks, make_embed(coll), "fake")
    assert archived["metadata_updated"] == 1 and archived["chunks_embedded"] == 0
    assert all(r["meta"]["superseded"] for r in coll.rows.values() if r["meta"]["doc_id"] == "fees")
    restored = sync(coll, docs_from(tmp_path, TEXTS), make_chunks, make_embed(coll), "fake")
    assert restored["metadata_updated"] == 1 and restored["chunks_embedded"] == 0
    assert not any(r["meta"]["superseded"] for r in coll.rows.values())


def test_requests_delete_archive_and_restore(tmp_path: Path) -> None:
    for folder in ("lake", "archive", "incoming"):
        (tmp_path / folder).mkdir()
    (tmp_path / "lake" / "fee-2027.html").write_text("new", encoding="utf-8")
    (tmp_path / "archive" / "fee-2026.html").write_text("old", encoding="utf-8")
    (tmp_path / "lake" / "guide.md").write_text("g", encoding="utf-8")
    save_registry(tmp_path, [
        {"doc_id": "fee-2027", "file": "fee-2027.html", "folder": "lake", "family": "fee", "superseded": False, "sha256": "1"},
        {"doc_id": "fee-2026", "file": "fee-2026.html", "folder": "archive", "family": "fee", "superseded": True, "sha256": "2"},
        {"doc_id": "guide", "file": "guide.md", "folder": "lake", "family": "guide", "superseded": False, "sha256": "3"}])
    (tmp_path / "incoming" / "_requests.json").write_text(json.dumps(
        [{"action": "restore", "doc_id": "fee-2026"}, {"action": "delete", "doc_id": "guide"}]), encoding="utf-8")
    done = apply_requests(tmp_path)
    assert [d["result"] for d in done] == ["done", "done"]
    reg = {e["doc_id"]: e for e in load_registry(tmp_path)}
    assert reg["fee-2026"]["superseded"] is False and reg["fee-2026"]["folder"] == "lake"
    assert reg["fee-2027"]["superseded"] is True and reg["fee-2027"]["folder"] == "archive"
    assert "guide" not in reg and (tmp_path / "deleted" / "guide.md").exists()


def test_migrating_from_an_index_with_the_same_chunk_ids(tmp_path: Path) -> None:
    """An older index used the same chunk ids but had no doc_id. The sync must overwrite
    those chunks, not skip them and then delete them as orphans (bug found on Batch B)."""
    coll = FakeCollection()
    docs = docs_from(tmp_path, TEXTS)
    for doc in docs:
        for c in make_chunks(doc):
            coll.rows[c.id] = {"doc": c.text, "vec": [0.0, 0.0], "meta": {"source": c.source}}
    stats = sync(coll, docs, make_chunks, make_embed(coll), "fake")
    assert stats["added"] == 3 and stats["chunks_embedded"] == 8
    assert coll.count() == 8
    assert counts_by_doc(coll) == {"fees": 3, "guide": 2, "rules": 3}
