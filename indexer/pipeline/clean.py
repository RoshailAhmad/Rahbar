"""Stage 2: Clean. Remove artefacts without destroying structure.

Rules (also listed in docs/PIPELINE.md):
1. A line that appears on more than half the pages of a document (3+ pages) is a
   running header or footer, and is removed.
2. Lines that are only a page number ("12", "Page 3", "3 of 40") are removed.
3. Words hyphenated across a line break are joined ("regu-\\nlation" -> "regulation").
4. Runs of spaces collapse to one; three or more blank lines collapse to one.
Deliberately NOT stripped: heading lines such as "5.4 Academic Warning". Chunking uses
them as section boundaries, and citations name them.
"""

from __future__ import annotations

import re
from collections import Counter

from .models import Document, Page

PAGE_NUMBER = re.compile(r"^\s*(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?\s*$", re.IGNORECASE)


def _normalise(line: str) -> str:
    """Compare header/footer lines ignoring digits, so 'Page 3' and 'Page 4' match."""
    return re.sub(r"\d+", "#", line.strip().lower())


def clean(doc: Document) -> Document:
    repeated: set[str] = set()
    if len(doc.pages) >= 3:
        counts: Counter[str] = Counter()
        for page in doc.pages:
            counts.update({_normalise(line) for line in page.text.splitlines() if line.strip()})
        repeated = {line for line, n in counts.items() if n > len(doc.pages) / 2}

    cleaned: list[Page] = []
    for page in doc.pages:
        lines = []
        for line in page.text.splitlines():
            if line.strip() and _normalise(line) in repeated:
                continue
            if PAGE_NUMBER.match(line):
                continue
            lines.append(line)
        text = "\n".join(lines)
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        cleaned.append(Page(source=page.source, page=page.page, text=text, ocr=page.ocr))
    return Document(source=doc.source, doc_version=doc.doc_version,
                    superseded=doc.superseded, pages=cleaned)
