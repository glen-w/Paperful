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
    layout_options,
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
)


def handle_page_library(ui: UiContext, request: Request) -> HTMLResponse:
    prefs = prefs_from_request(request)
    tree = ui.collections(force=request.query_params.get("refresh") == "1")
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
            scope_items, manifest = jobs.load_scope_items_cached(
                ui.cfg, prefs.collection
            )
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
            collections_checked_at=ui.collections_checked_at(),
            items=items,
            library_pagination=library_pagination,
            error=error,
            briefs=briefs,
            dest_options=dest_options(),
        ),
    )
    if persist_per_page:
        set_cookie(response, COOKIE_LIBRARY_PER_PAGE, str(per_page), request=request)
    return response


_VERB_PAGES: tuple[tuple[str, str], ...] = (
    ("preview_run", "/wanted"),
    ("grab", "/wanted"),
    ("attach", "/wanted"),
    ("recover", "/wanted"),
    ("handoff", "/wanted"),
    ("inbox_drain", "/wanted"),
    ("reachout", "/wanted"),
    ("pending_fill", "/wanted"),
    ("summarize_item", "/wanted"),
    ("snowball", "/discover?tab=queue"),
    ("authorwatch", "/discover?tab=people"),
    ("network", "/discover?tab=people"),
    ("search", "/discover?tab=web"),
    ("watch", "/discover?tab=following"),
    ("check_again", "/discover?tab=following"),
    ("refs_gap", "/discover?tab=grow"),
    ("ingest_dois", "/discover?tab=grow"),
    ("authors", "/discover?tab=grow"),
    ("packs_promote", "/discover?tab=grow"),
    ("repair", "/repair"),
    ("mirror", "/mirror"),
    ("ask", "/ask"),
    ("rag", "/index"),
    ("extract_sections", "/index"),
    ("summarize", "/index"),
    ("synthesize", "/index"),
    ("critique", "/critique"),
    ("rewrite", "/rewrite"),
    ("stuff", "/stuff"),
    ("doctor", "/system"),
)


def page_for_verb(verb: str) -> str:
    """Workbench page that shows a job's outcome (longest prefix wins)."""
    best = ""
    best_len = -1
    for prefix, page in _VERB_PAGES:
        if verb == prefix or verb.startswith(prefix + "_") or verb.startswith(prefix):
            if len(prefix) > best_len:
                best, best_len = page, len(prefix)
    return best


def _result_summary(rec: dict[str, Any]) -> str:
    """Compact one-line view of ``result`` for the Activity table."""
    result = rec.get("result")
    if not isinstance(result, dict):
        return ""
    parts: list[str] = []
    for key, value in result.items():
        if key in {"markdown", "rows", "candidates", "items", "errors"}:
            if isinstance(value, (list, dict)):
                parts.append(f"{key} {len(value)}")
            continue
        if isinstance(value, (str, int, float, bool)) and value not in ("", None):
            text = str(value)
            if len(text) > 48:
                text = text[:45] + "…"
            parts.append(f"{key} {text}")
        if len(parts) >= 5:
            break
    return " · ".join(parts)


def activity_rows(cfg: Config, limit: int = 50) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rec in commands.list_commands(cfg, limit=limit):
        created = float(rec.get("created") or 0.0)
        started = float(rec.get("started") or 0.0)
        finished = float(rec.get("finished") or 0.0)
        duration = ""
        if started and finished and finished >= started:
            secs = finished - started
            duration = f"{secs:.0f} s" if secs < 90 else f"{secs / 60:.1f} min"
        verb = str(rec.get("verb") or "")
        page = page_for_verb(verb)
        link = ""
        if page:
            link = page + ("&" if "?" in page else "?") + "run=" + str(rec.get("id"))
        rows.append(
            {
                **rec,
                "created_ts": created,
                "duration": duration,
                "result_summary": _result_summary(rec),
                "link": link,
            }
        )
    return rows


