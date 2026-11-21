"""Verification stage (Assignment 03, Part A1; RAGOps paper 4.2.2).

Runs after extraction and before chunking. For every incoming document it records pass or
fail, with a reason, for four checks:

  quality       empty text, garbled text, or extraction that failed
  completeness  required metadata present (source, title, date or version, page count);
                text not truncated (a PDF without its %%EOF trailer, HTML without </html>)
  recency       a newer version of the same document (same `family`) is already known
  uniqueness    exact duplicate (SHA-256) or near-duplicate (embedding cosine >= threshold)

Decisions: "accept" (all four pass), "quarantine" (quality, completeness or uniqueness
fails: not indexed), "supersede" (only recency fails: kept, archived, superseded=true).

The embedding function is passed in, so tests run with a fake embedder and no model.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

Embedder = Callable[[list[str]], list[list[float]]]

NEAR_DUP_THRESHOLD = 0.97     # cosine on the opening text; real near-copies score ~0.99
MIN_TEXT_CHARS = 50           # less than this after extraction counts as empty
MIN_LETTER_RATIO = 0.5        # below this share of letters the text is garbled
OPENING_CHARS = 2000          # how much of each document the near-duplicate check embeds


@dataclass
class Candidate:
    """One document to verify: its file, its metadata and its extracted text."""

    path: Path
    meta: dict                    # from _index.json or Markdown front matter
    text: str = ""
    pages: int = 0
    extract_error: str | None = None
    sha256: str = ""
    opening_vector: list[float] | None = None

    @property
    def doc_id(self) -> str:
        return self.path.stem

    @property
    def title(self) -> str | None:
        return self.meta.get("name") or self.meta.get("title")

    @property
    def version(self) -> str | None:
        value = self.meta.get("doc_version") or self.meta.get("date")
        return str(value) if value not in (None, "", "unknown") else None

    @property
    def family(self) -> str | None:
        """Documents with the same family are versions of each other."""
        name = self.meta.get("family") or self.title
        return re.sub(r"\s+", " ", name.strip().lower()) if name else None


@dataclass
class Known:
    """A document already accepted into the data lake (from the registry)."""

    doc_id: str
    sha256: str
    family: str | None
    version: str | None
    opening_vector: list[float] | None = None


@dataclass
class Result:
    doc_id: str
    file: str
    checks: dict[str, dict] = field(default_factory=dict)
    decision: str = "accept"
    supersedes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"doc_id": self.doc_id, "file": self.file, "decision": self.decision,
                "supersedes": self.supersedes, "checks": self.checks}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _version_key(version: str | None) -> tuple:
    """'2027-28' > '2026-27' > '2026-06' > '2026'; compares the numbers in order."""
    return tuple(int(n) for n in re.findall(r"\d+", version or ""))


def check_quality(c: Candidate) -> tuple[bool, str]:
    if c.extract_error:
        return False, f"extraction failed: {c.extract_error}"
    stripped = re.sub(r"\s+", "", c.text)
    if len(stripped) < MIN_TEXT_CHARS:
        return False, f"empty: {len(stripped)} characters after extraction"
    letters = sum(ch.isalpha() for ch in stripped)
    ratio = letters / len(stripped)
    if ratio < MIN_LETTER_RATIO:
        return False, f"garbled: only {ratio:.0%} of characters are letters"
    return True, f"{len(stripped)} characters, {ratio:.0%} letters"


def is_truncated(path: Path) -> str | None:
    """A reason string when the file looks cut off, else None."""
    data = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == ".pdf" and b"%%EOF" not in data[-2048:]:
        return "PDF has no %%EOF trailer (file cut off)"
    if suffix in (".html", ".htm") and b"</html>" not in data[-4096:].lower():
        return "HTML has no closing </html> tag"
    return None


def check_completeness(c: Candidate) -> tuple[bool, str]:
    missing = [name for name, value in (("title", c.title), ("date or version", c.version)) if not value]
    if c.pages < 1:
        missing.append("page count")
    if missing:
        return False, "missing metadata: " + ", ".join(missing)
    truncated = is_truncated(c.path)
    if truncated:
        return False, f"truncated: {truncated}"
    return True, f"title, version {c.version}, {c.pages} page(s), not truncated"


def check_recency(c: Candidate, known: list[Known], batch: list[Candidate]) -> tuple[bool, str, list[str]]:
    """Fail when a newer version of the same family exists. Also returns the older
    versions this document supersedes (they get archived)."""
    if not c.family:
        return True, "no family to compare (see completeness)", []
    others = [(k.doc_id, k.version) for k in known if k.family == c.family and k.doc_id != c.doc_id]
    others += [(b.doc_id, b.version) for b in batch if b.family == c.family and b.doc_id != c.doc_id
               and b.sha256 != c.sha256]
    newer = [doc for doc, ver in others if _version_key(ver) > _version_key(c.version)]
    older = [doc for doc, ver in others if _version_key(ver) < _version_key(c.version)]
    if newer:
        return False, f"a newer version exists: {', '.join(sorted(set(newer)))}", []
    if older:
        return True, f"newest version; supersedes {', '.join(sorted(set(older)))}", sorted(set(older))
    return True, "no other version known", []


def check_uniqueness(c: Candidate, known: list[Known], accepted: list[Candidate],
                     threshold: float) -> tuple[bool, str]:
    for k in known:
        if k.sha256 == c.sha256:
            return False, f"exact duplicate (SHA-256) of {k.doc_id}"
    for a in accepted:
        if a.sha256 == c.sha256:
            return False, f"exact duplicate (SHA-256) of {a.doc_id}"
    if c.opening_vector is not None:
        best_doc, best = None, 0.0
        for doc_id, vec in [(k.doc_id, k.opening_vector) for k in known] + \
                           [(a.doc_id, a.opening_vector) for a in accepted]:
            if vec is not None:
                score = cosine(c.opening_vector, vec)
                if score > best:
                    best_doc, best = doc_id, score
        if best >= threshold:
            return False, f"near-duplicate of {best_doc} (cosine {best:.3f} >= {threshold})"
        return True, f"unique (closest cosine {best:.3f})"
    return True, "unique by hash (no embedding)"


def verify(candidates: list[Candidate], known: list[Known], embed: Embedder | None,
           threshold: float = NEAR_DUP_THRESHOLD) -> list[Result]:
    """Run the four checks on every candidate, in file-name order."""
    candidates = sorted(candidates, key=lambda c: c.path.name)
    for c in candidates:
        c.sha256 = c.sha256 or sha256_file(c.path)
    if embed is not None:
        with_text = [c for c in candidates if c.text.strip()]
        if with_text:
            vectors = embed([c.text[:OPENING_CHARS] for c in with_text])
            for c, v in zip(with_text, vectors):
                c.opening_vector = v

    results: list[Result] = []
    accepted: list[Candidate] = []
    for c in candidates:
        r = Result(doc_id=c.doc_id, file=c.path.name)
        q_ok, q_why = check_quality(c)
        co_ok, co_why = check_completeness(c)
        re_ok, re_why, supersedes = check_recency(c, known, candidates)
        u_ok, u_why = check_uniqueness(c, known, accepted, threshold)
        r.checks = {"quality": {"pass": q_ok, "reason": q_why},
                    "completeness": {"pass": co_ok, "reason": co_why},
                    "recency": {"pass": re_ok, "reason": re_why},
                    "uniqueness": {"pass": u_ok, "reason": u_why}}
        if not (q_ok and co_ok and u_ok):
            r.decision = "quarantine"
        elif not re_ok:
            r.decision = "supersede"
            accepted.append(c)
        else:
            r.decision = "accept"
            r.supersedes = supersedes
            accepted.append(c)
        results.append(r)
    return results


def report_markdown(results: list[Result], run_id: str) -> str:
    def cell(check: dict) -> str:
        return ("PASS" if check["pass"] else "FAIL") + ": " + check["reason"].replace("|", "/")

    lines = [f"# Verification report {run_id}", "",
             "| Document | Quality | Completeness | Recency | Uniqueness | Decision |",
             "| --- | --- | --- | --- | --- | --- |"]
    for r in results:
        lines.append(f"| {r.file} | {cell(r.checks['quality'])} | {cell(r.checks['completeness'])} | "
                     f"{cell(r.checks['recency'])} | {cell(r.checks['uniqueness'])} | {r.decision} |")
    fails = {name: sum(1 for r in results if not r.checks[name]["pass"])
             for name in ("quality", "completeness", "recency", "uniqueness")}
    lines += ["", "Failures per check: " + ", ".join(f"{k} {v}" for k, v in fails.items())]
    return "\n".join(lines) + "\n"
