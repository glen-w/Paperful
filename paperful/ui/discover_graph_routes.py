"""Workbench HTTP routes (Discover citation graph)."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from . import jobs
from .context import UiContext
from .prefs import prefs_from_request


def _graph_overlay_context(
    ui: UiContext, watch_name: str, compare_run_id: str
) -> tuple[set[str] | None, set[str] | None]:
    from ..snowball.citation_graph import valid_run_id
    from ..snowball.queue import load_queue
    from ..snowball.watch import load_seen

    watch_seen: set[str] | None = None
    compare_ids: set[str] | None = None
    if watch_name.strip():
        try:
            watch_seen = load_seen(ui.cfg, watch_name.strip())
        except Exception:
            watch_seen = set()
    if compare_run_id.strip() and valid_run_id(compare_run_id.strip()):
        try:
            _, rows = load_queue(ui.cfg.state_dir, compare_run_id.strip())
            compare_ids = {row.identity for row in rows}
        except FileNotFoundError:
            compare_ids = set()
    return (watch_seen, compare_ids)


def handle_discover_graph(
    ui: UiContext, run_id: str = "", watch_name: str = "", compare_run: str = ""
) -> JSONResponse:
    from ..snowball.citation_graph import CitationGraphError, graph_for_run

    watch_seen, compare_ids = _graph_overlay_context(ui, watch_name, compare_run)
    try:
        graph = graph_for_run(
            ui.cfg.state_dir,
            run_id,
            watch_seen=watch_seen,
            compare_ids=compare_ids,
            map_categories=ui.cfg.snowball_map_categories,
            map_category_defs=ui.cfg.snowball_map_category_defs,
            out_dir=ui.cfg.out_dir,
        )
    except CitationGraphError as exc:
        status = 404 if "queue" in str(exc).lower() else 400
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)
    return JSONResponse(graph)


def handle_discover_graph_meta(ui: UiContext) -> JSONResponse:
    from ..snowball.graph_library import graph_meta

    return JSONResponse(graph_meta(ui.cfg))


async def handle_discover_graph_annotate(
    ui: UiContext, request: Request
) -> JSONResponse:
    from ..snowball.citation_graph import CitationGraphError
    from ..snowball.graph_library import annotate_queue

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        graph = annotate_queue(
            ui.cfg,
            str(body.get("run_id") or ""),
            str(body.get("node_id") or ""),
            tags=body.get("tags") if isinstance(body.get("tags"), list) else None,
            note=None if body.get("note") is None else str(body.get("note")),
            collection=None
            if body.get("collection") is None
            else str(body.get("collection")),
        )
    except CitationGraphError as exc:
        status = 404 if "queue" in str(exc).lower() else 400
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)
    return JSONResponse({"ok": True, "graph": graph})


async def handle_discover_graph_add(ui: UiContext, request: Request) -> JSONResponse:
    from ..snowball.citation_graph import CitationGraphError
    from ..snowball.graph_library import add_one_to_library, find_pdf_for_key

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    prefs = prefs_from_request(request)
    collection = str(body.get("collection") or prefs.collection or "").strip()
    try:
        result = add_one_to_library(
            ui.cfg,
            str(body.get("run_id") or ""),
            str(body.get("node_id") or ""),
            collection=collection,
        )
    except CitationGraphError as exc:
        status = 404 if "queue" in str(exc).lower() else 400
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)
    searched = False
    search_error = ""
    if result.get("auto_search") and result.get("item_key"):
        try:
            find_pdf_for_key(ui.cfg, str(result["item_key"]), collection=collection)
            searched = True
        except CitationGraphError as exc:
            search_error = str(exc)
    return JSONResponse(
        {
            "ok": True,
            "graph": result["graph"],
            "item_key": result.get("item_key"),
            "searched": searched,
            "search_error": search_error,
        }
    )


async def handle_discover_graph_find_pdf(
    ui: UiContext, request: Request
) -> JSONResponse:
    from ..snowball.citation_graph import CitationGraphError, graph_for_run
    from ..snowball.graph_library import find_pdf_for_key
    from ..snowball.queue import load_queue

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    run_id = str(body.get("run_id") or "")
    node_id = str(body.get("node_id") or "")
    item_key = str(body.get("item_key") or "").strip()
    prefs = prefs_from_request(request)
    collection = str(body.get("collection") or prefs.collection or "").strip()
    if not item_key and run_id and node_id:
        try:
            _, rows = load_queue(ui.cfg.state_dir, run_id)
            row = next((r for r in rows if r.identity == node_id), None)
            if row and row.exists_match:
                item_key = str(row.exists_match.get("item_key") or "")
        except FileNotFoundError:
            return JSONResponse(
                {"ok": False, "error": "No queue for that run."}, status_code=404
            )
    try:
        find_pdf_for_key(ui.cfg, item_key, collection=collection)
        graph = (
            graph_for_run(
                ui.cfg.state_dir,
                run_id,
                map_categories=ui.cfg.snowball_map_categories,
                map_category_defs=ui.cfg.snowball_map_category_defs,
                out_dir=ui.cfg.out_dir,
            )
            if run_id
            else {}
        )
    except CitationGraphError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "graph": graph, "item_key": item_key})


async def handle_discover_graph_remove(ui: UiContext, request: Request) -> JSONResponse:
    from ..snowball.citation_graph import CitationGraphError
    from ..snowball.graph_library import remove_from_library

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    prefs = prefs_from_request(request)
    collection = str(body.get("collection") or prefs.collection or "").strip()
    try:
        graph = remove_from_library(
            ui.cfg,
            str(body.get("run_id") or ""),
            str(body.get("node_id") or ""),
            collection=collection,
        )
    except CitationGraphError as exc:
        status = 404 if "queue" in str(exc).lower() else 400
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)
    return JSONResponse({"ok": True, "graph": graph})


async def handle_discover_graph_repair(ui: UiContext, request: Request) -> JSONResponse:
    from ..snowball.citation_graph import CitationGraphError, repair_queue_links
    from ..snowball.command import _openalex_client
    from ..snowball.openalex import OpenAlexBudgetExceeded

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    run_id = str(body.get("run_id") or "")
    try:
        graph = repair_queue_links(
            ui.cfg.state_dir,
            run_id,
            _openalex_client(ui.cfg),
            map_categories=ui.cfg.snowball_map_categories,
            map_category_defs=ui.cfg.snowball_map_category_defs,
            out_dir=ui.cfg.out_dir,
        )
    except CitationGraphError as exc:
        status = 404 if "queue" in str(exc).lower() else 400
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)
    except OpenAlexBudgetExceeded as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=429)
    return JSONResponse(graph)


async def handle_discover_graph_halo(ui: UiContext, request: Request) -> JSONResponse:
    from ..identity import LibraryFingerprint
    from ..mirror import items_in_mirror
    from ..snowball.citation_graph import CitationGraphError, library_halo
    from ..snowball.command import _openalex_client
    from ..snowball.openalex import OpenAlexBudgetExceeded
    from ..snowball.queue import load_queue

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    run_id = str(body.get("run_id") or "")
    node_id = str(body.get("node_id") or "")
    try:
        dest, rows = load_queue(ui.cfg.state_dir, run_id)
    except FileNotFoundError:
        return JSONResponse(
            {"ok": False, "error": "No queue for that run."}, status_code=404
        )
    target = next((row for row in rows if row.identity == node_id), None)
    if target is None:
        return JSONResponse(
            {"ok": False, "error": "That paper is not in this queue."}, status_code=400
        )
    items = items_in_mirror(ui.cfg.out_dir)
    fp = LibraryFingerprint.from_items(items)
    library_dois = set(fp.by_doi.keys())
    try:
        overlay = library_halo(_openalex_client(ui.cfg), target, library_dois)
    except CitationGraphError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except OpenAlexBudgetExceeded as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=429)
    return JSONResponse({"ok": True, **overlay})


async def handle_discover_graph_expand(ui: UiContext, request: Request) -> JSONResponse:
    from ..snowball.citation_graph import CitationGraphError, expand_queue
    from ..snowball.command import _openalex_client
    from ..snowball.openalex import OpenAlexBudgetExceeded

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    run_id = str(body.get("run_id") or "")
    node_id = str(body.get("node_id") or "")
    direction = str(body.get("direction") or "both")
    try:
        graph = expand_queue(
            ui.cfg.state_dir,
            run_id,
            node_id,
            direction,
            _openalex_client(ui.cfg),
            map_categories=ui.cfg.snowball_map_categories,
            map_category_defs=ui.cfg.snowball_map_category_defs,
        )
    except CitationGraphError as exc:
        status = 404 if "queue" in str(exc).lower() else 400
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)
    except OpenAlexBudgetExceeded as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=429)
    return JSONResponse(graph)


