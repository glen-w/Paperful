"""Library actions from the Discover citation map (add, annotate, find PDF, remove)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..capture import clip_tags, list_collection_paths, list_tag_names, safe_collection
from ..config import Config
from ..library import LibraryError
from ..mirror import pdf_for_key
from .candidate import Candidate
from .citation_graph import CitationGraphError, build_graph, valid_run_id, write_graph_file
from .queue import load_queue


def _rewrite_queue(dest: Path, rows: list[Candidate]) -> None:
    path = dest / "candidates.jsonl"
    path.write_text(
        "".join(json.dumps(row.to_dict(), ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _find_row(rows: list[Candidate], node_id: str) -> Candidate:
    target = next((row for row in rows if row.identity == node_id), None)
    if target is None:
        raise CitationGraphError("That paper is not in this queue.")
    return target


def _rebuild_graph(cfg: Config, rows: list[Candidate], run_id: str) -> dict[str, Any]:
    return build_graph(
        rows,
        run_id=run_id,
        map_categories=getattr(cfg, "snowball_map_categories", None),
        map_category_defs=getattr(cfg, "snowball_map_category_defs", None),
        out_dir=cfg.out_dir,
    )


def graph_meta(cfg: Config) -> dict[str, Any]:
    """Collections and tags for map pickers."""
    live = None
    try:
        from ..library import get_backend

        live = get_backend(cfg)
    except Exception:
        live = None
    return {
        "collections": list_collection_paths(cfg, live),
        "tags": list_tag_names(cfg, live),
        "edit": getattr(cfg, "ui_citation_map_edit", "both") or "both",
        "auto_search": bool(getattr(cfg, "ui_citation_map_auto_search", False)),
        "remove_mode": getattr(cfg, "ui_citation_map_remove", "trash") or "trash",
    }


def annotate_queue(
    cfg: Config,
    run_id: str,
    node_id: str,
    *,
    tags: list[str] | None = None,
    note: str | None = None,
    collection: str | None = None,
) -> dict[str, Any]:
    """Stage tags / note / collection on a queue row; write live when already in library."""
    if not valid_run_id(run_id):
        raise CitationGraphError("Unknown run.")
    try:
        dest, rows = load_queue(cfg.state_dir, run_id)
    except FileNotFoundError as exc:
        raise CitationGraphError("No queue for that run.") from exc
    row = _find_row(rows, node_id)
    op = dict(row.operator or {})
    if tags is not None:
        op["tags"] = clip_tags(tags)
    if note is not None:
        text = str(note).strip()
        if len(text) > 4000:
            text = text[:4000]
        op["note"] = text
    if collection is not None:
        coll = str(collection).strip()
        op["collection"] = safe_collection(coll, coll or "Inbox") if coll else ""
    row.operator = op or None
    key = item_key_of(row)
    if key and (tags is not None or note is not None or collection is not None):
        _apply_live_operator(cfg, key, op)
    _rewrite_queue(dest, rows)
    graph = _rebuild_graph(cfg, rows, run_id)
    write_graph_file(dest, graph)
    return graph


def _apply_live_operator(cfg: Config, item_key: str, op: dict[str, Any]) -> None:
    """Push staged operator fields onto an existing library item (add, not move)."""
    from ..library import get_backend
    from ..notehtml import wrap

    try:
        backend = get_backend(cfg)
    except Exception as exc:
        raise CitationGraphError("Library is not reachable. Check doctor.") from exc
    try:
        coll = str(op.get("collection") or "").strip()
        if coll:
            resolved = backend.ensure_collection_path(coll)
            backend.add_to_collection(item_key, resolved)
        note = str(op.get("note") or "").strip()
        if note:
            body = wrap(
                f"<p>{note}</p>",
                note_type="map",
                verb="discover-map",
            )
            backend.create_or_update_note(item_key, body, "paperful:map")
        tags = clip_tags(op.get("tags") or [])
        if tags:
            adder = getattr(backend, "add_tags", None)
            if adder is not None:
                adder(item_key, tags)
            else:
                # Best-effort: many backends only set tags at create time.
                pass
    except LibraryError as exc:
        raise CitationGraphError(str(exc) or "Could not update the library item.") from exc


def add_one_to_library(
    cfg: Config,
    run_id: str,
    node_id: str,
    *,
    collection: str,
) -> dict[str, Any]:
    """Keep + create one candidate parent in the library, then refresh the map."""
    from ..library import get_backend
    from .ingest import create_new

    if not valid_run_id(run_id):
        raise CitationGraphError("Unknown run.")
    try:
        dest, rows = load_queue(cfg.state_dir, run_id)
    except FileNotFoundError as exc:
        raise CitationGraphError("No queue for that run.") from exc
    row = _find_row(rows, node_id)
    if row.status == "exists" or row.exists_match:
        raise CitationGraphError("That paper is already in your library.")
    if row.status != "new":
        raise CitationGraphError("Only new candidates can be added from the map.")
    row.keep = True
    op = row.operator or {}
    target = str(op.get("collection") or "").strip() or collection.strip()
    if not target:
        raise CitationGraphError("Set a collection chip (or stage a collection on this paper).")
    extra = list(op.get("tags") or [])
    try:
        backend = get_backend(cfg)
    except Exception as exc:
        raise CitationGraphError("Library is not reachable. Check doctor.") from exc
    items, counts = create_new(
        backend,
        [row],
        target,
        extra_tags=extra,
        note_provenance=True,
        operator_note=str(op.get("note") or ""),
    )
    if counts.get("failed"):
        raise CitationGraphError(row.why or "Could not create that item.")
    if items:
        key = items[0].key
        row.status = "exists"
        row.exists_match = {"item_key": key, "doi": str(row.ids.get("doi") or "")}
    _rewrite_queue(dest, rows)
    graph = _rebuild_graph(cfg, rows, run_id)
    write_graph_file(dest, graph)
    return {
        "graph": graph,
        "item_key": (items[0].key if items else ""),
        "auto_search": bool(getattr(cfg, "ui_citation_map_auto_search", False)),
    }


def remove_from_library(
    cfg: Config,
    run_id: str,
    node_id: str,
    *,
    collection: str = "",
) -> dict[str, Any]:
    """Trash the item (default) or remove it from the current collection only."""
    from ..library import get_backend

    if not valid_run_id(run_id):
        raise CitationGraphError("Unknown run.")
    try:
        dest, rows = load_queue(cfg.state_dir, run_id)
    except FileNotFoundError as exc:
        raise CitationGraphError("No queue for that run.") from exc
    row = _find_row(rows, node_id)
    match = row.exists_match or {}
    key = str(match.get("item_key") or "").strip()
    if not key:
        raise CitationGraphError("No library item key for that paper.")
    mode = (getattr(cfg, "ui_citation_map_remove", "trash") or "trash").strip().lower()
    if mode == "remove_from_collection":
        raise CitationGraphError(
            "Remove-from-collection is not available yet; use trash, or change "
            "[ui].citation_map_remove back to trash."
        )
    try:
        backend = get_backend(cfg)
    except Exception as exc:
        raise CitationGraphError("Library is not reachable. Check doctor.") from exc
    try:
        backend.trash_item(key)
    except LibraryError as exc:
        raise CitationGraphError(str(exc) or "Could not trash that item.") from exc
    row.status = "new"
    row.exists_match = None
    _rewrite_queue(dest, rows)
    graph = _rebuild_graph(cfg, rows, run_id)
    write_graph_file(dest, graph)
    return graph


def find_pdf_for_key(cfg: Config, item_key: str, *, collection: str) -> None:
    """Fetch PDF for one library item (Wanted Grab path, one key)."""
    from io import StringIO

    from rich.console import Console

    from ..run_cmd import run_fetch

    key = (item_key or "").strip()
    if not key:
        raise CitationGraphError("Missing item key.")
    auto_attach = (getattr(cfg, "ui_attach_mode", "manual") or "manual") == "auto"
    console = Console(file=StringIO(), highlight=False, width=120)
    run_fetch(
        console,
        cfg,
        collection=[collection] if collection else [],
        library=not collection,
        dry_run=False,
        year_from=None,
        year_to=None,
        item_type=[],
        limit=None,
        no_attach=not auto_attach,
        force_attach=auto_attach,
        retry_failed=None,
        try_all=None,
        sources=None,
        preset="oa",
        scihub=None,
        relogin=False,
        browser_agent=None,
        upgrade_linked=None,
        want_snapshot_upgrade=False,
        strict_pdf_doi=None,
        handoff=None,
        include_doi_tabs=False,
        downloads_dir=None,
        re_request=False,
        json_out=True,
        item_keys=[key],
    )


def item_key_of(row: Candidate) -> str:
    match = row.exists_match or {}
    return str(match.get("item_key") or "").strip()


def has_pdf_for(out_dir: Path | None, item_key: str) -> bool | None:
    if not out_dir or not item_key:
        return None
    try:
        return pdf_for_key(out_dir, item_key) is not None
    except Exception:
        return None
