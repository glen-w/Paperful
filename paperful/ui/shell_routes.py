"""Workbench HTTP routes (shell)."""

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
    library_has_attached_pdf,
    WANTED_FILTER_LABELS,
    WANTED_ORDER_LABELS,
    library_items_page,
    library_page_from_request,
    library_page_size_options,
    library_per_page_from_request,
    nest_collection_rows,
    pagination_meta,
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


def handle_page_library(ui: UiContext, request: Request) -> HTMLResponse:
    prefs = prefs_from_request(request)
    tree = _ui_app.collections_tree(ui.cfg)
    error = ""
    rows = []
    nested: list[dict[str, Any]] = []
    if tree.get("ok"):
        rows = tree.get("collections") or []
        nested = nest_collection_rows(rows, active=prefs.collection)
    else:
        error = str(tree.get("error") or "Library unavailable")
    items: list[dict[str, Any]] = []
    library_total = 0
    library_page = 1
    library_page_count = 1
    per_page = library_per_page_from_request(request, ui.cfg)
    page_sizes = library_page_size_options(ui.cfg)
    persist_per_page = request.query_params.get("per_page") is not None
    if prefs.collection:
        try:
            scope_items, manifest = jobs._load_scope_items(ui.cfg, prefs.collection)
            page = library_page_from_request(request)
            items, library_total, library_page, library_page_count = library_items_page(
                ui.cfg,
                scope_items,
                manifest,
                page=page,
                per_page=per_page,
            )
        except Exception as exc:
            error = error or str(exc)
    briefs = briefs_page_flags(ui.cfg)
    library_pagination = pagination_meta(
        page=library_page,
        per_page=per_page,
        page_count=library_page_count,
        total=library_total,
        page_sizes=page_sizes,
    )
    library_pagination.update(
        {
            "prev_url": (
                ui.page_url("/library", page=library_page - 1, per_page=per_page)
                if library_page > 1
                else ""
            ),
            "next_url": (
                ui.page_url("/library", page=library_page + 1, per_page=per_page)
                if library_page < library_page_count
                else ""
            ),
        }
    )
    response = ui.templates.TemplateResponse(
        request,
        "library.html",
        ui.ctx(
            request,
            "library",
            collections=rows,
            collection_tree=nested,
            items=items,
            library_pagination=library_pagination,
            error=error,
            briefs=briefs,
            dest_options=dest_options(),
        ),
    )
    if persist_per_page:
        set_cookie(response, COOKIE_LIBRARY_PER_PAGE, str(per_page))
    return response


def handle_page_activity(ui: UiContext, request: Request) -> HTMLResponse:
    return ui.templates.TemplateResponse(
        request,
        "activity.html",
        ui.ctx(
            request,
            "activity",
            commands=commands.list_commands(ui.cfg),
            trust_line=_trust_line(ui.cfg),
        ),
    )


def handle_page_system(ui: UiContext, request: Request) -> HTMLResponse:
    raw = ui.remember_doctor(_ui_app.doctor_payload(ui.cfg))
    checks = []
    for row in raw:
        checks.append(
            {
                "name": row["name"],
                "status": row["status"],
                "next": next_step(
                    str(row.get("code") or ""), str(row.get("detail") or "")
                ),
            }
        )
    return ui.templates.TemplateResponse(
        request,
        "system.html",
        ui.ctx(request, "system", checks=checks),
    )


def handle_page_settings(
    ui: UiContext, request: Request, saved: int = 0
) -> HTMLResponse:
    return ui.templates.TemplateResponse(
        request,
        "settings.html",
        ui.ctx(
            request,
            "settings",
            email=ui.cfg.email,
            zotero_host=__import__(
                "paperful.zot", fromlist=["zotero_local_host"]
            ).zotero_local_host(),
            saved=bool(saved),
            out_dir=str(ui.cfg.out_dir),
            attach_mode=ui.cfg.ui_attach_mode,
            show_auto_attach_setting=library_has_attached_pdf(ui.cfg),
            citation_map_edit=ui.cfg.ui_citation_map_edit,
            citation_map_auto_search=ui.cfg.ui_citation_map_auto_search,
            coauthor_network=ui.cfg.ui_coauthor_network,
        ),
    )


