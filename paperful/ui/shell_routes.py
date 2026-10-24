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

def register_shell(ui: UiContext) -> None:
    app = ui.app
    cfg = ui.cfg
    templates = ui.templates
    ctx = ui.ctx
    _page_url = ui.page_url
    _after_job = ui.after_job
    _optional_int = ui.optional_int
    _upload_bytes = ui.upload_bytes
    _resolved_prompt = ui.resolved_prompt
    _save_prompt_if_asked = ui.save_prompt_if_asked
    _parse_dest = ui.parse_dest
    _remember_doctor = ui.remember_doctor
    _cached_doctor = ui.cached_doctor

    @app.get("/library", response_class=HTMLResponse)
    def page_library(request: Request) -> HTMLResponse:
        prefs = prefs_from_request(request)
        tree = _ui_app.collections_tree(cfg)
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
        per_page = library_per_page_from_request(request, cfg)
        page_sizes = library_page_size_options(cfg)
        persist_per_page = request.query_params.get("per_page") is not None
        if prefs.collection:
            try:
                scope_items, manifest = jobs._load_scope_items(cfg, prefs.collection)
                page = library_page_from_request(request)
                items, library_total, library_page, library_page_count = library_items_page(
                    cfg,
                    scope_items,
                    manifest,
                    page=page,
                    per_page=per_page,
                )
            except Exception as exc:
                error = error or str(exc)
        briefs = briefs_page_flags(cfg)
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
                    _page_url("/library", page=library_page - 1, per_page=per_page)
                    if library_page > 1
                    else ""
                ),
                "next_url": (
                    _page_url("/library", page=library_page + 1, per_page=per_page)
                    if library_page < library_page_count
                    else ""
                ),
            }
        )
        response = templates.TemplateResponse(
            request,
            "library.html",
            ctx(
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


    @app.get("/activity", response_class=HTMLResponse)
    def page_activity(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "activity.html",
            ctx(
                request,
                "activity",
                commands=commands.list_commands(cfg),
                trust_line=_trust_line(cfg),
            ),
        )


    @app.get("/system", response_class=HTMLResponse)
    def page_system(request: Request) -> HTMLResponse:
        raw = _remember_doctor(_ui_app.doctor_payload(cfg))
        checks = []
        for row in raw:
            checks.append(
                {
                    "name": row["name"],
                    "status": row["status"],
                    "next": next_step(str(row.get("code") or ""), str(row.get("detail") or "")),
                }
            )
        return templates.TemplateResponse(
            request,
            "system.html",
            ctx(request, "system", checks=checks),
        )


    @app.get("/settings", response_class=HTMLResponse)
    def page_settings(request: Request, saved: int = 0) -> HTMLResponse:
        from ..snowball.map_settings import for_config as map_for_config
        from ..snowball.similar_settings import for_config

        return templates.TemplateResponse(
            request,
            "settings.html",
            ctx(
                request,
                "settings",
                email=cfg.email,
                zotero_host=__import__("paperful.zot", fromlist=["zotero_local_host"]).zotero_local_host(),
                saved=bool(saved),
                out_dir=str(cfg.out_dir),
                attach_mode=cfg.ui_attach_mode,
                show_auto_attach_setting=library_has_attached_pdf(cfg),
                citation_map_edit=cfg.ui_citation_map_edit,
                citation_map_auto_search=cfg.ui_citation_map_auto_search,
                similar=for_config(cfg).to_dict(),
                map_opts=map_for_config(cfg).to_dict(),
                similar_store_configured=bool((cfg.openalex_store_backend or "").strip()),
                config_writable=cfg.config_path is not None and cfg.config_path.is_file(),
            ),
        )

    @app.post("/settings/map")
    async def save_map_settings(request: Request) -> RedirectResponse:
        from ..snowball.map_settings import DEFAULT as MAP_DEFAULT
        from ..snowball.map_settings import MAP_SAVE_KEYS, for_config as map_for_config
        from ..snowball.similar_settings import toml_literal

        form = await request.form()
        if form.get("reset") == "1":
            chosen = MAP_DEFAULT
        else:
            raw = {key: form.get(key) for key in MAP_SAVE_KEYS if key in form}
            raw["fit"] = form.get("fit") == "1"
            chosen = map_for_config(cfg).merged(raw)
        cfg.map_settings = chosen
        path = cfg.config_path
        if path is not None and path.is_file():
            text = path.read_text(encoding="utf-8")
            values = chosen.to_dict()
            for key in MAP_SAVE_KEYS:
                text = _patch_section_assignment(text, "map", key, toml_literal(values.get(key)))
            path.write_text(text, encoding="utf-8")
        return RedirectResponse(url="/settings?saved=1#maps", status_code=303)

    @app.post("/settings/similar-map")
    async def save_similar_map(request: Request) -> RedirectResponse:
        from ..snowball.similar_settings import (
            DEFAULT,
            SIMILAR_SAVE_KEYS,
            for_config,
            toml_literal,
            written_cap_keys,
        )

        form = await request.form()
        current = for_config(cfg)
        if form.get("reset") == "1":
            chosen = DEFAULT
        else:
            raw = {key: form.get(key) for key in SIMILAR_SAVE_KEYS if key in form}
            if str(raw.get("pool") or "").strip().lower() == current.pool:
                # Unchanged depth keeps any exact caps from config.toml.
                raw.pop("pool")
            # Unchecked boxes are absent from the form.
            raw["hide_in_library"] = form.get("hide_in_library") == "1"
            for key in ("year_from", "year_to"):
                if not str(raw.get(key) or "").strip():
                    raw[key] = 0
            chosen = current.merged(raw)
        cfg.similar_map = chosen
        path = cfg.config_path
        if path is not None and path.is_file():
            text = path.read_text(encoding="utf-8")
            values = chosen.to_dict()
            for key in SIMILAR_SAVE_KEYS:
                text = _patch_section_assignment(
                    text, "similar_map", key, toml_literal(values.get(key))
                )
            # Exact caps already in the file must follow a new depth, or a
            # restart would bring the old caps back.
            for key in written_cap_keys(text):
                text = _patch_section_assignment(
                    text, "similar_map", key, toml_literal(values.get(key))
                )
            path.write_text(text, encoding="utf-8")
        return RedirectResponse(url="/settings?saved=1#similar-map", status_code=303)


    @app.post("/settings")
    async def save_settings(request: Request) -> RedirectResponse:
        form = await request.form()
        email = str(form.get("email") or "")
        host = str(form.get("zotero_host") or "")
        out_dir = str(form.get("out_dir") or "")
        preset = str(form.get("preset") or "oa")
        if email:
            _patch_config_field(cfg, "", "email", email)
        if host:
            _patch_config_field(cfg, "zotero", "host", host)
        if out_dir:
            _patch_config_field(cfg, "", "out_dir", out_dir)
        path = cfg.config_path
        attach_mode = str(form.get("attach_mode") or "").strip().lower()
        if attach_mode in {"manual", "auto"}:
            cfg.ui_attach_mode = attach_mode
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
            cfg.ui_citation_map_edit = edit
            if path is not None and path.is_file():
                text = path.read_text(encoding="utf-8")
                path.write_text(
                    _patch_section_assignment(
                        text, "ui", "citation_map_edit", f'"{edit}"'
                    ),
                    encoding="utf-8",
                )
        auto_search = form.get("citation_map_auto_search") == "1"
        cfg.ui_citation_map_auto_search = auto_search
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
        resp = RedirectResponse(url="/settings?saved=1", status_code=303)
        if preset in {"oa", "eoi"}:
            set_cookie(resp, COOKIE_PRESET, preset)
        return resp


    @app.post("/prefs/advanced")
    async def prefs_advanced(request: Request) -> RedirectResponse:
        form = await request.form()
        on = form.get("advanced") == "1"
        referer = request.headers.get("referer") or "/wanted"
        resp = RedirectResponse(url=referer, status_code=303)
        set_cookie(resp, COOKIE_ADVANCED, "1" if on else "0")
        return resp


    @app.post("/prefs/collection")
    async def prefs_collection(request: Request) -> RedirectResponse:
        form = await request.form()
        coll = str(form.get("collection") or "")
        resp = RedirectResponse(url="/library", status_code=303)
        set_cookie(resp, COOKIE_COLLECTION, coll)
        return resp


    @app.get("/briefs", response_class=HTMLResponse)
    def page_briefs(
        request: Request,
        run: str = "",
        error: str = "",
    ) -> HTMLResponse:
        flags = briefs_page_flags(cfg)
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
        synthesize_result = last_job_result(cfg, "synthesize", run)
        return templates.TemplateResponse(
            request,
            "briefs.html",
            ctx(
                request,
                "briefs",
                message=msg,
                flags=flags,
                dest_options=dest_options(),
                orders=SUMMARIZE_ORDERS,
                summaries=list_recent_summaries(cfg),
                reports=list_html_stems(cfg.reports_dir),
                summarize_result=last_job_result(cfg, "summarize", run),
                synthesize_result=synthesize_result,
                synth_form=briefs_synth_form(
                    request,
                    dest_default=cfg.synthesize_dest,
                    collection=prefs.collection,
                    last=synthesize_result,
                ),
                synth_via=str(request.query_params.get("via") or "").strip() == "synthesize",
                poll_run=(run or "").strip(),
                error=err,
            ),
        )


    @app.post("/briefs/summarize")
    async def briefs_summarize(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        if not cfg.llm_enabled:
            return RedirectResponse(url=_page_url("/briefs", error="llm"), status_code=303)
        try:
            year_from = _optional_int(form.get("year_from"))
            year_to = _optional_int(form.get("year_to"))
        except ValueError:
            return RedirectResponse(url=_page_url("/briefs", error="year"), status_code=303)
        try:
            limit = _optional_int(form.get("limit"), positive=True)
            max_new = _optional_int(form.get("max_new"), positive=True)
        except ValueError:
            return RedirectResponse(url=_page_url("/briefs", error="limit"), status_code=303)
        try:
            dest = _parse_dest(form.get("dest"), cfg.summarize_dest)
        except ValueError:
            return RedirectResponse(url=_page_url("/briefs", error="dest"), status_code=303)
        order = str(form.get("order") or "").strip() or cfg.summarize_order
        if order not in SUMMARIZE_ORDERS:
            return RedirectResponse(url=_page_url("/briefs", error="order"), status_code=303)
        force = form.get("force") == "1"

        def work(cmd_id: str) -> None:
            jobs.summarize(
                cfg,
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

        cmd_id = commands.enqueue(cfg, "summarize", work)
        return RedirectResponse(url=_page_url("/briefs", run=cmd_id), status_code=303)


    @app.post("/briefs/synthesize")
    async def briefs_synthesize(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        raw_dest = str(form.get("dest") or "").strip()
        raw_limit = str(form.get("limit") or "").strip()
        raw_year_from = str(form.get("year_from") or "").strip()
        raw_year_to = str(form.get("year_to") or "").strip()
        force = form.get("force") == "1"

        def bounce(error: str) -> RedirectResponse:
            return RedirectResponse(
                url=_page_url(
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

        if not cfg.llm_enabled:
            return bounce("llm")
        dry_run = str(form.get("dry_run") or "1") != "0"
        try:
            year_from = _optional_int(form.get("year_from"))
            year_to = _optional_int(form.get("year_to"))
        except ValueError:
            return bounce("year")
        try:
            limit = _optional_int(form.get("limit"), positive=True)
        except ValueError:
            return bounce("limit")
        try:
            dest = _parse_dest(form.get("dest"), dest_for_form(cfg.synthesize_dest, prefs.collection))
        except ValueError:
            return bounce("dest")
        from ..config import wants_zotero

        if wants_zotero(dest) and not prefs.collection and not dry_run:
            return bounce("collection")

        def work(cmd_id: str) -> None:
            jobs.synthesize(
                cfg,
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
            cfg,
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
        return RedirectResponse(url=_page_url("/briefs", run=cmd_id), status_code=303)


    @app.get("/briefs/summary/{key}", response_class=HTMLResponse)
    def briefs_summary(request: Request, key: str):
        meta = summary_meta(cfg, key)
        if meta is None or safe_child(cfg.summaries_dir, f"{key}.html") is None:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        return templates.TemplateResponse(
            request,
            "brief_summary.html",
            ctx(
                request,
                "briefs",
                key=meta["name"],
                cite=meta["cite"],
                model=meta["model"],
            ),
        )


    @app.get("/briefs/report/{slug}", response_model=None)
    def briefs_report(slug: str):
        path = safe_child(cfg.reports_dir, f"{slug}.html")
        if path is None:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        return FileResponse(path, media_type="text/html; charset=utf-8")


    @app.get("/v1/runs/{cmd_id}/events", response_model=None)
    def run_events(cmd_id: str):
        if commands.read_command(cfg, cmd_id) is None:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        return StreamingResponse(
            commands.iter_command_status_events(cfg, cmd_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )


    @app.get("/v1/runs/{cmd_id}")
    def run_status(cmd_id: str) -> JSONResponse:
        rec = commands.read_command(cfg, cmd_id)
        if rec is None:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        return JSONResponse({"ok": True, **rec})


    @app.post("/v1/gui/noop")
    def gui_noop() -> JSONResponse:
        def work(cmd_id: str) -> None:
            jobs.run_noop(cfg, cmd_id)

        cmd_id = commands.enqueue(cfg, "noop", work)
        return JSONResponse({"id": cmd_id, "status": "queued"}, status_code=202)

