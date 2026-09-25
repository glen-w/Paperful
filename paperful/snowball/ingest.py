"""Create new parents, then optionally fill PDFs with the existing pipeline."""

from __future__ import annotations

from typing import Any

from rich.console import Console

from ..config import RECOVER_DISCLAIMER, SCIHUB_DISCLAIMER, Config, parse_fetch_pdfs
from ..interop.load import parent_payload
from ..library import LibraryBackend, LibraryError
from ..pipeline import Pipeline, RunStats
from ..remarks import linked_sentence, say
from ..routing import with_recover_lane
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
    console: Console | None = None,
    tally: Any = None,
    remarks_surface: str = "note",
    local_cites: Any = None,
) -> tuple[list[Item], dict[str, int]]:
    """Create status=new rows. One LibraryError does not abort the rest."""
    collection_key = backend.ensure_collection_path(collection)
    created_items: list[Item] = []
    created = 0
    skipped_exists = 0
    failed = 0
    prefix = tag_prefix or TAG
    pending = sum(1 for row in rows if row.status == "new" and row.keep is not False)
    if console is not None:
        console.print(f"[green]creating {pending} items in {collection}[/]")
    if tally is not None:
        tally.stage = "creating"
        tally.track(pending)
    if local_cites is not None and getattr(local_cites, "prepare", None):
        client = getattr(local_cites, "client", None)
        if client is not None:
            local_cites.prepare(rows, client)
    for row in rows:
        if row.status in {"exists", "version"}:
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
            if tally is not None:
                tally.advance(1)
            continue
        created += 1
        if tally is not None:
            tally.created = created
            tally.advance(1)
        note = (
            f"<p>snowball {row.schema}<br>"
            f"seed: {row.seed.get('type')} {row.seed.get('value')}<br>"
            f"direction: {row.direction} hop: {row.hop}<br>"
            f"why: {row.why}<br>"
            f"run: {row.run_id}</p>"
        )
        if note_provenance:
            backend.create_or_update_note(key, note, prefix)
        cite_count = 0
        if local_cites is not None:
            cite_count = local_cites.count(
                openalex=str(row.ids.get("openalex") or ""),
                doi=str(row.ids.get("doi") or ""),
            )
        line = linked_sentence(
            hop=row.hop,
            direction=row.direction,
            overlap=int(row.biblio.get("overlap") or 0),
            cite_count=cite_count,
            library=bool(getattr(local_cites, "library", False)),
        )
        if line:
            say(backend, key, "linked", line, surface=remarks_surface)
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


def fill_pdfs(
    cfg: Config,
    backend: Any,
    items: list[Item],
    console: Console,
    *,
    tally: Any = None,
    mode: str = "fast",
) -> RunStats:
    """Fill PDFs for the keys just created.

    ``fast`` is the open-access first pass (no vault browser). ``full`` runs
    that pass, then the same source stack as ``run`` — browser lanes and the
    recover agent when configured — on items the manifest still wants.
    """
    mode = parse_fetch_pdfs(mode)
    if mode == "off" or not items:
        return RunStats()
    attacher = backend if cfg.attach else None
    fast = _run_fill(
        cfg,
        items,
        console,
        attacher=attacher,
        sources=list(cfg.sources),
        use_browser=False,
        tally=tally,
        stage="fetching PDFs",
    )
    if mode == "fast":
        return fast
    manifest = Manifest(cfg.manifest_path)
    left = [it for it in items if manifest.should_process(it.key, False)]
    if not left:
        return fast
    sources = with_recover_lane(cfg, list(cfg.sources))
    if "scihub" in sources:
        console.print(f"[yellow]{SCIHUB_DISCLAIMER}[/]")
    if "browser_agent" in sources:
        console.print(f"[yellow]{RECOVER_DISCLAIMER}[/]")
    console.print(
        f"full stack: {len(left)} still without a PDF. Sources: {', '.join(sources)}"
    )
    full = _run_fill(
        cfg,
        left,
        console,
        attacher=attacher,
        sources=sources,
        use_browser=True,
        tally=tally,
        stage="fetching PDFs (full)",
        prior_ok=int(fast.ok),
    )
    fast.ok += full.ok
    fast.attached += full.attached
    fast.attach_failed = full.attach_failed
    return fast


def _run_fill(
    cfg: Config,
    items: list[Item],
    console: Console,
    *,
    attacher: Any,
    sources: list[str],
    use_browser: bool,
    tally: Any,
    stage: str,
    prior_ok: int = 0,
) -> RunStats:
    def _tick() -> None:
        if tally is not None:
            tally.advance(1)

    pipe = Pipeline(
        cfg,
        Manifest(cfg.manifest_path),
        console,
        sources=sources,
        attacher=attacher,
        use_browser=use_browser,
        progress=_tick if tally is not None else None,
    )
    if tally is not None:
        tally.stage = stage
        tally.track(len(items))
        tally.bind_pdfs(
            lambda: prior_ok + int(getattr(getattr(pipe, "stats", None), "ok", 0) or 0)
        )
    return pipe.run(items)
