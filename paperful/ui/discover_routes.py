"""Workbench HTTP routes (discover)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from fastapi import Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from ..agent_ops import last_run
from . import app as _ui_app
from ..config import Config
from . import commands, jobs
from .context import UiContext
from .doctor_steps import next_step
from .pages import (
    ASK_ERROR_MESSAGES,
    DEST_OPTIONS,
    SUMMARIZE_ORDERS,
    ask_page_flags,
    authorwatch_inbox_rows,
    authorwatch_lists,
    authorwatch_people_rows,
    authorwatch_suggestion_rows,
    briefs_page_flags,
    briefs_synth_form,
    dest_for_form,
    dest_options,
    focus_options,
    following_lists,
    last_ask_result,
    last_job_result,
    job_view,
    WANTED_FILTER_LABELS,
    WANTED_ORDER_LABELS,
    library_items_page,
    library_page_from_request,
    library_page_size_options,
    library_per_page_from_request,
    nest_collection_rows,
    paginate_rows,
    pagination_meta,
    resolve_discover_tab,
    wanted_filter_from_request,
    wanted_items_page,
    wanted_order_from_request,
    wanted_query_from_request,
    list_ask_packs,
    list_answered_packs,
    list_html_stems,
    list_recent_summaries,
    list_snowball_profiles,
    summary_meta,
    list_threads,
    newest_snowball_queue,
    snowball_stop_view,
    command_by_id,
    repair_queues,
    safe_child,
    snowball_deferred_run_id,
    thread_for_display,
    wanted_rows,
    MIRROR_VERBS,
)
from .rag_form import (
    list_saved_prompts,
    parse_rag_scope,
    read_questions_upload,
    resolve_prompt_from_form,
    save_prompt_as,
    scope_has_target,
)
from .snowball_form import parse_discover_topic
from .prefs import (
    COOKIE_ADVANCED,
    COOKIE_COLLECTION,
    COOKIE_LIBRARY_PER_PAGE,
    COOKIE_PRESET,
    prefs_from_request,
    set_cookie,
)
from .app import (
    _health_status,
    _health_label,
    _health_tooltip,
    _trust_line,
    _load_wanted,
    _patch_config_field,
    _patch_section_assignment,
)


def _last_review_token(ui: UiContext, verb: str) -> str:
    for rec in commands.list_commands(ui.cfg, limit=20):
        if rec.get("verb") == verb and rec.get("review_token"):
            return str(rec["review_token"])
    return ""


def _safe_aw_suggestions(ui: UiContext, active: str) -> list[dict[str, Any]]:
    if not active:
        return []
    try:
        return authorwatch_suggestion_rows(ui.cfg, active)
    except Exception:
        return []


def _discover_page(
    ui: UiContext,
    request: Request,
    *,
    list_name: str = "",
    error: str = "",
    run: str = "",
    watch_name: str = "",
    compare_run: str = "",
    tab: str | None = None,
    explore_picks: list[dict[str, Any]] | None = None,
    explore_query: str = "",
    note: Any = ...,
    status_code: int = 200,
) -> HTMLResponse:
    prefs = prefs_from_request(request)
    run_id, all_candidates = newest_snowball_queue(ui.cfg)
    stop_pending, stop_note = snowball_stop_view(ui.cfg, run_id)
    list_requested = bool((list_name or "").strip())
    active_list = (list_name or "followed").strip()
    following = following_lists(ui.cfg)
    picks = explore_picks or []
    tab_name = resolve_discover_tab(
        tab if tab is not None else request.query_params.get("tab"),
        advanced=prefs.advanced,
        has_candidates=bool(all_candidates),
        has_following=bool(following),
        explore_picks=bool(picks),
        list_requested=list_requested,
    )
    per_page = library_per_page_from_request(request, ui.cfg)
    persist_per_page = request.query_params.get("per_page") is not None
    page = library_page_from_request(request)
    candidates, queue_total, page, queue_page_count = paginate_rows(
        all_candidates, page=page, per_page=per_page
    )
    page_sizes = library_page_size_options(ui.cfg)
    queue_pagination = pagination_meta(
        page=page,
        per_page=per_page,
        page_count=queue_page_count,
        total=queue_total,
        page_sizes=page_sizes,
    )

    def _discover_qs(
        *,
        page_no: int | None = None,
        with_per_page: bool = False,
        tab_override: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "tab": tab_override or tab_name,
            "list_name": list_name if list_requested else "",
            "watch_name": (watch_name or "").strip(),
            "compare_run": (compare_run or "").strip(),
            "run": (run or "").strip(),
            "error": error,
        }
        if with_per_page or persist_per_page:
            params["per_page"] = per_page
        if page_no is not None and int(page_no) > 1:
            params["page"] = page_no
        return params

    queue_pagination.update(
        {
            "prev_url": ui.page_url(
                "/discover", **_discover_qs(page_no=page - 1, with_per_page=True)
            )
            if page > 1
            else "",
            "next_url": ui.page_url(
                "/discover", **_discover_qs(page_no=page + 1, with_per_page=True)
            )
            if page < queue_page_count
            else "",
            "tab_urls": {
                name: ui.page_url(
                    "/discover", **_discover_qs(page_no=1, tab_override=name)
                )
                for name in (
                    ("explore", "topic", "grow", "people", "queue", "following")
                    if prefs.advanced
                    else ("explore", "topic", "people", "queue", "following")
                )
            },
        }
    )
    people: list[dict[str, Any]] = []
    if active_list and tab_name == "people":
        try:
            people = authorwatch_people_rows(ui.cfg, active_list)
        except Exception:
            people = []
    if note is ...:
        note = (
            last_job_result(ui.cfg, "snowball_briefing")
            or last_job_result(ui.cfg, "snowball_digest")
            or last_job_result(ui.cfg, "authorwatch_briefing")
            or last_job_result(ui.cfg, "refs_gap")
            or last_job_result(ui.cfg, "authors")
        )
    return ui.templates.TemplateResponse(
        request,
        "discover.html",
        ui.ctx(
            request,
            "discover",
            tab=tab_name,
            run_id=run_id,
            candidates=candidates,
            stop_pending=stop_pending,
            stop_note=stop_note,
            following=following,
            inbox=authorwatch_inbox_rows(ui.cfg) if tab_name == "people" else [],
            aw_lists=authorwatch_lists(ui.cfg) if tab_name == "people" else [],
            aw_list=active_list,
            aw_people=people,
            aw_suggestions=_safe_aw_suggestions(ui, active_list)
            if tab_name == "people"
            else [],
            profiles=list_snowball_profiles(ui.cfg),
            deferred_run=snowball_deferred_run_id(ui.cfg),
            snowball_token=_last_review_token(ui, "snowball_apply"),
            aw_token=_last_review_token(ui, "authorwatch_apply"),
            watch_token=_last_review_token(ui, "watch_apply"),
            ingest_token=_last_review_token(ui, "ingest_dois"),
            note=note,
            job=job_view(command_by_id(ui.cfg, (run or "").strip())),
            poll_run=(run or "").strip(),
            error=error,
            map_watch_name=(watch_name or "").strip(),
            map_compare_run=(compare_run or "").strip(),
            explore_picks=picks,
            explore_query=explore_query,
            queue_pagination=queue_pagination,
            coauthor_network=ui.cfg.ui_coauthor_network,
        ),
        status_code=status_code,
    )


def handle_page_discover(
    ui: UiContext,
    request: Request,
    list_name: str = "",
    error: str = "",
    run: str = "",
    watch_name: str = "",
    compare_run: str = "",
    tab: str = "",
) -> HTMLResponse:
    return _discover_page(
        ui,
        request,
        list_name=list_name,
        error=error,
        run=run,
        watch_name=watch_name,
        compare_run=compare_run,
        tab=tab or None,
    )


async def handle_discover_explore(ui: UiContext, request: Request):
    from ..snowball.citation_graph import CitationGraphError
    from ..snowball.command import _openalex_client
    from ..snowball.explore import ExploreAmbiguous, start_explore
    from ..snowball.openalex import OpenAlexBudgetExceeded

    form = await request.form()
    query = str(form.get("query") or "").strip()
    node_id = str(form.get("node_id") or "").strip()
    try:
        start_explore(
            ui.cfg,
            _openalex_client(ui.cfg),
            query=query,
            node_id=node_id,
            map_categories=ui.cfg.snowball_map_categories,
            map_category_defs=ui.cfg.snowball_map_category_defs,
        )
    except ExploreAmbiguous as exc:
        picks = [
            {
                "id": p.id,
                "title": p.title,
                "year": p.year,
                "cited_by_count": p.cited_by_count,
                "doi": p.doi,
            }
            for p in exc.picks
        ]
        return _discover_page(
            ui,
            request,
            tab="explore",
            explore_picks=picks,
            explore_query=query,
            note=None,
        )
    except CitationGraphError as exc:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="explore", error=str(exc)[:120]),
            status_code=303,
        )
    except OpenAlexBudgetExceeded as exc:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="explore", error=str(exc)[:120]),
            status_code=303,
        )
    return RedirectResponse(url=ui.page_url("/discover", tab="queue"), status_code=303)


async def handle_discover_topic(ui: UiContext, request: Request) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    payload = parse_discover_topic(form, advanced=prefs.advanced)

    def work(cmd_id: str) -> None:
        jobs.snowball_run(ui.cfg, cmd_id, payload=payload, collection=prefs.collection)

    cmd_id = commands.enqueue(ui.cfg, f"snowball_{payload.kind}", work)
    return ui.after_job("/discover", cmd_id, tab="queue")


async def handle_discover_profile_save(
    ui: UiContext, request: Request
) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    name = str(form.get("profile_name") or "").strip()
    if not name:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="topic", error="profile"), status_code=303
        )
    from .snowball_form import profile_body_from_payload
    from ..snowball.profile import save_profile
    from ..snowball.command import SnowballError

    payload = parse_discover_topic(form, advanced=True)
    try:
        body = profile_body_from_payload(payload, collection=prefs.collection)
        save_profile(ui.cfg, name, body, force=form.get("force") == "1")
    except (SnowballError, ValueError) as exc:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="topic", error=str(exc)[:80]),
            status_code=303,
        )
    return RedirectResponse(url=ui.page_url("/discover", tab="topic"), status_code=303)


async def handle_discover_refs_gap(ui: UiContext, request: Request) -> RedirectResponse:
    prefs = prefs_from_request(request)

    def work(cmd_id: str) -> None:
        from ..agent_ops import run_refs_gap

        result = run_refs_gap(ui.cfg, prefs.collection)
        rec = commands.read_command(ui.cfg, cmd_id) or {}
        rec["result"] = result
        commands.write_command(ui.cfg, rec)

    cmd_id = commands.enqueue(ui.cfg, "refs_gap", work)
    return ui.after_job("/discover", cmd_id, tab="grow")


async def handle_discover_ingest_preview(
    ui: UiContext, request: Request
) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    pack_path = str(form.get("pack_path") or "").strip()
    upload = form.get("file")
    dest = ui.cfg.state_dir / "gui" / "uploads"
    dest.mkdir(parents=True, exist_ok=True)
    source_path = ""
    if upload is not None and getattr(upload, "filename", None):
        path = dest / Path(str(upload.filename)).name
        path.write_bytes(await upload.read())
        source_path = str(path)
    elif pack_path:
        source_path = pack_path

    def work(cmd_id: str) -> None:
        from . import discover_jobs

        discover_jobs.ingest_preview(
            ui.cfg, cmd_id, collection=prefs.collection, source_path=source_path
        )

    cmd_id = commands.enqueue(ui.cfg, "ingest_dois", work)
    return ui.after_job("/discover", cmd_id, tab="grow")


async def handle_discover_ingest_apply(ui: UiContext, request: Request):
    prefs = prefs_from_request(request)
    form = await request.form()
    from . import discover_jobs

    token = str(form.get("review_token") or "") or _last_review_token(ui, "ingest_dois")
    ok, msg = discover_jobs.ingest_apply(
        ui.cfg, token=token, collection=prefs.collection
    )
    if not ok:
        return JSONResponse({"ok": False, "error": msg}, status_code=409)
    return RedirectResponse(url=ui.page_url("/discover", tab="grow"), status_code=303)


async def handle_discover_authors(ui: UiContext, request: Request) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    try:
        min_count = int(form.get("min_count") or 2)
        max_authors = int(form.get("max_authors") or 15)
    except ValueError:
        return RedirectResponse(
            url=ui.page_url(
                "/discover", tab="grow", error="Counts must be whole numbers."
            ),
            status_code=303,
        )

    def work(cmd_id: str) -> None:
        from rich.console import Console
        from ..authors_cmd import run_authors

        run_authors(
            Console(quiet=True, file=None),
            collection=[prefs.collection] if prefs.collection else [],
            library=not bool(prefs.collection),
            year_from=None,
            year_to=None,
            item_type=[],
            min_count=min_count,
            max_authors=max_authors,
            apply=form.get("apply") == "1",
            profile=None,
            run_config=None,
            config=ui.cfg.config_path,
            fmt="json",
        )
        rec = commands.read_command(ui.cfg, cmd_id) or {}
        rec["result"] = {"apply": form.get("apply") == "1"}
        commands.write_command(ui.cfg, rec)

    cmd_id = commands.enqueue(ui.cfg, "authors", work)
    return ui.after_job("/discover", cmd_id, tab="grow")


async def handle_discover_packs_promote(
    ui: UiContext, request: Request
) -> RedirectResponse:
    form = await request.form()
    slug = str(form.get("slug") or "").strip()
    if not slug:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="grow", error="slug"), status_code=303
        )

    def work(cmd_id: str) -> None:
        from ..snowball.preflight import promote_pack

        path = promote_pack(ui.cfg, slug)
        rec = commands.read_command(ui.cfg, cmd_id) or {}
        rec["result"] = {"path": str(path)}
        commands.write_command(ui.cfg, rec)

    cmd_id = commands.enqueue(ui.cfg, "packs_promote", work)
    return ui.after_job("/discover", cmd_id, tab="grow")


async def handle_discover_follow(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    orcid = str(form.get("orcid") or "").strip()
    list_name = str(form.get("list_name") or "followed").strip()
    backfill = str(form.get("backfill_from") or "").strip() or None
    if not orcid:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="people", error="orcid"), status_code=303
        )

    def work(cmd_id: str) -> None:
        jobs.follow_person(
            ui.cfg, cmd_id, orcid=orcid, list_name=list_name, backfill_from=backfill
        )

    cmd_id = commands.enqueue(ui.cfg, "authorwatch_run", work)
    return ui.after_job("/discover", cmd_id, tab="people", list_name=list_name)


async def handle_discover_apply_preview(
    ui: UiContext, request: Request
) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    kind = str(form.get("kind") or "snowball")
    run_id = str(form.get("run_id") or "")
    list_name = str(form.get("list_name") or "followed")

    def work(cmd_id: str) -> None:
        jobs.discover_apply_preview(
            ui.cfg,
            cmd_id,
            kind=kind,
            run_id=run_id,
            list_name=list_name,
            collection=prefs.collection,
        )

    if kind == "authorwatch":
        verb = "authorwatch_apply"
        tab = "people"
    elif kind in {"watch", "topic"}:
        verb = "watch_apply"
        tab = "following"
    else:
        verb = "snowball_apply"
        tab = "queue"
    cmd_id = commands.enqueue(ui.cfg, verb, work)
    return ui.after_job(
        "/discover", cmd_id, tab=tab, list_name=list_name if tab == "people" else ""
    )


async def handle_discover_apply(ui: UiContext, request: Request):
    prefs = prefs_from_request(request)
    form = await request.form()
    kind = str(form.get("kind") or "snowball")
    run_id = str(form.get("run_id") or "")
    list_name = str(form.get("list_name") or "followed")
    token = str(form.get("review_token") or "")
    if not token:
        if kind == "authorwatch":
            token = _last_review_token(ui, "authorwatch_apply")
        elif kind in {"watch", "topic"}:
            token = _last_review_token(ui, "watch_apply")
        else:
            token = _last_review_token(ui, "snowball_apply")
    ok, msg = jobs.discover_apply_consume(
        ui.cfg,
        token=token,
        kind=kind,
        run_id=run_id,
        list_name=list_name,
        collection=prefs.collection,
    )
    if not ok:
        return JSONResponse({"ok": False, "error": msg}, status_code=409)
    return RedirectResponse(url="/wanted", status_code=303)


async def handle_discover_check(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    kind = str(form.get("kind") or "")
    name = str(form.get("name") or "")

    def work(cmd_id: str) -> None:
        if kind == "person":
            from ..authorwatch import run_list

            run_list(ui.cfg, name, console=jobs._quiet_console())
        elif kind == "topic":
            from ..snowball.watch import run_watch

            run_watch(ui.cfg, name, console=jobs._quiet_console())

    cmd_id = commands.enqueue(ui.cfg, "check_again", work)
    return ui.after_job("/discover", cmd_id, tab="following")


async def handle_discover_keep(ui: UiContext, request: Request):
    from ..snowball.citation_graph import CitationGraphError, graph_for_run

    form = await request.form()
    run_id = str(form.get("run_id") or "")
    doi = str(form.get("doi") or "")
    keep = str(form.get("keep") or "1") == "1"
    page_raw = str(form.get("page") or "").strip()
    page = int(page_raw) if page_raw.isdigit() else 1
    wants_json = str(form.get("format") or "") == "json"
    accept = (request.headers.get("accept") or "").lower()
    if "application/json" in accept:
        wants_json = True
    if run_id and doi:
        jobs.set_snowball_keep(ui.cfg, run_id, [doi], keep)
    if wants_json:
        if not run_id:
            return JSONResponse({"ok": False, "error": "Missing run."}, status_code=400)
        try:
            graph = graph_for_run(
                ui.cfg.state_dir,
                run_id,
                map_categories=ui.cfg.snowball_map_categories,
                map_category_defs=ui.cfg.snowball_map_category_defs,
                out_dir=ui.cfg.out_dir,
            )
        except CitationGraphError as exc:
            status = 404 if "queue" in str(exc).lower() else 400
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)
        return JSONResponse({"ok": True, "graph": graph, "doi": doi, "keep": keep})
    return RedirectResponse(
        url=ui.page_url("/discover", tab="queue", page=page if page > 1 else ""),
        status_code=303,
    )


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


async def handle_discover_watch(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("watch_name") or "topic-watch").strip()
    profile = str(form.get("profile") or "").strip()
    if not profile:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="queue", error="watch"), status_code=303
        )
    from ..snowball.watch import save_watch

    try:
        save_watch(ui.cfg, name, profile)
    except Exception:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="queue", error="watch"), status_code=303
        )
    return RedirectResponse(
        url=ui.page_url("/discover", tab="following"), status_code=303
    )


async def handle_discover_continue(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    run_id = str(form.get("run_id") or "").strip()
    if not run_id:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="queue"), status_code=303
        )

    def work(cmd_id: str) -> None:
        from ..snowball.command import SnowballError, run_continue

        try:
            run_continue(ui.cfg, run_id, console=jobs._quiet_console())
        except SnowballError as exc:
            rec = commands.read_command(ui.cfg, cmd_id) or {}
            rec["status"] = "failed"
            rec["error"] = str(exc)
            commands.write_command(ui.cfg, rec)
            raise

    cmd_id = commands.enqueue(ui.cfg, "snowball_continue", work)
    return ui.after_job("/discover", cmd_id, tab="queue")


async def handle_discover_resume(ui: UiContext, request: Request) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    run_id = str(form.get("run_id") or snowball_deferred_run_id(ui.cfg)).strip()
    if not run_id:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="topic"), status_code=303
        )

    def work(cmd_id: str) -> None:
        from ..snowball.command import SnowballRequest, run_resume

        req = SnowballRequest(gate="dry-run", collection=prefs.collection or "")
        run_resume(ui.cfg, run_id, req, console=jobs._quiet_console())

    cmd_id = commands.enqueue(ui.cfg, "snowball_resume", work)
    return ui.after_job("/discover", cmd_id, tab="queue")


async def handle_discover_profile_run(
    ui: UiContext, request: Request
) -> RedirectResponse:
    form = await request.form()
    profile = str(form.get("profile") or "").strip()
    if not profile:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="topic"), status_code=303
        )

    def work(cmd_id: str) -> None:
        from ..snowball.command import (
            SnowballError,
            run_collection,
            run_doi,
            run_hybrid,
            run_orcid,
            run_search,
        )
        from ..snowball.profile import (
            composed_query_from_profile,
            load_profile,
            orcids_from_profile,
            request_from_profile,
        )

        console = jobs._quiet_console()
        raw = load_profile(ui.cfg, profile)
        req = request_from_profile(raw, ui.cfg)
        mode = str(raw.get("mode") or "")
        if mode == "search":
            run_search(ui.cfg, composed_query_from_profile(raw), req, console=console)
        elif mode == "hybrid":
            run_hybrid(ui.cfg, composed_query_from_profile(raw), req, console=console)
        elif mode == "doi":
            dois = [str(x) for x in raw.get("dois") or []]
            run_doi(ui.cfg, dois, req, console=console)
        elif mode == "orcid":
            run_orcid(ui.cfg, orcids_from_profile(raw), req, console=console)
        elif mode == "collection":
            seed = str(
                raw.get("seed_collection") or raw.get("collection") or ""
            ).strip()
            run_collection(ui.cfg, seed, req, console=console)
        else:
            raise SnowballError(f"Profile {profile!r} has unknown mode.")

    cmd_id = commands.enqueue(ui.cfg, "snowball_profile", work)
    return ui.after_job("/discover", cmd_id, tab="queue")


def _maybe_file_note(ui: UiContext, html: str, apply: bool, collection: str) -> str:
    if not apply:
        return ""
    from . import discover_jobs

    return discover_jobs.file_frontier_note(ui.cfg, html, collection)


async def handle_discover_briefing(ui: UiContext, request: Request) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    run_id = str(form.get("run_id") or "").strip()
    apply_note = form.get("apply") == "1"
    if not run_id:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="topic"), status_code=303
        )

    def work(cmd_id: str) -> None:
        from ..snowball.briefing import write_run_briefing

        briefing = write_run_briefing(ui.cfg, run_id)
        note_key = _maybe_file_note(ui, briefing.html, apply_note, prefs.collection)
        jobs._attach_result(
            ui.cfg,
            cmd_id,
            {
                "path": str(briefing.path),
                "markdown": briefing.markdown[:4000],
                "note_key": note_key,
            },
        )

    cmd_id = commands.enqueue(ui.cfg, "snowball_briefing", work)
    return ui.after_job("/discover", cmd_id, tab="queue")


async def handle_discover_digest(ui: UiContext, request: Request) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    run_id = str(form.get("run_id") or "").strip()
    apply_note = form.get("apply") == "1"
    if not run_id:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="topic"), status_code=303
        )

    def work(cmd_id: str) -> None:
        from ..snowball.digest import write_run_digest

        digest = write_run_digest(ui.cfg, run_id)
        note_key = _maybe_file_note(ui, digest.html, apply_note, prefs.collection)
        jobs._attach_result(
            ui.cfg,
            cmd_id,
            {
                "path": str(digest.path),
                "markdown": digest.markdown[:4000],
                "note_key": note_key,
            },
        )

    cmd_id = commands.enqueue(ui.cfg, "snowball_digest", work)
    return ui.after_job("/discover", cmd_id, tab="queue")


async def handle_discover_watch_briefing(
    ui: UiContext, request: Request
) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    name = str(form.get("name") or "").strip()
    apply_note = form.get("apply") == "1"
    if not name:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="following"), status_code=303
        )

    def work(cmd_id: str) -> None:
        from ..snowball.briefing import write_watch_briefing

        briefing = write_watch_briefing(ui.cfg, name)
        note_key = _maybe_file_note(ui, briefing.html, apply_note, prefs.collection)
        jobs._attach_result(
            ui.cfg,
            cmd_id,
            {
                "path": str(briefing.path),
                "markdown": briefing.markdown[:4000],
                "note_key": note_key,
            },
        )

    cmd_id = commands.enqueue(ui.cfg, "watch_briefing", work)
    return ui.after_job("/discover", cmd_id, tab="following")


async def handle_discover_watch_digest(
    ui: UiContext, request: Request
) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    name = str(form.get("name") or "").strip()
    apply_note = form.get("apply") == "1"
    if not name:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="following"), status_code=303
        )

    def work(cmd_id: str) -> None:
        from ..snowball.digest import write_watch_digest

        digest = write_watch_digest(ui.cfg, name)
        note_key = _maybe_file_note(ui, digest.html, apply_note, prefs.collection)
        jobs._attach_result(
            ui.cfg,
            cmd_id,
            {
                "path": str(digest.path),
                "markdown": digest.markdown[:4000],
                "note_key": note_key,
            },
        )

    cmd_id = commands.enqueue(ui.cfg, "watch_digest", work)
    return ui.after_job("/discover", cmd_id, tab="following")


async def handle_discover_aw_save(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("name") or "").strip()
    if not name:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="people"), status_code=303
        )
    from ..authorwatch import save_list

    save_list(ui.cfg, name)
    return RedirectResponse(
        url=ui.page_url("/discover", tab="people", list_name=name), status_code=303
    )


async def handle_discover_aw_add(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("list_name") or "followed").strip()
    orcid = str(form.get("orcid") or "").strip()
    display = str(form.get("display_name") or "").strip()
    affiliation = str(form.get("affiliation") or "").strip()
    from ..authorwatch import add_person

    add_person(
        ui.cfg, name, orcid=orcid, display_name=display, affiliation_host=affiliation
    )
    return RedirectResponse(
        url=ui.page_url("/discover", tab="people", list_name=name), status_code=303
    )


async def handle_discover_aw_remove(
    ui: UiContext, request: Request
) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("list_name") or "").strip()
    person_id = str(form.get("person_id") or "").strip()
    orcid = str(form.get("orcid") or "").strip()
    from ..authorwatch import remove_person

    remove_person(ui.cfg, name, orcid=orcid, person_id=person_id)
    return RedirectResponse(
        url=ui.page_url("/discover", tab="people", list_name=name), status_code=303
    )


async def handle_discover_aw_resolve(
    ui: UiContext, request: Request
) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("list_name") or "").strip()

    def work(_cmd_id: str) -> None:
        from ..authorwatch import resolve_people

        resolve_people(ui.cfg, name)

    cmd_id = commands.enqueue(ui.cfg, "authorwatch_resolve", work)
    return ui.after_job("/discover", cmd_id, tab="people", list_name=name)


async def handle_discover_aw_run(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("list_name") or "").strip()
    backfill = str(form.get("backfill_from") or "").strip() or None
    max_authors = form.get("max_authors")
    per_author = form.get("per_author_limit")
    try:
        max_authors_n = int(max_authors) if str(max_authors or "").strip() else None
        per_author_n = int(per_author) if str(per_author or "").strip() else None
    except ValueError:
        return RedirectResponse(
            url=ui.page_url(
                "/discover", error="Counts must be whole numbers.", list_name=name
            ),
            status_code=303,
        )

    def work(_cmd_id: str) -> None:
        from ..authorwatch import run_list

        kwargs: dict[str, Any] = {
            "console": jobs._quiet_console(),
            "backfill_from": backfill,
        }
        if max_authors_n is not None:
            kwargs["max_authors"] = max_authors_n
        if per_author_n is not None:
            kwargs["per_author_limit"] = per_author_n
        run_list(ui.cfg, name, **kwargs)

    cmd_id = commands.enqueue(ui.cfg, "authorwatch_run", work)
    return ui.after_job("/discover", cmd_id, tab="people", list_name=name)


async def handle_discover_aw_import(ui: UiContext, request: Request):
    form = await request.form()
    name = str(form.get("list_name") or "followed").strip()
    source = str(form.get("source") or "csv").strip().lower()
    upload = form.get("file")
    filename = str(getattr(upload, "filename", "") or "")
    if not filename or upload is None:
        return JSONResponse({"ok": False, "error": "file required"}, status_code=400)
    data = await upload.read()
    dest_dir = ui.cfg.state_dir / "gui" / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(filename).name
    dest.write_bytes(data)
    jobs.authorwatch_import(ui.cfg, list_name=name, path=dest, source=source)
    return RedirectResponse(
        url=ui.page_url("/discover", tab="people", list_name=name), status_code=303
    )


async def handle_discover_aw_suggest(
    ui: UiContext, request: Request
) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    name = str(form.get("list_name") or "").strip()
    method = str(form.get("method") or "corpus").strip()
    limit = int(str(form.get("limit") or "15") or "15")
    collection = str(form.get("collection") or prefs.collection or "").strip()

    def work(_cmd_id: str) -> None:
        jobs.authorwatch_suggest(
            ui.cfg, list_name=name, collection=collection, method=method, limit=limit
        )

    cmd_id = commands.enqueue(ui.cfg, "authorwatch_suggest", work)
    return ui.after_job("/discover", cmd_id, tab="people", list_name=name)


async def handle_discover_aw_accept(
    ui: UiContext, request: Request
) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("list_name") or "").strip()
    ids = [str(v) for v in form.getlist("suggestion_id")]
    seed_from = str(form.get("seed_from") or "").strip() or None

    def work(_cmd_id: str) -> None:
        jobs.authorwatch_accept(
            ui.cfg, list_name=name, suggestion_ids=ids, seed_from=seed_from
        )

    cmd_id = commands.enqueue(ui.cfg, "authorwatch_accept", work)
    return ui.after_job("/discover", cmd_id, tab="people", list_name=name)


async def handle_discover_aw_delete(
    ui: UiContext, request: Request
) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("list_name") or "").strip()
    from ..authorwatch import delete_list

    delete_list(ui.cfg, name, yes=True)
    return RedirectResponse(url=ui.page_url("/discover", tab="people"), status_code=303)


async def handle_discover_aw_edit(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("list_name") or "").strip()
    person_id = str(form.get("person_id") or "").strip()
    display = str(form.get("display_name") or "").strip()
    affiliation = str(form.get("affiliation") or "").strip()
    from ..authorwatch import update_person

    update_person(
        ui.cfg, name, person_id, display_name=display, affiliation_host=affiliation
    )
    return RedirectResponse(
        url=ui.page_url("/discover", tab="people", list_name=name), status_code=303
    )


async def handle_discover_aw_briefing(
    ui: UiContext, request: Request
) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("list_name") or "").strip()
    if not name:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="people"), status_code=303
        )

    def work(cmd_id: str) -> None:
        from ..authorwatch import write_briefing

        path = write_briefing(ui.cfg, name)
        jobs._attach_result(
            ui.cfg,
            cmd_id,
            {"path": str(path), "markdown": path.read_text(encoding="utf-8")[:4000]},
        )

    cmd_id = commands.enqueue(ui.cfg, "authorwatch_briefing", work)
    return ui.after_job("/discover", cmd_id, tab="people", list_name=name)


def handle_discover_network_meta(ui: UiContext) -> JSONResponse:
    from ..network.store import list_runs

    enabled = ui.cfg.ui_coauthor_network != "off"
    return JSONResponse(
        {
            "ok": True,
            "enabled": enabled,
            "runs": list_runs(ui.cfg) if enabled else [],
        }
    )


def handle_discover_network(
    ui: UiContext, run_id: str = "", phase: str = ""
) -> JSONResponse:
    from ..network.store import NetworkError, load_run

    if ui.cfg.ui_coauthor_network == "off":
        return JSONResponse({"ok": False, "error": "Co-author network is off."}, status_code=404)
    cleaned = (run_id or "").strip()
    if not cleaned:
        return JSONResponse({"ok": False, "error": "run_id required"}, status_code=400)
    try:
        bundle = load_run(ui.cfg, cleaned)
    except NetworkError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
    graph = bundle.get("graph") or {}
    metrics = bundle.get("metrics") or {}
    slug = (phase or "").strip()
    if slug:
        payload = (bundle.get("phases") or {}).get(slug) or {}
        if not payload:
            return JSONResponse(
                {"ok": False, "error": f"Phase {slug!r} is not in this run."},
                status_code=404,
            )
        graph = payload.get("graph") or graph
        metrics = payload.get("metrics") or metrics
    return JSONResponse(
        {
            "ok": True,
            "schema": bundle.get("schema"),
            "run_id": bundle.get("run_id"),
            "meta": bundle.get("meta") or {},
            "graph": graph,
            "metrics": metrics,
        }
    )


async def handle_discover_network_run(
    ui: UiContext, request: Request
) -> RedirectResponse:
    form = await request.form()
    orcid = str(form.get("orcid") or "").strip()
    phases = str(form.get("phases") or "bbnj").strip() or "bbnj"
    partition = str(form.get("partition") or "none").strip() or "none"
    try:
        max_works = int(str(form.get("max_works") or "500").strip() or "500")
        max_alters = int(str(form.get("max_alters") or "150").strip() or "150")
    except ValueError:
        return RedirectResponse(
            url=ui.page_url(
                "/discover", tab="people", error="Counts must be whole numbers."
            ),
            status_code=303,
        )
    if not orcid:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="people", error="ORCID is required."),
            status_code=303,
        )

    def work(cmd_id: str) -> None:
        from ..network.run import run_orcid
        from ..network.store import NetworkError

        try:
            bundle = run_orcid(
                ui.cfg,
                orcid,
                phases=phases,
                partition=partition,
                max_works=max_works,
                max_alters=max_alters,
            )
        except (NetworkError, ValueError) as exc:
            raise RuntimeError(str(exc)) from exc
        jobs._attach_result(
            ui.cfg,
            cmd_id,
            {
                "run_id": bundle.get("run_id"),
                "path": bundle.get("path"),
                "nodes": (bundle.get("meta") or {}).get("nodes"),
            },
        )

    cmd_id = commands.enqueue(ui.cfg, "network_orcid", work)
    return ui.after_job("/discover", cmd_id, tab="people")


def register_discover(ui: UiContext) -> None:
    app = ui.app

    @app.get("/discover", response_class=HTMLResponse)
    def page_discover(
        request: Request,
        list_name: str = "",
        error: str = "",
        run: str = "",
        watch_name: str = "",
        compare_run: str = "",
        tab: str = "",
    ) -> HTMLResponse:
        return handle_page_discover(
            ui,
            request=request,
            list_name=list_name,
            error=error,
            run=run,
            watch_name=watch_name,
            compare_run=compare_run,
            tab=tab,
        )

    @app.post("/discover/explore")
    async def discover_explore(request: Request):
        return await handle_discover_explore(ui, request=request)

    @app.post("/discover/topic")
    async def discover_topic(request: Request) -> RedirectResponse:
        return await handle_discover_topic(ui, request=request)

    @app.post("/discover/profile-save")
    async def discover_profile_save(request: Request) -> RedirectResponse:
        return await handle_discover_profile_save(ui, request=request)

    @app.post("/discover/refs-gap")
    async def discover_refs_gap(request: Request) -> RedirectResponse:
        return await handle_discover_refs_gap(ui, request=request)

    @app.post("/discover/ingest-preview")
    async def discover_ingest_preview(request: Request) -> RedirectResponse:
        return await handle_discover_ingest_preview(ui, request=request)

    @app.post("/discover/ingest-apply", response_model=None)
    async def discover_ingest_apply(request: Request):
        return await handle_discover_ingest_apply(ui, request=request)

    @app.post("/discover/authors")
    async def discover_authors(request: Request) -> RedirectResponse:
        return await handle_discover_authors(ui, request=request)

    @app.post("/discover/packs-promote")
    async def discover_packs_promote(request: Request) -> RedirectResponse:
        return await handle_discover_packs_promote(ui, request=request)

    @app.post("/discover/follow")
    async def discover_follow(request: Request) -> RedirectResponse:
        return await handle_discover_follow(ui, request=request)

    @app.post("/discover/apply-preview")
    async def discover_apply_preview(request: Request) -> RedirectResponse:
        return await handle_discover_apply_preview(ui, request=request)

    @app.post("/discover/apply", response_model=None)
    async def discover_apply(request: Request):
        return await handle_discover_apply(ui, request=request)

    @app.post("/discover/check-again")
    async def discover_check(request: Request) -> RedirectResponse:
        return await handle_discover_check(ui, request=request)

    @app.post("/discover/keep")
    async def discover_keep(request: Request):
        return await handle_discover_keep(ui, request=request)

    @app.get("/discover/graph")
    def discover_graph(
        run_id: str = "", watch_name: str = "", compare_run: str = ""
    ) -> JSONResponse:
        return handle_discover_graph(
            ui, run_id=run_id, watch_name=watch_name, compare_run=compare_run
        )

    @app.get("/discover/graph/meta")
    def discover_graph_meta() -> JSONResponse:
        return handle_discover_graph_meta(ui)

    @app.post("/discover/graph/annotate")
    async def discover_graph_annotate(request: Request) -> JSONResponse:
        return await handle_discover_graph_annotate(ui, request=request)

    @app.post("/discover/graph/add")
    async def discover_graph_add(request: Request) -> JSONResponse:
        return await handle_discover_graph_add(ui, request=request)

    @app.post("/discover/graph/find-pdf")
    async def discover_graph_find_pdf(request: Request) -> JSONResponse:
        return await handle_discover_graph_find_pdf(ui, request=request)

    @app.post("/discover/graph/remove")
    async def discover_graph_remove(request: Request) -> JSONResponse:
        return await handle_discover_graph_remove(ui, request=request)

    @app.post("/discover/graph/repair")
    async def discover_graph_repair(request: Request) -> JSONResponse:
        return await handle_discover_graph_repair(ui, request=request)

    @app.post("/discover/graph/halo")
    async def discover_graph_halo(request: Request) -> JSONResponse:
        return await handle_discover_graph_halo(ui, request=request)

    @app.post("/discover/graph/expand")
    async def discover_graph_expand(request: Request) -> JSONResponse:
        return await handle_discover_graph_expand(ui, request=request)

    @app.post("/discover/watch")
    async def discover_watch(request: Request) -> RedirectResponse:
        return await handle_discover_watch(ui, request=request)

    @app.post("/discover/continue")
    async def discover_continue(request: Request) -> RedirectResponse:
        return await handle_discover_continue(ui, request=request)

    @app.post("/discover/resume")
    async def discover_resume(request: Request) -> RedirectResponse:
        return await handle_discover_resume(ui, request=request)

    @app.post("/discover/profile-run")
    async def discover_profile_run(request: Request) -> RedirectResponse:
        return await handle_discover_profile_run(ui, request=request)

    @app.post("/discover/briefing")
    async def discover_briefing(request: Request) -> RedirectResponse:
        return await handle_discover_briefing(ui, request=request)

    @app.post("/discover/digest")
    async def discover_digest(request: Request) -> RedirectResponse:
        return await handle_discover_digest(ui, request=request)

    @app.post("/discover/watch-briefing")
    async def discover_watch_briefing(request: Request) -> RedirectResponse:
        return await handle_discover_watch_briefing(ui, request=request)

    @app.post("/discover/watch-digest")
    async def discover_watch_digest(request: Request) -> RedirectResponse:
        return await handle_discover_watch_digest(ui, request=request)

    @app.post("/discover/aw/save")
    async def discover_aw_save(request: Request) -> RedirectResponse:
        return await handle_discover_aw_save(ui, request=request)

    @app.post("/discover/aw/add")
    async def discover_aw_add(request: Request) -> RedirectResponse:
        return await handle_discover_aw_add(ui, request=request)

    @app.post("/discover/aw/remove")
    async def discover_aw_remove(request: Request) -> RedirectResponse:
        return await handle_discover_aw_remove(ui, request=request)

    @app.post("/discover/aw/resolve")
    async def discover_aw_resolve(request: Request) -> RedirectResponse:
        return await handle_discover_aw_resolve(ui, request=request)

    @app.post("/discover/aw/run")
    async def discover_aw_run(request: Request) -> RedirectResponse:
        return await handle_discover_aw_run(ui, request=request)

    @app.post("/discover/aw/import", response_model=None)
    async def discover_aw_import(request: Request):
        return await handle_discover_aw_import(ui, request=request)

    @app.post("/discover/aw/suggest")
    async def discover_aw_suggest(request: Request) -> RedirectResponse:
        return await handle_discover_aw_suggest(ui, request=request)

    @app.post("/discover/aw/accept")
    async def discover_aw_accept(request: Request) -> RedirectResponse:
        return await handle_discover_aw_accept(ui, request=request)

    @app.post("/discover/aw/delete")
    async def discover_aw_delete(request: Request) -> RedirectResponse:
        return await handle_discover_aw_delete(ui, request=request)

    @app.post("/discover/aw/edit")
    async def discover_aw_edit(request: Request) -> RedirectResponse:
        return await handle_discover_aw_edit(ui, request=request)

    @app.post("/discover/aw/briefing")
    async def discover_aw_briefing(request: Request) -> RedirectResponse:
        return await handle_discover_aw_briefing(ui, request=request)

    @app.get("/discover/network/meta")
    def discover_network_meta() -> JSONResponse:
        return handle_discover_network_meta(ui)

    @app.get("/discover/network")
    def discover_network(run_id: str = "", phase: str = "") -> JSONResponse:
        return handle_discover_network(ui, run_id=run_id, phase=phase)

    @app.post("/discover/network/run")
    async def discover_network_run(request: Request) -> RedirectResponse:
        return await handle_discover_network_run(ui, request=request)
