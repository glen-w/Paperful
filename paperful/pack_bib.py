"""BibTeX / RIS from snowball and authorwatch proposal packs on disk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .interop.load import dump_records
from .snowball.candidate import Candidate


def resolve_candidate_jsonl(pack: Path) -> Path:
    """Run dir, watch dir, authorwatch dir, or a ``*.jsonl`` file."""
    path = Path(pack)
    if path.is_file():
        if path.suffix.lower() == ".jsonl":
            return path
        raise FileNotFoundError(f"Expected a .jsonl file, not {path}")
    if not path.is_dir():
        raise FileNotFoundError(str(path))
    for name in ("candidates.jsonl", "inbox.jsonl"):
        candidate = path / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"No candidates.jsonl or inbox.jsonl under {path}. "
        "Use a snowball run id folder, watch folder, or authorwatch list folder."
    )


def load_candidates(jsonl_path: Path) -> list[Candidate]:
    rows: list[Candidate] = []
    with jsonl_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(Candidate.from_dict(json.loads(line)))
    return rows


def _creators(names: list[str]) -> list[dict[str, str]]:
    creators: list[dict[str, str]] = []
    for name in names:
        parts = name.split()
        if len(parts) == 1:
            creators.append({"creatorType": "author", "name": parts[0]})
            continue
        creators.append(
            {
                "creatorType": "author",
                "firstName": " ".join(parts[:-1]),
                "lastName": parts[-1],
            }
        )
    return creators


def _item_type(openalex_type: str) -> str:
    if openalex_type in {"article", "journal-article"}:
        return "journalArticle"
    if openalex_type == "posted-content":
        return "preprint"
    if openalex_type in {"book", "book-chapter"}:
        return "book" if openalex_type == "book" else "bookSection"
    return "document"


def candidate_to_record(row: Candidate) -> dict[str, Any] | None:
    biblio = row.biblio or {}
    title = str(biblio.get("title") or "").strip()
    doi = (row.ids.get("doi") or "").strip()
    if not title and not doi:
        return None
    authors = list(biblio.get("authors") or [])
    year = biblio.get("year")
    url = str(biblio.get("oa_url") or "").strip()
    oa_id = (row.ids.get("openalex") or "").strip()
    if not url and oa_id:
        url = f"https://openalex.org/{oa_id}"
    venue = str(biblio.get("venue") or "").strip()
    return {
        "item_type": _item_type(str(biblio.get("type") or "")),
        "title": title or doi,
        "creators": _creators(authors),
        "date": str(year) if year else "",
        "year": year,
        "publication_title": venue,
        "doi": doi or None,
        "url": url or None,
        "abstract": "",
        "extra": "",
        "tags": [],
        "notes": [],
        "pdfs": [],
        "collection_paths": [],
        "item_key": row.identity or None,
    }


def records_from_candidates(rows: list[Candidate]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        rec = candidate_to_record(row)
        if rec is not None:
            out.append(rec)
    return out


def dump_candidates(rows: list[Candidate], fmt: str) -> str:
    records = records_from_candidates(rows)
    if not records:
        raise ValueError("No exportable rows (need at least a title or DOI per line).")
    return dump_records(records, fmt)


def export_pack_text(pack: Path, fmt: str) -> tuple[str, Path, int]:
    jsonl = resolve_candidate_jsonl(pack)
    rows = load_candidates(jsonl)
    text = dump_candidates(rows, fmt)
    return text, jsonl, len(records_from_candidates(rows))