async def handle_save_settings(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    email = str(form.get("email") or "")
    host = str(form.get("zotero_host") or "")
    out_dir = str(form.get("out_dir") or "")
    preset = str(form.get("preset") or "oa")
    if email:
        _patch_config_field(ui.cfg, "", "email", email)
    if host:
        _patch_config_field(ui.cfg, "zotero", "host", host)
    if out_dir:
        _patch_config_field(ui.cfg, "", "out_dir", out_dir)
    path = ui.cfg.config_path
    attach_mode = str(form.get("attach_mode") or "").strip().lower()
    if attach_mode in {"manual", "auto"}:
        ui.cfg.ui_attach_mode = attach_mode
        if path is not None and path.is_file():
            text = path.read_text(encoding="utf-8")
            path.write_text(
                _patch_section_assignment(
                    text, "ui", "attach_mode", f'"{attach_mode}"'
                ),
                encoding="utf-8",
            )
    edit = str(form.get("citation_map_edit") or "").strip().lower()
    if edit in {"sidebar", "popup", "both", "off"}:
        ui.cfg.ui_citation_map_edit = edit
        if path is not None and path.is_file():
            text = path.read_text(encoding="utf-8")
            path.write_text(
                _patch_section_assignment(text, "ui", "citation_map_edit", f'"{edit}"'),
                encoding="utf-8",
            )
    auto_search = form.get("citation_map_auto_search") == "1"
    ui.cfg.ui_citation_map_auto_search = auto_search
    if path is not None and path.is_file():
        text = path.read_text(encoding="utf-8")
        path.write_text(
            _patch_section_assignment(
                text,
                "ui",
                "citation_map_auto_search",
                "true" if auto_search else "false",
            ),
            encoding="utf-8",
        )
    network = "on" if form.get("coauthor_network") == "1" else "off"
    ui.cfg.ui_coauthor_network = network
    if path is not None and path.is_file():
        text = path.read_text(encoding="utf-8")
        path.write_text(
            _patch_section_assignment(text, "ui", "coauthor_network", f'"{network}"'),
            encoding="utf-8",
        )
    resp = RedirectResponse(url="/settings?saved=1", status_code=303)
    if preset in {"oa", "eoi"}:
        set_cookie(resp, COOKIE_PRESET, preset)
    return resp


async def handle_prefs_advanced(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    on = form.get("advanced") == "1"
    referer = request.headers.get("referer") or "/wanted"
    resp = RedirectResponse(url=referer, status_code=303)
    set_cookie(resp, COOKIE_ADVANCED, "1" if on else "0")
    return resp


async def handle_prefs_collection(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    coll = str(form.get("collection") or "")
    resp = RedirectResponse(url="/library", status_code=303)
    set_cookie(resp, COOKIE_COLLECTION, coll)
    return resp


def handle_page_briefs(
    ui: UiContext,
    request: Request,
    run: str = "",
    error: str = "",
) -> HTMLResponse:
    flags = briefs_page_flags(ui.cfg)
    if flags["llm_on"]:
        msg = (
            "Write grounded summaries of PDFs in the current collection, "
            "then fold those notes into a literature-review report. "
            "Scope follows the collection chip."
        )
    else:
        msg = (
            "Turn on [llm] in config.toml to summarize and synthesize. "
            "Settings does not toggle it."
        )
    err = ASK_ERROR_MESSAGES.get(error, error)
    prefs = prefs_from_request(request)
    synthesize_result = last_job_result(ui.cfg, "synthesize", run)
    return ui.templates.TemplateResponse(
        request,
        "briefs.html",
        ui.ctx(
            request,
            "briefs",
            message=msg,
            flags=flags,
            dest_options=dest_options(),
            orders=SUMMARIZE_ORDERS,
            summaries=list_recent_summaries(ui.cfg),
            reports=list_html_stems(ui.cfg.reports_dir),
            summarize_result=last_job_result(ui.cfg, "summarize", run),
            synthesize_result=synthesize_result,
            synth_form=briefs_synth_form(
                request,
                dest_default=ui.cfg.synthesize_dest,
                collection=prefs.collection,
                last=synthesize_result,
            ),
            synth_via=str(request.query_params.get("via") or "").strip()
            == "synthesize",
            poll_run=(run or "").strip(),
            error=err,
        ),
    )


async def handle_briefs_summarize(ui: UiContext, request: Request) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    if not ui.cfg.llm_enabled:
        return RedirectResponse(
            url=ui.page_url("/briefs", error="llm"), status_code=303
        )
    try:
        year_from = ui.optional_int(form.get("year_from"))
        year_to = ui.optional_int(form.get("year_to"))
    except ValueError:
        return RedirectResponse(
            url=ui.page_url("/briefs", error="year"), status_code=303
        )
    try:
        limit = ui.optional_int(form.get("limit"), positive=True)
        max_new = ui.optional_int(form.get("max_new"), positive=True)
    except ValueError:
        return RedirectResponse(
            url=ui.page_url("/briefs", error="limit"), status_code=303
        )
    try:
        dest = ui.parse_dest(form.get("dest"), ui.cfg.summarize_dest)
    except ValueError:
        return RedirectResponse(
            url=ui.page_url("/briefs", error="dest"), status_code=303
        )
    order = str(form.get("order") or "").strip() or ui.cfg.summarize_order
    if order not in SUMMARIZE_ORDERS:
        return RedirectResponse(
            url=ui.page_url("/briefs", error="order"), status_code=303
        )
    force = form.get("force") == "1"

    def work(cmd_id: str) -> None:
        jobs.summarize(
            ui.cfg,
            cmd_id,
            collection=prefs.collection,
            year_from=year_from,
            year_to=year_to,
            limit=limit,
            max_new=max_new,
            dest=dest,
            order=order,
            force=force,
        )

    cmd_id = commands.enqueue(ui.cfg, "summarize", work)
    return RedirectResponse(url=ui.page_url("/briefs", run=cmd_id), status_code=303)


async def handle_briefs_synthesize(ui: UiContext, request: Request) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    raw_dest = str(form.get("dest") or "").strip()
    raw_limit = str(form.get("limit") or "").strip()
    raw_year_from = str(form.get("year_from") or "").strip()
    raw_year_to = str(form.get("year_to") or "").strip()
    force = form.get("force") == "1"

    def bounce(error: str) -> RedirectResponse:
        return RedirectResponse(
            url=ui.page_url(
                "/briefs",
                error=error,
                via="synthesize",
                synth_dest=raw_dest,
                synth_limit=raw_limit,
                synth_year_from=raw_year_from,
                synth_year_to=raw_year_to,
                synth_force="1" if force else "",
            ),
            status_code=303,
        )

    if not ui.cfg.llm_enabled:
        return bounce("llm")
    dry_run = str(form.get("dry_run") or "1") != "0"
    try:
        year_from = ui.optional_int(form.get("year_from"))
        year_to = ui.optional_int(form.get("year_to"))
    except ValueError:
        return bounce("year")
    try:
        limit = ui.optional_int(form.get("limit"), positive=True)
    except ValueError:
        return bounce("limit")
    try:
        dest = ui.parse_dest(
            form.get("dest"), dest_for_form(ui.cfg.synthesize_dest, prefs.collection)
        )
    except ValueError:
        return bounce("dest")
    from ..config import wants_zotero

    if wants_zotero(dest) and not prefs.collection and not dry_run:
        return bounce("collection")

    def work(cmd_id: str) -> None:
        jobs.synthesize(
            ui.cfg,
            cmd_id,
            collection=prefs.collection,
            year_from=year_from,
            year_to=year_to,
            limit=limit,
            dest=dest,
            dry_run=dry_run,
            force=force,
        )

    cmd_id = commands.enqueue(
        ui.cfg,
        "synthesize",
        work,
        args={
            "dest": dest,
            "limit": limit,
            "year_from": year_from,
            "year_to": year_to,
            "force": force,
            "dry_run": dry_run,
        },
    )
    return RedirectResponse(url=ui.page_url("/briefs", run=cmd_id), status_code=303)


def handle_briefs_summary(ui: UiContext, request: Request, key: str):
    meta = summary_meta(ui.cfg, key)
    if meta is None or safe_child(ui.cfg.summaries_dir, f"{key}.html") is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    return ui.templates.TemplateResponse(
        request,
        "brief_summary.html",
        ui.ctx(
            request,
            "briefs",
            key=meta["name"],
            cite=meta["cite"],
            model=meta["model"],
        ),
    )


def handle_briefs_report(ui: UiContext, slug: str):
    path = safe_child(ui.cfg.reports_dir, f"{slug}.html")
    if path is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    return FileResponse(path, media_type="text/html; charset=utf-8")


def handle_run_events(ui: UiContext, cmd_id: str):
    if commands.read_command(ui.cfg, cmd_id) is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    return StreamingResponse(
        commands.iter_command_status_events(ui.cfg, cmd_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def handle_run_status(ui: UiContext, cmd_id: str) -> JSONResponse:
    rec = commands.read_command(ui.cfg, cmd_id)
    if rec is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    return JSONResponse({"ok": True, **rec})


def handle_gui_noop(ui: UiContext) -> JSONResponse:
    def work(cmd_id: str) -> None:
        jobs.run_noop(ui.cfg, cmd_id)

    cmd_id = commands.enqueue(ui.cfg, "noop", work)
    return JSONResponse({"id": cmd_id, "status": "queued"}, status_code=202)


def register_shell(ui: UiContext) -> None:
    app = ui.app

    @app.get("/library", response_class=HTMLResponse)
    def page_library(request: Request) -> HTMLResponse:
        return handle_page_library(ui, request=request)

    @app.get("/activity", response_class=HTMLResponse)
    def page_activity(request: Request) -> HTMLResponse:
        return handle_page_activity(ui, request=request)

    @app.get("/system", response_class=HTMLResponse)
    def page_system(request: Request) -> HTMLResponse:
        return handle_page_system(ui, request=request)

    @app.get("/settings", response_class=HTMLResponse)
    def page_settings(request: Request, saved: int = 0) -> HTMLResponse:
        return handle_page_settings(ui, request=request, saved=saved)

    @app.post("/settings")
    async def save_settings(request: Request) -> RedirectResponse:
        return await handle_save_settings(ui, request=request)

    @app.post("/prefs/advanced")
    async def prefs_advanced(request: Request) -> RedirectResponse:
        return await handle_prefs_advanced(ui, request=request)

    @app.post("/prefs/collection")
    async def prefs_collection(request: Request) -> RedirectResponse:
        return await handle_prefs_collection(ui, request=request)

    @app.get("/briefs", response_class=HTMLResponse)
    def page_briefs(
        request: Request,
        run: str = "",
        error: str = "",
    ) -> HTMLResponse:
        return handle_page_briefs(ui, request=request, run=run, error=error)

    @app.post("/briefs/summarize")
    async def briefs_summarize(request: Request) -> RedirectResponse:
        return await handle_briefs_summarize(ui, request=request)

    @app.post("/briefs/synthesize")
    async def briefs_synthesize(request: Request) -> RedirectResponse:
        return await handle_briefs_synthesize(ui, request=request)

    @app.get("/briefs/summary/{key}", response_class=HTMLResponse)
    def briefs_summary(request: Request, key: str):
        return handle_briefs_summary(ui, request=request, key=key)

    @app.get("/briefs/report/{slug}", response_model=None)
    def briefs_report(slug: str):
        return handle_briefs_report(ui, slug=slug)

    @app.get("/v1/runs/{cmd_id}/events", response_model=None)
    def run_events(cmd_id: str):
        return handle_run_events(ui, cmd_id=cmd_id)

    @app.get("/v1/runs/{cmd_id}")
    def run_status(cmd_id: str) -> JSONResponse:
        return handle_run_status(ui, cmd_id=cmd_id)

    @app.post("/v1/gui/noop")
    def gui_noop() -> JSONResponse:
        return handle_gui_noop(ui)
