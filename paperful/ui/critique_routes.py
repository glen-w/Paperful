"""Workbench HTTP routes (Advanced Critique)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import commands, jobs
from .context import UiContext
from .pages import (
    ASK_ERROR_MESSAGES,
    command_by_id,
    critique_pack_markdown,
    last_job_result,
    list_recent_critiques,
)
from .prefs import prefs_from_request
from ..critique_extract import (
    ACCEPT,
    MAX_UPLOAD_BYTES,
    SUPPORTED,
    ExtractError,
    stage_bytes,
)


def _picker_items(ui: UiContext, collection: str) -> list[dict[str, Any]]:
    items, _manifest = jobs._load_scope_items(ui.cfg, collection)
    rows: list[dict[str, Any]] = []
    for it in items[:300]:
        rows.append(
            {
                "key": it.key,
                "title": it.title or it.key,
                "year": getattr(it, "year", None),
            }
        )
    return rows


def handle_page_critique(
    ui: UiContext, request: Request, run: str = "", error: str = ""
) -> HTMLResponse:
    prefs = prefs_from_request(request)
    run_rec = command_by_id(ui.cfg, run) if run else None
    result = last_job_result(ui.cfg, "critique", run)
    pack_md = ""
    pack_dir = str((result or {}).get("pack_dir") or "")
    if pack_dir:
        pack_md = critique_pack_markdown(ui.cfg, pack_dir)
    err = ASK_ERROR_MESSAGES.get(error, error)
    return ui.templates.TemplateResponse(
        request,
        "critique.html",
        ui.ctx(
            request,
            "critique",
            error=err,
            run_rec=run_rec,
            poll_run=run,
            result=result,
            pack_md=pack_md,
            items=_picker_items(ui, prefs.collection),
            recent=list_recent_critiques(ui.cfg),
            accept=ACCEPT,
            llm_on=bool(ui.cfg.llm_enabled),
            critique_llm=bool(ui.cfg.critique_llm),
            critique_advanced=bool(ui.cfg.critique_advanced),
            grobid_enabled=bool(ui.cfg.grobid_enabled),
        ),
    )


async def handle_critique_run(ui: UiContext, request: Request) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    item_key = str(form.get("item_key") or "").strip()
    apply = form.get("apply") == "1"
    llm = form.get("llm") == "1"
    ai_model = form.get("ai_model") == "1"
    vale = form.get("vale") == "1"
    advanced = form.get("advanced") == "1"
    grobid = form.get("grobid") == "1"
    force = form.get("force") == "1"
    show_dismissed = form.get("show_dismissed") == "1"
    upload = form.get("file")
    data: bytes | None = None
    name = ""
    if upload is not None and getattr(upload, "filename", None):
        name = str(upload.filename)
        raw = await upload.read()  # type: ignore[union-attr]
        data = raw if raw else None
    if bool(item_key) == bool(data):
        return RedirectResponse(url="/critique?error=target", status_code=303)
    staged: Path | None = None
    if data is not None:
        suffix = Path(name or "upload.bin").suffix.lower()
        if suffix not in SUPPORTED:
            return RedirectResponse(url="/critique?error=format", status_code=303)
        if len(data) > MAX_UPLOAD_BYTES:
            return RedirectResponse(url="/critique?error=size", status_code=303)
        try:
            staged = stage_bytes(ui.cfg, data, name)
        except ExtractError:
            return RedirectResponse(url="/critique?error=format", status_code=303)
        try:
            staged.resolve().relative_to(
                (ui.cfg.state_dir / "critiques" / "uploads").resolve()
            )
        except ValueError:
            return RedirectResponse(url="/critique?error=format", status_code=303)
    if apply and staged is not None:
        apply = False

    def work(cmd_id: str) -> None:
        jobs.critique(
            ui.cfg,
            cmd_id,
            item_key=item_key,
            staged_path=staged,
            collection=prefs.collection,
            apply=apply,
            llm=llm,
            ai_model=ai_model,
            vale=vale,
            advanced=advanced,
            grobid=grobid,
            force=force,
            show_dismissed=show_dismissed,
        )

    cmd_id = commands.enqueue(
        ui.cfg,
        "critique",
        work,
        args={"item_key": item_key, "upload": name, "apply": apply},
    )
    return ui.after_job("/critique", cmd_id)


def register_critique(ui: UiContext) -> None:
    app = ui.app

    @app.get("/critique", response_class=HTMLResponse)
    def page_critique(request: Request, run: str = "", error: str = "") -> HTMLResponse:
        return handle_page_critique(ui, request=request, run=run, error=error)

    @app.post("/critique")
    async def critique_run(request: Request) -> RedirectResponse:
        return await handle_critique_run(ui, request=request)
