"""Stage 1: Extract. PDF, HTML or Markdown to text, page by page.

- PDF: pdfplumber. Tables are pulled out separately and written as `a | b | c` rows,
  so their columns stay together instead of being interleaved with the prose.
- A page with (almost) no text layer is OCR'd with Tesseract and marked ocr=True.
  OCR needs tesseract-ocr and poppler-utils, which the indexer image installs; on a
  laptop without them the page stays empty and a warning is logged.
- HTML: tags stripped, table rows kept as `a | b | c`, headings kept as `# heading`.
- Markdown: front matter removed, the rest kept as one page.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from html.parser import HTMLParser
from typing import Any

from .models import Document, Page

MIN_TEXT_CHARS = 20   # below this, a PDF page is treated as having no text layer


def _log(msg: str, **fields: object) -> None:
    print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "logger": "rahbar.indexer.extract", "msg": msg, **fields}),
          file=sys.stdout, flush=True)


def _table_rows(table: list[list[Any]]) -> str:
    rows = []
    for row in table:
        cells = [re.sub(r"\s+", " ", str(c)).strip() if c is not None else "" for c in row]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _ocr_page(path: str, number: int) -> str:
    try:
        import pytesseract
        from pdf2image import convert_from_path

        images = convert_from_path(path, dpi=200, first_page=number, last_page=number)
        return str(pytesseract.image_to_string(images[0])) if images else ""
    except Exception as exc:  # tesseract/poppler missing (laptop), or a broken page
        _log("ocr unavailable for page", source=os.path.basename(path), page=number,
             error=f"{type(exc).__name__}: {exc}")
        return ""


def _extract_pdf(path: str) -> list[Page]:
    import pdfplumber

    source = os.path.basename(path)
    pages: list[Page] = []
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            boxes = [t.bbox for t in tables]

            def outside_tables(obj: dict[str, Any], boxes: list[Any] = boxes) -> bool:
                if "x0" not in obj or "top" not in obj:
                    return True
                return not any(x0 <= obj["x0"] and obj["x1"] <= x1
                               and top <= obj["top"] and obj["bottom"] <= bottom
                               for (x0, top, x1, bottom) in boxes)

            prose_source = page.filter(outside_tables) if boxes else page
            text = prose_source.extract_text() or ""
            table_text = "\n\n".join(_table_rows(t.extract()) for t in tables)
            if table_text.strip():
                text = f"{text}\n\n{table_text}"

            ocr = False
            if len(text.strip()) < MIN_TEXT_CHARS:
                text = _ocr_page(path, number)
                ocr = True
            pages.append(Page(source=source, page=number, text=text, ocr=ocr))
    if any(p.ocr for p in pages):
        _log("ocr used", source=source, pages=[p.page for p in pages if p.ocr],
             recovered_chars=sum(len(p.text) for p in pages if p.ocr))
    return pages


class _HTMLText(HTMLParser):
    SKIP = {"script", "style", "nav", "header", "footer", "noscript", "svg", "form"}
    BLOCK = {"p", "div", "section", "article", "li", "br", "ul", "ol", "table", "tbody"}
    HEADINGS = {"h1", "h2", "h3", "h4"}

    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []
        self.skip_depth = 0
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.heading: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self.skip_depth += 1
        elif self.skip_depth:
            return
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []
        elif tag in self.HEADINGS:
            self.heading = []
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif self.skip_depth:
            return
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if any(self.row):
                self.out.append("\n" + " | ".join(self.row) + "\n")
            self.row = None
        elif tag in self.HEADINGS and self.heading is not None:
            title = " ".join("".join(self.heading).split())
            if title:
                self.out.append(f"\n\n# {title}\n\n")
            self.heading = None
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif self.heading is not None:
            self.heading.append(data)
        else:
            self.out.append(data)


def _extract_html(path: str) -> list[Page]:
    with open(path, encoding="utf-8", errors="replace") as f:
        parser = _HTMLText()
        parser.feed(f.read())
    text = "".join(parser.out)
    text = "\n".join(line.strip() for line in text.splitlines())
    return [Page(source=os.path.basename(path), page=1, text=text)]


def _extract_markdown(path: str) -> list[Page]:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    return [Page(source=os.path.basename(path), page=1, text=text)]


def extract(path: str, doc_version: str, superseded: bool) -> Document:
    """Return the document's text page by page. Pages with no text layer are OCR'd."""
    suffix = os.path.splitext(path)[1].lower()
    if suffix == ".pdf":
        pages = _extract_pdf(path)
    elif suffix in (".html", ".htm"):
        pages = _extract_html(path)
    elif suffix in (".md", ".txt"):
        pages = _extract_markdown(path)
    else:
        raise ValueError(f"unsupported document type: {path}")
    return Document(source=os.path.basename(path), doc_version=doc_version,
                    superseded=superseded, pages=pages)
