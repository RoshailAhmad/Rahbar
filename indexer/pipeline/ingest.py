"""Ingestion with verification (Assignment 03, Part A1) over the data lake on the PVC.

    DATA_DIR/incoming/    new files (+ optional _index.json with their metadata)
    DATA_DIR/lake/        accepted documents      + lake/_registry.json (one entry per document)
    DATA_DIR/quarantine/  failed documents (never indexed)
    DATA_DIR/archive/     superseded versions (still indexed with superseded=true; restorable)
    DATA_DIR/reports/     verification-<run_id>.json and .md, one pair per run
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .verify import Candidate, Embedder, Known, Result, report_markdown, verify

SUPPORTED = {".pdf", ".html", ".htm", ".md", ".txt"}


def _front_matter(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta: dict = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"')
    return meta


def load_registry(data_dir: Path) -> list[dict]:
    path = data_dir / "lake" / "_registry.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def save_registry(data_dir: Path, entries: list[dict]) -> None:
    path = data_dir / "lake" / "_registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def incoming_candidates(data_dir: Path, extract_text) -> list[Candidate]:
    """extract_text(path) -> (text, pages). An exception counts as failed extraction."""
    incoming = data_dir / "incoming"
    index_path = incoming / "_index.json"
    index = {e["file"]: e for e in json.loads(index_path.read_text(encoding="utf-8"))} \
        if index_path.exists() else {}
    candidates = []
    for path in sorted(incoming.iterdir()):
        if path.suffix.lower() not in SUPPORTED or path.name.lower().startswith("readme"):
            continue
        meta = dict(index.get(path.name) or {})
        if path.suffix.lower() == ".md":
            meta = {**_front_matter(path), **meta}
        c = Candidate(path=path, meta=meta)
        try:
            c.text, c.pages = extract_text(path)
        except Exception as exc:  # a corrupt file must be quarantined, not crash the Job
            c.extract_error = f"{type(exc).__name__}: {exc}"[:200]
        candidates.append(c)
    return candidates


def apply_decisions(data_dir: Path, candidates: list[Candidate], results: list[Result]) -> dict[str, int]:
    """Move files and update the registry. Returns counts per decision."""
    by_id = {c.doc_id: c for c in candidates}
    registry = {e["doc_id"]: e for e in load_registry(data_dir)}
    counts = {"accept": 0, "quarantine": 0, "supersede": 0}
    for r in results:
        c = by_id[r.doc_id]
        counts[r.decision] += 1
        if r.decision == "quarantine":
            dest = data_dir / "quarantine"
        elif r.decision == "supersede":
            dest = data_dir / "archive"
        else:
            dest = data_dir / "lake"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(c.path), str(dest / c.path.name))
        if r.decision == "quarantine":
            continue
        registry[c.doc_id] = {
            "doc_id": c.doc_id, "file": c.path.name, "folder": dest.name, "sha256": c.sha256,
            "title": c.title, "family": c.family, "doc_version": c.version or "unknown",
            "superseded": r.decision == "supersede" or bool(c.meta.get("superseded", False)),
            "pages": c.pages, "opening_vector": c.opening_vector,
        }
        for old in r.supersedes:  # an older version already in the lake moves to the archive
            entry = registry.get(old)
            if entry and entry["folder"] == "lake":
                shutil.move(str(data_dir / "lake" / entry["file"]), str(data_dir / "archive" / entry["file"]))
                entry.update(folder="archive", superseded=True)
    save_registry(data_dir, list(registry.values()))
    return counts


def run_ingest(data_dir: Path, extract_text, embed: Embedder | None) -> tuple[list[Result], dict[str, int]]:
    for name in ("incoming", "lake", "quarantine", "archive", "reports"):
        (data_dir / name).mkdir(parents=True, exist_ok=True)
    candidates = incoming_candidates(data_dir, extract_text)
    known = [Known(doc_id=e["doc_id"], sha256=e["sha256"], family=e.get("family"),
                   version=e.get("doc_version"), opening_vector=e.get("opening_vector"))
             for e in load_registry(data_dir)]
    results = verify(candidates, known, embed)
    counts = apply_decisions(data_dir, candidates, results)
    leftover = data_dir / "incoming" / "_index.json"
    if leftover.exists():
        leftover.unlink()

    run_id = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    report = {"run_id": run_id, "documents": len(results), "decisions": counts,
              "results": [r.to_dict() for r in results]}
    reports = data_dir / "reports"
    (reports / f"verification-{run_id}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (reports / f"verification-{run_id}.md").write_text(report_markdown(results, run_id), encoding="utf-8")
    return results, counts


def lake_documents(data_dir: Path) -> list[tuple[Path, str, bool]]:
    """(path, doc_version, superseded) for every document to index: lake + archive."""
    return [(data_dir / e["folder"] / e["file"], str(e.get("doc_version", "unknown")),
             bool(e.get("superseded", False))) for e in load_registry(data_dir)]
