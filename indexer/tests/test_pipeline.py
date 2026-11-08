"""Extract, clean, chunk and store, with no model and no Chroma server."""

from __future__ import annotations

from pathlib import Path

from pipeline.chunk import chunk
from pipeline.clean import clean
from pipeline.config import get_settings
from pipeline.extract import extract
from pipeline.models import Document, Page
from pipeline.store import store

FIXTURES = Path(__file__).resolve().parents[2] / "eval" / "fixtures"


def _doc(text: str, pages: int = 1) -> Document:
    return Document(source="rules.md", doc_version="2026", superseded=False,
                    pages=[Page(source="rules.md", page=i + 1, text=text) for i in range(pages)])


def test_chunks_keep_their_section_and_metadata() -> None:
    doc = _doc("# 1. Attendance\n\nStudents must attend 80 percent.\n\n"
               "# 2. Academic warning\n\nBelow 2.00 CGPA means warning.")
    chunks = chunk(doc, size=50, overlap=5)
    assert [c.section for c in chunks] == ["1. Attendance", "2. Academic warning"]
    assert all(c.doc_version == "2026" and c.superseded is False for c in chunks)
    assert "80 percent" in chunks[0].text and "2.00" in chunks[1].text


def test_long_sections_split_with_overlap_and_stable_ids() -> None:
    words = " ".join(f"w{i}." for i in range(120))
    doc = _doc(f"# 5.4 Academic Warning\n\n{words}")
    chunks = chunk(doc, size=50, overlap=10)
    assert len(chunks) >= 3
    first = chunks[0].text.split()[-10:]
    second = chunks[1].text.split("\n", 1)[1].split()[:10]
    assert first == second                       # neighbours share `overlap` words
    assert all(len(c.text.split("\n", 1)[1].split()) <= 50 for c in chunks)
    assert [c.id for c in chunks] == [c.id for c in chunk(doc, size=50, overlap=10)]


def test_clean_strips_repeating_headers_and_page_numbers_but_keeps_headings() -> None:
    topics = ["Attendance", "Academic Warning", "Repeating Courses", "Fees"]
    pages = [Page(source="r.pdf", page=i + 1,
                  text=f"FAST-NUCES Academic Rules\n{i + 1}.1 {t}\nRules about {t.lower()}.\n{i + 1}")
             for i, t in enumerate(topics)]
    cleaned = clean(Document(source="r.pdf", doc_version="2026", superseded=False, pages=pages))
    text = cleaned.pages[0].text
    assert "FAST-NUCES Academic Rules" not in text
    assert "1" not in text.splitlines()
    assert "1.1 Attendance" in text and "Rules about attendance." in text


def test_fixture_markdown_extracts_without_front_matter() -> None:
    doc = extract(str(FIXTURES / "academic-rules-2026.md"), "2026", False)
    assert not doc.pages[0].text.startswith("---")
    sections = {c.section for c in chunk(clean(doc), size=400, overlap=50)}
    assert "2. Academic warning" in sections


class _FakeCollection:
    def __init__(self, metadata: dict) -> None:
        self.metadata, self.rows = metadata, 0

    def add(self, ids, documents, embeddings, metadatas) -> None:  # type: ignore[no-untyped-def]
        assert {"source", "section", "page", "doc_version", "superseded"} <= set(metadatas[0])
        self.rows += len(ids)

    def count(self) -> int:
        return self.rows


class _FakeClient:
    def delete_collection(self, name: str) -> None:
        raise ValueError("does not exist")

    def create_collection(self, name: str, metadata: dict) -> _FakeCollection:
        self.collection = _FakeCollection(metadata)
        return self.collection


def test_store_records_the_embedding_pin_and_index_version() -> None:
    chunks = chunk(_doc("# 1. Rules\n\nSome text."), size=50, overlap=5)
    client = _FakeClient()
    n = store(chunks, [[0.1, 0.2, 0.3]] * len(chunks), get_settings(), client=client)
    meta = client.collection.metadata
    assert n == len(chunks)
    assert meta["embed_model"] == get_settings().embed_model
    assert meta["dimension"] == 3 and meta["index_version"]


def test_numbered_sentences_are_not_mistaken_for_headings() -> None:
    from pipeline.chunk import _heading

    assert _heading("5.4 Academic Warning") == "5.4 Academic Warning"
    assert _heading("1.21 Attendance") == "1.21 Attendance"
    assert _heading("3 Fee Refund Policy for Withdrawal") is not None
    assert _heading("14 Political activities or campaigns are strictly prohibited within") is None
    assert _heading("2 Students must carry their ID cards") is None
