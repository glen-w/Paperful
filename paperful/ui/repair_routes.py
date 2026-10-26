"""Workbench HTTP routes (repair)."""

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


def _review_tokens_for(ui: UiContext, prefix: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in commands.list_commands(ui.cfg, limit=40):
        verb = str(c.get("verb") or "")
        token = str(c.get("review_token") or "")
        if not token or not verb.startswith(prefix):
            continue
        short = verb[len(prefix) :]
        if short and short not in out:
            out[short] = token
    return out


def _repair_flags(form: Any) -> dict[str, Any]:
    return {
        "overwrite": form.get("overwrite") == "1",
        "apply_medium": form.get("apply_medium") == "1",
        "phase": str(form.get("phase") or "all"),
        "fix_broken": form.get("fix_broken") == "1",
        "merge_files": form.get("merge_files") == "1",
        "rename": form.get("rename") == "1",
        "link": form.get("link") == "1",
        "attach": form.get("attach") == "1",
    }


def _mirror_flags(form: Any) -> dict[str, Any]:
    pdfs = str(form.get("pdfs") or "").strip()
    return {
        "full": form.get("full") == "1",
        "pdfs": pdfs,
        "accept_gone": form.get("accept_gone") == "1",
    }


def handle_page_repair(
    ui: UiContext, request: Request, run: str = "", error: str = ""
) -> HTMLResponse:
    run_rec = command_by_id(ui.cfg, run) if run else None
    return ui.templates.TemplateResponse(
        request,
        "repair.html",
        ui.ctx(
            request,
            "repair",
            queues=repair_queues(ui.cfg),
            tokens=_review_tokens_for(ui, "repair_"),
            message="",
            run_rec=run_rec,
            poll_run=run,
            error=error,
        ),
    )


async def handle_repair_preview_route(
    ui: UiContext, request: Request
) -> RedirectResponse:
    from .repair_mirror_jobs import GuiScopeError

    prefs = prefs_from_request(request)
    form = await request.form()
    verb = str(form.get("verb") or "dedupe")
    if verb not in {
        "lint",
        "screen",
        "fix-metadata",
        "dedupe",
        "versions",
        "attachments",
        "ocr",
    }:
        return RedirectResponse(url="/repair?error=verb", status_code=303)
    if not prefs.collection:
        return RedirectResponse(url="/repair?error=collection", status_code=303)
    overwrite = form.get("overwrite") == "1"
    apply_medium = form.get("apply_medium") == "1"
    surgery = {
        "fix_broken": form.get("fix_broken") == "1",
        "merge_files": form.get("merge_files") == "1",
        "rename": form.get("rename") == "1",
        "link": form.get("link") == "1",
        "attach": form.get("attach") == "1",
        "force_retry": form.get("force_retry") == "1",
        "auto_ignore_failures": form.get("auto_ignore_failures") == "1",
    }

    def work(cmd_id: str) -> None:
        try:
            jobs.repair_preview(
                ui.cfg,
                cmd_id,
                verb=verb,
                collection=prefs.collection,
                overwrite=overwrite,
                apply_medium=apply_medium,
                surgery=surgery,
            )
        except GuiScopeError as exc:
            rec = commands.read_command(ui.cfg, cmd_id) or {}
            rec["status"] = "failed"
            rec["error"] = str(exc)
            commands.write_command(ui.cfg, rec)
            raise

    cmd_id = commands.enqueue(ui.cfg, f"repair_{verb}", work)
    return RedirectResponse(url=f"/repair?run={cmd_id}", status_code=303)


async def handle_repair_apply_route(
    ui: UiContext, request: Request
) -> JSONResponse | RedirectResponse:
    form = await request.form()
    token = str(form.get("review_token") or "")
    if not token:
        return JSONResponse(
            {"ok": False, "error": "missing review token"}, status_code=409
        )
    ok, msg = jobs.repair_apply(ui.cfg, token=token)
    if not ok:
        return JSONResponse({"ok": False, "error": msg}, status_code=409)
    return RedirectResponse(url="/repair", status_code=303)


def handle_page_mirror(
    ui: UiContext, request: Request, run: str = "", error: str = ""
) -> HTMLResponse:
    run_rec = command_by_id(ui.cfg, run) if run else None
    return ui.templates.TemplateResponse(
        request,
        "mirror.html",
        ui.ctx(
            request,
            "mirror",
            verbs=MIRROR_VERBS,
            message="",
            run_rec=run_rec,
            poll_run=run,
            error=error,
        ),
    )


async def handle_mirror_preview_route(
    ui: UiContext, request: Request
) -> RedirectResponse:
    from .repair_mirror_jobs import GuiScopeError

    prefs = prefs_from_request(request)
    form = await request.form()
    verb = str(form.get("verb") or "sync")
    if verb not in set(MIRROR_VERBS):
        return RedirectResponse(url="/mirror?error=verb", status_code=303)
    scoped = verb in {"snapshot", "restore"}
    if scoped and not prefs.collection:
        return RedirectResponse(url="/mirror?error=collection", status_code=303)
    pdfs = str(form.get("pdfs") or "lazy")
    accept_gone = form.get("accept_gone") == "1"

    def work(cmd_id: str) -> None:
        try:
            jobs.mirror_preview(
                ui.cfg,
                cmd_id,
                verb=verb,
                collection=prefs.collection,
                pdfs=pdfs,
                accept_gone=accept_gone,
            )
        except GuiScopeError as exc:
            rec = commands.read_command(ui.cfg, cmd_id) or {}
            rec["status"] = "failed"
            rec["error"] = str(exc)
            commands.write_command(ui.cfg, rec)
            raise

    cmd_id = commands.enqueue(ui.cfg, f"mirror_{verb.replace(' ', '_')}", work)
    return RedirectResponse(url=f"/mirror?run={cmd_id}", status_code=303)


async def handle_mirror_apply_route(
    ui: UiContext, request: Request
) -> JSONResponse | RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    verb = str(form.get("verb") or "")
    token = str(form.get("review_token") or "")
    if not token:
        return JSONResponse(
            {"ok": False, "error": "missing review token"}, status_code=409
        )
    ok, msg = jobs.mirror_apply(ui.cfg, token=token, collection=prefs.collection)
    if not ok:
        return JSONResponse({"ok": False, "error": msg}, status_code=409)
    return RedirectResponse(url="/mirror", status_code=303)


def register_repair(ui: UiContext) -> None:
    app = ui.app

    @app.get("/repair", response_class=HTMLResponse)
    def page_repair(request: Request, run: str = "", error: str = "") -> HTMLResponse:
        return handle_page_repair(ui, request=request, run=run, error=error)

    @app.post("/repair/preview")
    async def repair_preview_route(request: Request) -> RedirectResponse:
        return await handle_repair_preview_route(ui, request=request)

    @app.post("/repair/apply", response_model=None)
    async def repair_apply_route(request: Request) -> JSONResponse | RedirectResponse:
        return await handle_repair_apply_route(ui, request=request)

    @app.get("/mirror", response_class=HTMLResponse)
    def page_mirror(request: Request, run: str = "", error: str = "") -> HTMLResponse:
        return handle_page_mirror(ui, request=request, run=run, error=error)

    @app.post("/mirror/preview")
    async def mirror_preview_route(request: Request) -> RedirectResponse:
        return await handle_mirror_preview_route(ui, request=request)

    @app.post("/mirror/apply", response_model=None)
    async def mirror_apply_route(request: Request) -> JSONResponse | RedirectResponse:
        return await handle_mirror_apply_route(ui, request=request)
