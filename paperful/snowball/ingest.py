"""Create new parents, then optionally fill PDFs with the existing pipeline."""

from __future__ import annotations

from typing import Any

from rich.console import Console

from ..config import Config
from ..interop.load import parent_payload
from ..library import LibraryBackend, LibraryError
from ..pipeline import Pipeline
from ..store import Manifest
from ..zot import Item
from .candidate import Candidate

TAG = "paperful-snowball"


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


def create_new(
    backend: LibraryBackend,
    rows: list[Candidate],
    collection: str,
    *,
    tag_prefix: str = TAG,
    note_provenance: bool = True,
) -> tuple[list[Item], dict[str, int]]:
    """Create status=new rows. One LibraryError does not abort the rest."""
    collection_key = backend.ensure_collection_path(collection)
    created_items: list[Item] = []
    created = 0
    skipped_exists = 0
    failed = 0
    prefix = tag_prefix or TAG
    for row in rows:
        if row.status == "exists":
            skipped_exists += 1
            continue
        if row.status != "new" or row.keep is False:
            continue
        biblio = row.biblio
        year = biblio.get("year")
        authors = list(biblio.get("authors") or [])
        record = {
            "item_type": _item_type(str(biblio.get("type") or "")),
            "title": biblio.get("title") or "",
            "creators": _creators(authors),
            "date": str(year) if year else "",
            "doi": row.ids.get("doi") or "",
            "url": biblio.get("oa_url") or "",
            "publication_title": biblio.get("venue") or "",
            "tags": [{"tag": prefix}, {"tag": f"{prefix}:{row.provenance.get('backend') or 'openalex'}"}],
        }
        payload = parent_payload(record, [collection_key])
        try:
            key = backend.create_parent(payload)
        except LibraryError as exc:
            failed += 1
            row.status = "error"
            row.why = str(exc)
            continue
        created += 1
        note = (
            f"<p>snowball {row.schema}<br>"
            f"seed: {row.seed.get('type')} {row.seed.get('value')}<br>"
            f"direction: {row.direction} hop: {row.hop}<br>"
            f"why: {row.why}<br>"
            f"run: {row.run_id}</p>"
        )
        if note_provenance:
            backend.create_or_update_note(key, note, prefix)
        first = authors[0].split()[-1] if authors else None
        created_items.append(
            Item(
                key=key,
                item_type=record["item_type"],
                title=str(record["title"]),
                doi=record["doi"] or None,
                arxiv_id=None,
                url=record["url"] or None,
                year=int(year) if year else None,
                first_author=first,
                collection_paths=[collection],
                doi_source="crossref" if record["doi"] else "none",
            )
        )
    return created_items, {"created": created, "skipped_exists": skipped_exists, "failed": failed}


def fill_pdfs(cfg: Config, backend: Any, items: list[Item], console: Console) -> Any:
    """Existing run pipeline, limited to the keys just created."""
    attacher = backend if cfg.attach else None
    pipe = Pipeline(
        cfg,
        Manifest(cfg.manifest_path),
        console,
        sources=list(cfg.sources),
        attacher=attacher,
        use_browser=False,
    )
    return pipe.run(items)
