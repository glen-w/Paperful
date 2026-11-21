"""Workbench HTTP routes (Advanced Peer review)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import commands, jobs
from .context import UiContext
from .page_common import picker_title
from .pages import (
    ASK_ERROR_MESSAGES,
    command_by_id,
    peer_review_pack_markdown,
    last_job_result,
    list_recent_peer_reviews,
)
from .prefs import prefs_from_request
from ..peer_review_extract import (
    ACCEPT,
    MAX_UPLOAD_BYTES,
    SUPPORTED,
    ExtractError,
    stage_bytes,
)
from ..peer_review_lanes import resolve_peer_review_lanes


def _default_lanes(cfg: Any) -> tuple[str, ...]:
    return resolve_peer_review_lanes(cfg)


def _picker_items(ui: UiContext, collection: str) -> list[dict[str, Any]]:
    items, _manifest = jobs.load_scope_items_cached(ui.cfg, collection)
    rows: list[dict[str, Any]] = []
    for it in items[:300]:
        rows.append(
            {
                "key": it.key,
                "title": picker_title(it.title, it.key),
                "year": getattr(it, "year", None),
            }
        )
    return rows


def handle_page_peer_review(
    ui: UiContext, request: Request, run: str = "", error: str = ""
) -> HTMLResponse:
    prefs = prefs_from_request(request)
    run_rec = command_by_id(ui.cfg, run) if run else None
    result = last_job_result(ui.cfg, "peer-review", run)
    pack_md = ""
    pack_dir = str((result or {}).get("pack_dir") or "")
    if pack_dir:
        pack_md = peer_review_pack_markdown(ui.cfg, pack_dir)
    err = ASK_ERROR_MESSAGES.get(error, error)
    return ui.templates.TemplateResponse(
        request,
        "peer_review.html",
        ui.ctx(
            request,
            "peer-review",
            error=err,
            run_rec=run_rec,
            poll_run=run,
            result=result,
            pack_md=pack_md,
            items=_picker_items(ui, prefs.collection),
            recent=list_recent_peer_reviews(ui.cfg),
            accept=ACCEPT,
            llm_on=bool(ui.cfg.llm_enabled),
            peer_review_llm=bool(ui.cfg.peer_review_llm),
            peer_review_advanced=bool(ui.cfg.peer_review_advanced),
            peer_review_lanes=list(_default_lanes(ui.cfg)),
            grobid_enabled=bool(ui.cfg.grobid_enabled),
        ),
    )


async def handle_peer_review_run(ui: UiContext, request: Request) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    item_key = str(form.get("item_key") or "").strip()
    apply = form.get("apply") == "1"
    llm = form.get("llm") == "1"
    ai_model = form.get("ai_model") == "1"
    vale = form.get("vale") == "1"
    forensics = form.get("forensics") == "1"
    advanced = form.get("advanced") == "1"
    raw_lanes = [str(v).strip() for v in form.getlist("lane") if str(v).strip()]
    if llm and "reviewers" not in raw_lanes:
        raw_lanes.append("reviewers")
    if advanced and "marg" not in raw_lanes:
        raw_lanes.append("marg")
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
        return RedirectResponse(url="/peer-review?error=target", status_code=303)
    staged: Path | None = None
    if data is not None:
        suffix = Path(name or "upload.bin").suffix.lower()
        if suffix not in SUPPORTED:
            return RedirectResponse(url="/peer-review?error=format", status_code=303)
        if len(data) > MAX_UPLOAD_BYTES:
            return RedirectResponse(url="/peer-review?error=size", status_code=303)
        try:
            staged = stage_bytes(ui.cfg, data, name)
        except ExtractError:
            return RedirectResponse(url="/peer-review?error=format", status_code=303)
        try:
            staged.resolve().relative_to(
                (ui.cfg.state_dir / "peer-reviews" / "uploads").resolve()
            )
        except ValueError:
            return RedirectResponse(url="/peer-review?error=format", status_code=303)
    if apply and staged is not None:
        apply = False

    def work(cmd_id: str) -> None:
        jobs.peer_review(
            ui.cfg,
            cmd_id,
            item_key=item_key,
            staged_path=staged,
            collection=prefs.collection,
            apply=apply,
            llm=llm,
            ai_model=ai_model,
            vale=vale,
            forensics=forensics,
            advanced=advanced,
            lanes=raw_lanes,
            grobid=grobid,
            force=force,
            show_dismissed=show_dismissed,
        )

    cmd_id = commands.enqueue(
        ui.cfg,
        "peer-review",
        work,
        args={"item_key": item_key, "upload": name, "apply": apply},
    )
    return ui.after_job("/peer-review", cmd_id)


def register_peer_review(ui: UiContext) -> None:
    app = ui.app

    @app.get("/peer-review", response_class=HTMLResponse)
    def page_peer_review(request: Request, run: str = "", error: str = "") -> HTMLResponse:
        return handle_page_peer_review(ui, request=request, run=run, error=error)

    @app.post("/peer-review")
    async def peer_review_run(request: Request) -> RedirectResponse:
        return await handle_peer_review_run(ui, request=request)