def handle_page_activity(ui: UiContext, request: Request) -> HTMLResponse:
    show_all = request.query_params.get("all") == "1"
    verb = str(request.query_params.get("verb") or "").strip()
    rows = activity_rows(ui.cfg, limit=500 if show_all else 50)
    verbs = sorted({str(r.get("verb") or "") for r in rows if r.get("verb")})
    if verb:
        rows = [r for r in rows if str(r.get("verb") or "") == verb]
    return ui.templates.TemplateResponse(
        request,
        "activity.html",
        ui.ctx(
            request,
            "activity",
            commands=rows,
            verbs=verbs,
            verb_filter=verb,
            show_all=show_all,
            trust_line=_trust_line(ui.cfg),
        ),
    )


DOCTOR_STALE_AFTER = 10 * 60  # seconds before System suggests a re-check


def _doctor_rows(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in raw:
        code = str(row.get("code") or "")
        detail = str(row.get("detail") or "")
        status = str(row.get("status") or "")
        step = next_step(code, detail)
        rows.append(
            {
                "name": row["name"],
                "status": status,
                "code": code,
                "detail": detail,
                # Only amber/red rows carry an action; green rows show detail.
                "next": step if status in {"amber", "red"} else "",
            }
        )
    return rows


def handle_page_system(ui: UiContext, request: Request, run: str = "") -> HTMLResponse:
    """Render doctor from the process cache.

    The first visit (empty cache) runs doctor inline so the page is never
    blank. Later visits render instantly; **Re-check** enqueues a ``doctor``
    job and the page reloads when it finishes.
    """
    checked_at = float(ui.health_cache.get("at") or 0.0)
    if not checked_at:
        raw = ui.remember_doctor(_ui_app.doctor_payload(ui.cfg))
        checked_at = float(ui.health_cache.get("at") or time.time())
    else:
        raw = ui.cached_doctor()
    return ui.templates.TemplateResponse(
        request,
        "system.html",
        ui.ctx(
            request,
            "system",
            checks=_doctor_rows(raw),
            checked_at=checked_at,
            stale=(time.time() - checked_at) > DOCTOR_STALE_AFTER,
            job=job_view(command_by_id(ui.cfg, (run or "").strip())),
            poll_run=(run or "").strip(),
        ),
    )


def handle_system_recheck(ui: UiContext) -> RedirectResponse:
    def work(cmd_id: str) -> None:
        checks = _ui_app.doctor_payload(ui.cfg)
        ui.remember_doctor(checks)
        rec = commands.read_command(ui.cfg, cmd_id) or {}
        worst = _health_status(checks)
        rec["result"] = {"health": worst, "checks": len(checks)}
        commands.write_command(ui.cfg, rec)

    cmd_id = commands.enqueue(ui.cfg, "doctor", work)
    return ui.after_job("/system", cmd_id)


def handle_page_settings(
    ui: UiContext, request: Request, saved: int = 0, error: str = ""
) -> HTMLResponse:
    return ui.templates.TemplateResponse(
        request,
        "settings.html",
        ui.ctx(
            request,
            "settings",
            error=error,
            config_path=str(ui.cfg.config_path or ""),
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
            web_search=ui.cfg.ui_web_search,
        ),
    )


def _settings_error(ui: UiContext, message: str) -> RedirectResponse:
    return RedirectResponse(
        url=ui.page_url("/settings", error=message), status_code=303
    )


async def handle_save_settings(ui: UiContext, request: Request) -> RedirectResponse:
    from .config_patch import ConfigPatchError, apply_patches

    form = await request.form()
    email = str(form.get("email") or "").strip()
    host = str(form.get("zotero_host") or "").strip()
    out_dir = str(form.get("out_dir") or "").strip()
    preset = str(form.get("preset") or "oa")
    attach_mode = str(form.get("attach_mode") or "").strip().lower()
    edit = str(form.get("citation_map_edit") or "").strip().lower()
    auto_search = form.get("citation_map_auto_search") == "1"
    network = "on" if form.get("coauthor_network") == "1" else "off"
    web = "on" if form.get("web_search") == "1" else "off"

    # Validate before touching anything.
    if email and ("@" not in email or " " in email or len(email) > 254):
        return _settings_error(ui, "Unpaywall email must look like name@example.org.")
    if out_dir:
        candidate = Path(out_dir).expanduser()
        if not candidate.is_absolute():
            candidate = (
                ui.cfg.config_path.parent if ui.cfg.config_path else Path.cwd()
            ) / candidate
        if candidate.exists() and not candidate.is_dir():
            return _settings_error(ui, f"out/ path is a file, not a folder: {out_dir}")
        if not candidate.parent.exists():
            return _settings_error(
                ui, f"out/ path parent folder does not exist: {candidate.parent}"
            )
    if attach_mode and attach_mode not in {"manual", "auto"}:
        return _settings_error(ui, "After Grab must be Manual or Automatic.")
    if edit and edit not in {"sidebar", "popup", "both", "off"}:
        return _settings_error(ui, "Citation map edits has an unknown value.")

    patches: dict[tuple[str, str], object] = {}
    if email:
        patches[("", "email")] = email
    if host:
        patches[("zotero", "host")] = host
    if out_dir:
        patches[("", "out_dir")] = out_dir
    if attach_mode:
        patches[("ui", "attach_mode")] = attach_mode
    if edit:
        patches[("ui", "citation_map_edit")] = edit
    patches[("ui", "citation_map_auto_search")] = auto_search
    patches[("ui", "coauthor_network")] = network
    patches[("ui", "web_search")] = web

    path = ui.cfg.config_path
    if path is not None and path.is_file():
        try:
            apply_patches(path, patches)
        except ConfigPatchError as exc:
            return _settings_error(ui, str(exc))
    # Mirror into the live config so the running process agrees with disk.
    if attach_mode:
        ui.cfg.ui_attach_mode = attach_mode
    if edit:
        ui.cfg.ui_citation_map_edit = edit
    ui.cfg.ui_citation_map_auto_search = auto_search
    ui.cfg.ui_coauthor_network = network
    ui.cfg.ui_web_search = web
    resp = RedirectResponse(url="/settings?saved=1", status_code=303)
    if preset in {"oa", "eoi"}:
        set_cookie(resp, COOKIE_PRESET, preset, request=request)
    return resp


def _back_to(request: Request, default: str) -> str:
    """Same-host Referer path, or ``default`` (never an off-site redirect)."""
    from .errors import same_host_path

    return (
        same_host_path(
            request.headers.get("referer") or "", request.headers.get("host") or ""
        )
        or default
    )


async def handle_prefs_advanced(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    on = form.get("advanced") == "1"
    resp = RedirectResponse(url=_back_to(request, "/wanted"), status_code=303)
    set_cookie(resp, COOKIE_ADVANCED, "1" if on else "0", request=request)
    return resp


async def handle_prefs_collection(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    coll = str(form.get("collection") or "")
    nxt = str(form.get("next") or "").strip()
    target = nxt if nxt.startswith("/") and not nxt.startswith("//") else "/library"
    resp = RedirectResponse(url=target, status_code=303)
    set_cookie(resp, COOKIE_COLLECTION, coll, request=request)
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
            layout_options=layout_options(),
            synth_form=briefs_synth_form(
                request,
                dest_default=ui.cfg.synthesize_dest,
                collection=prefs.collection,
                last=synthesize_result,
                layout_default=ui.cfg.synthesize_layout,
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
    raw_layout = str(form.get("layout") or "").strip()
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
                synth_layout=raw_layout,
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
    from ..synthesis_layouts import canonical_layout

    try:
        layout = canonical_layout(raw_layout or ui.cfg.synthesize_layout)
    except ValueError:
        return bounce("layout")

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
            layout=layout,
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
            "layout": layout,
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

    @app.post("/library/refresh")
    def library_refresh() -> RedirectResponse:
        ui.invalidate_collections()
        jobs.invalidate_scope_cache()
        return RedirectResponse(url="/library?refresh=1", status_code=303)

    @app.get("/activity", response_class=HTMLResponse)
    def page_activity(request: Request) -> HTMLResponse:
        return handle_page_activity(ui, request=request)

    @app.get("/system", response_class=HTMLResponse)
    def page_system(request: Request, run: str = "") -> HTMLResponse:
        return handle_page_system(ui, request=request, run=run)

    @app.post("/system/recheck")
    def system_recheck() -> RedirectResponse:
        return handle_system_recheck(ui)

    @app.get("/settings", response_class=HTMLResponse)
    def page_settings(
        request: Request, saved: int = 0, error: str = ""
    ) -> HTMLResponse:
        return handle_page_settings(ui, request=request, saved=saved, error=error)

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
