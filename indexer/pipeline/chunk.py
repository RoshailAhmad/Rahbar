"""Stage 3: Chunk. Structure-aware, with overlap.

Unit: words (whitespace-separated). CHUNK_SIZE and CHUNK_OVERLAP are in words.
1. Split into sections at heading lines (Markdown `#`, numbered clauses such as
   "5.4 Academic Warning", or short ALL-CAPS lines).
2. Inside a section, pack paragraphs into chunks of at most `size` words.
3. A paragraph longer than `size` is split by sentences; a sentence longer than `size`
   is split by words.
4. Each new chunk in the same section starts with the last `overlap` words of the
   previous one. Overlap never crosses a section boundary.
The section heading is also prefixed to each chunk's text, so the embedding (and an
exact-term search) sees "5.4 Academic Warning" together with its body.
"""

from __future__ import annotations

import re

from .models import Chunk, Document

MD_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
NUMBERED_HEADING = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+([A-Z][^.!?]{2,80})$")
CAPS_HEADING = re.compile(r"^[A-Z][A-Z0-9 &/,\-()]{4,70}$")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")
SMALL_WORDS = {"a", "an", "and", "or", "of", "the", "in", "on", "for", "to", "at", "by",
               "with", "from", "as", "per", "vs", "&", "-"}
# A heading never ends on a word like these; a sentence cut at the line break does.
DANGLING = {"a", "an", "and", "or", "of", "the", "in", "on", "for", "to", "at", "by",
            "with", "from", "as", "within", "is", "are", "be", "that", "which", "will"}


def _looks_like_title(text: str) -> bool:
    """'Academic Warning' or 'Attendance' yes; 'Political activities are prohibited' no.
    Numbered list items in the handbooks are sentences in sentence case."""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", text)]
    if not words or words[-1].lower() in DANGLING:
        return False
    if len(words) <= 3:
        return True
    content = [w for w in words if w.lower() not in SMALL_WORDS]
    capitalised = sum(1 for w in content if w[0].isupper())
    return capitalised / max(len(content), 1) >= 0.7


def _heading(line: str) -> str | None:
    line = line.strip()
    if not line or len(line) > 90:
        return None
    m = MD_HEADING.match(line)
    if m:
        return m.group(1).strip()
    m = NUMBERED_HEADING.match(line)
    if m and len(m.group(2).split()) <= 10 and _looks_like_title(m.group(2)):
        return f"{m.group(1)} {m.group(2).strip()}"
    if CAPS_HEADING.match(line) and len(line.split()) <= 8:
        return line.title()
    return None


def _sections(doc: Document) -> list[tuple[str, list[tuple[int, str]]]]:
    """[(section, [(page, paragraph), ...]), ...] in document order."""
    sections: list[tuple[str, list[tuple[int, str]]]] = [("Preamble", [])]
    for page in doc.pages:
        paragraph: list[str] = []

        def flush(page_no: int = page.page) -> None:
            if paragraph:
                sections[-1][1].append((page_no, " ".join(paragraph)))
                paragraph.clear()

        for line in page.text.splitlines():
            title = _heading(line)
            if title:
                flush()
                sections.append((title, []))
            elif not line.strip():
                flush()
            else:
                paragraph.append(line.strip())
        flush()
    return [(title, paras) for title, paras in sections if paras]


def _units(paragraph: str, size: int) -> list[str]:
    """Pieces of at most `size` words: the paragraph, else its sentences, else words."""
    if len(paragraph.split()) <= size:
        return [paragraph]
    units: list[str] = []
    for sentence in SENTENCE_END.split(paragraph):
        words = sentence.split()
        for i in range(0, len(words), size):
            units.append(" ".join(words[i:i + size]))
    return units


def _chunk_id(source: str, n: int) -> str:
    return f"{re.sub(r'[^a-z0-9]+', '-', source.lower()).strip('-')}::{n:04d}"


def chunk(doc: Document, size: int, overlap: int) -> list[Chunk]:
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError(f"need size > 0 and 0 <= overlap < size, got {size}, {overlap}")
    chunks: list[Chunk] = []

    def emit(section: str, page: int, words: list[str]) -> None:
        chunks.append(Chunk(
            id=_chunk_id(doc.source, len(chunks)),
            text=f"{section}\n{' '.join(words)}",
            source=doc.source, section=section, page=page,
            doc_version=doc.doc_version, superseded=doc.superseded,
        ))

    for section, paragraphs in _sections(doc):
        current: list[str] = []
        current_page = paragraphs[0][0]
        fresh = 0   # words added since the last emit (excludes carried-over overlap)
        for page, paragraph in paragraphs:
            for unit in _units(paragraph, size - overlap):
                words = unit.split()
                if current and len(current) + len(words) > size:
                    emit(section, current_page, current)
                    current = current[-overlap:] if overlap else []
                    current_page = page
                    fresh = 0
                if not current:
                    current_page = page
                current.extend(words)
                fresh += len(words)
        if fresh:
            emit(section, current_page, current)
    return chunks
