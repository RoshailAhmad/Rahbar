"""Part A1 verification: the four checks and the quarantine, with a fake embedder.

No Ollama, no Chroma: the fake embedder turns text into a bag-of-words vector, which is
enough to tell a near-copy (cosine ~0.99) from a different document (much lower).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pipeline.ingest import load_registry, run_ingest
from pipeline.verify import Candidate, check_completeness, check_quality


def fake_embed(texts: list[str]) -> list[list[float]]:
    vectors = []
    for text in texts:
        vec = [0.0] * 256
        for word in text.lower().split():
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % 256] += 1.0
        vectors.append(vec)
    return vectors


def fake_extract(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    if path.suffix == ".pdf":
        if b"%%EOF" not in data[-2048:]:
            raise ValueError("unexpected end of PDF")
        return data.decode("latin-1"), 2
    return data.decode("utf-8"), 1


RULES = "---\ntitle: Exam Rules\ndoc_version: \"2026-09\"\n---\n# Entry\n" + \
        "Students must arrive fifteen minutes early and show their card at the door. " * 6
LIBRARY = "---\ntitle: Library Rules\ndoc_version: \"2026-09\"\n---\n# Borrowing\n" + \
          "Undergraduates borrow four books for fourteen days and pay fines when late. " * 6
FEE_OLD = "<html><h1>Fees</h1><p>" + "Tuition per credit hour is listed for 2026-27 programs. " * 6 + "</p></html>"
FEE_NEW = FEE_OLD.replace("2026-27", "2027-28")
PDF_OK = b"%PDF-1.4\n" + b"Academic rules text with plenty of letters in it. " * 20 + b"\n%%EOF\n"


def put(folder: Path, name: str, content: str | bytes) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    data = content.encode() if isinstance(content, str) else content
    (folder / name).write_bytes(data)


def index_json(folder: Path, entries: list[dict]) -> None:
    (folder / "_index.json").write_text(json.dumps(entries), encoding="utf-8")


def seed_lake(data: Path) -> None:
    inc = data / "incoming"
    put(inc, "fee-structure-page.html", FEE_OLD)
    put(inc, "academic-rules.pdf", PDF_OK)
    put(inc, "exam-rules.md", RULES)
    index_json(inc, [{"file": "fee-structure-page.html", "name": "Fee Structure page", "doc_version": "2026-27"},
                     {"file": "academic-rules.pdf", "name": "Academic Rules", "doc_version": "2026-06"}])
    run_ingest(data, fake_extract, fake_embed)


def test_clean_corpus_is_accepted_into_the_lake(tmp_path: Path) -> None:
    seed_lake(tmp_path)
    assert sorted(p.name for p in (tmp_path / "lake").iterdir()) == \
        ["_registry.json", "academic-rules.pdf", "exam-rules.md", "fee-structure-page.html"]
    assert list((tmp_path / "quarantine").iterdir()) == []
    assert len(list((tmp_path / "reports").glob("verification-*.json"))) == 1


def test_batch_b_problems_are_caught(tmp_path: Path) -> None:
    seed_lake(tmp_path)
    inc = tmp_path / "incoming"
    put(inc, "b01-copy.html", FEE_OLD)                                   # exact duplicate
    put(inc, "b03-near.md", RULES.replace("door", "entrance", 1))
    put(inc, "b04-truncated.pdf", PDF_OK[: len(PDF_OK) // 2])           # cut off
    put(inc, "b05-untitled.md", "# Notes\n" + "Feedback forms open in week fourteen for courses. " * 5)
    put(inc, "b06-fee-2027.html", FEE_NEW)                               # newer version
    put(inc, "b08-library.md", LIBRARY)                                  # clean
    index_json(inc, [{"file": "b01-copy.html", "name": "Fee Structure page", "doc_version": "2026-27"},
                     {"file": "b04-truncated.pdf", "name": "Academic Rules", "doc_version": "2026-06"},
                     {"file": "b06-fee-2027.html", "name": "Fee Structure page", "doc_version": "2027-28"}])
    results, counts = run_ingest(tmp_path, fake_extract, fake_embed)
    decision = {r.file: r.decision for r in results}
    why = {r.file: r.checks for r in results}

    assert decision["b01-copy.html"] == "quarantine"
    assert "exact duplicate" in why["b01-copy.html"]["uniqueness"]["reason"]
    assert decision["b03-near.md"] == "quarantine"
    assert "near-duplicate of exam-rules" in why["b03-near.md"]["uniqueness"]["reason"]
    assert decision["b04-truncated.pdf"] == "quarantine"
    assert not why["b04-truncated.pdf"]["quality"]["pass"]
    assert decision["b05-untitled.md"] == "quarantine"
    assert "missing metadata" in why["b05-untitled.md"]["completeness"]["reason"]
    assert decision["b06-fee-2027.html"] == "accept"
    assert decision["b08-library.md"] == "accept"

    # the old fee page moved to the archive and is marked superseded
    assert (tmp_path / "archive" / "fee-structure-page.html").exists()
    entry = {e["doc_id"]: e for e in load_registry(tmp_path)}["fee-structure-page"]
    assert entry["superseded"] is True and entry["folder"] == "archive"
    assert sorted(p.name for p in (tmp_path / "quarantine").iterdir()) == \
        ["b01-copy.html", "b03-near.md", "b04-truncated.pdf", "b05-untitled.md"]
    assert counts == {"accept": 2, "quarantine": 4, "supersede": 0}


def test_an_older_version_arriving_late_is_superseded(tmp_path: Path) -> None:
    seed_lake(tmp_path)
    inc = tmp_path / "incoming"
    put(inc, "fee-2025.html", FEE_OLD.replace("2026-27", "2025-26"))
    index_json(inc, [{"file": "fee-2025.html", "name": "Fee Structure page", "doc_version": "2025-26"}])
    results, _ = run_ingest(tmp_path, fake_extract, fake_embed)
    assert results[0].decision == "supersede"
    assert "newer version exists" in results[0].checks["recency"]["reason"]


def test_quality_flags_empty_and_garbled_text(tmp_path: Path) -> None:
    path = tmp_path / "x.md"
    path.write_text("x", encoding="utf-8")
    assert not check_quality(Candidate(path=path, meta={}, text="   "))[0]
    assert "garbled" in check_quality(Candidate(path=path, meta={}, text="%$#@!" * 40 + "ab"))[1]
    assert check_quality(Candidate(path=path, meta={}, text="Real words here. " * 10))[0]


def test_completeness_flags_truncated_html(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_text("<html><p>" + "text " * 50, encoding="utf-8")
    ok, why = check_completeness(Candidate(path=path, meta={"name": "Page", "doc_version": "1"}, pages=1))
    assert not ok and "</html>" in why
