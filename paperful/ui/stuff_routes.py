"""Workbench HTTP routes (Advanced Stuff; extra library cites)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from . import commands, jobs
from .context import UiContext
from .pages import (
    ASK_ERROR_MESSAGES,
    ask_page_flags,
    command_by_id,
    last_job_result,
    list_recent_stuff,
    stuff_pack_markdown,
)
from .prefs import prefs_from_request
from ..critique_extract import (
    ACCEPT,
    MAX_UPLOAD_BYTES,
    SUPPORTED,
    ExtractError,
    stage_bytes,
)
from ..stuff import KNOWN_LANES, HONESTY_BANNER, resolve_k, resolve_lane


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


def _downloads(pack_dir: str) -> list[dict[str, str]]:
    folder = Path(pack_dir)
    if not folder.is_dir():
        return []
    out: list[dict[str, str]] = []
    for name in ("pack.md", "pack.json"):
        path = folder / name
        if path.is_file():
            out.append({"name": name, "path": str(path)})
    return out


def handle_page_stuff(
    ui: UiContext, request: Request, run: str = "", error: str = ""
) -> HTMLResponse:
    prefs = prefs_from_request(request)
    result = last_job_result(ui.cfg, "stuff", run)
    pack_md = ""
    pack_dir = str((result or {}).get("pack_dir") or "")
    if pack_dir:
        pack_md = stuff_pack_markdown(ui.cfg, pack_dir)
    err = ASK_ERROR_MESSAGES.get(error, error)
    flags = ask_page_flags(ui.cfg)
    try:
        lane_id = resolve_lane(ui.cfg, None)
    except ValueError:
        lane_id = "manuscript"
    return ui.templates.TemplateResponse(
        request,
        "stuff.html",
        ui.ctx(
            request,
            "stuff",
            error=err,
            error_code=error,
            run_rec=command_by_id(ui.cfg, run) if run else None,
            poll_run=run,
            result=result,
            pack_md=pack_md,
            downloads=_downloads(pack_dir),
            items=_picker_items(ui, prefs.collection),
            recent=list_recent_stuff(ui.cfg),
            accept=ACCEPT,
            honesty=HONESTY_BANNER,
            stuff_lane=lane_id,
            stuff_k=resolve_k(ui.cfg, None),
            stuff_lanes=list(KNOWN_LANES),
            rag_on=bool(flags.get("rag_on")),
            can_search=bool(flags.get("can_search")),
        ),
    )


async def handle_stuff_run(ui: UiContext, request: Request) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    item_key = str(form.get("item_key") or "").strip()
    raw_lane = str(form.get("lane") or "").strip()
    raw_k = str(form.get("k") or "").strip()
    upload = form.get("file")
    data: bytes | None = None
    name = ""
    if upload is not None and getattr(upload, "filename", None):
        name = str(upload.filename)
        raw = await upload.read()  # type: ignore[union-attr]
        data = raw if raw else None
    if bool(item_key) == bool(data):
        return RedirectResponse(url="/stuff?error=target", status_code=303)
    if not ui.cfg.rag_enabled:
        return RedirectResponse(url="/stuff?error=rag", status_code=303)
    try:
        lane_id = resolve_lane(ui.cfg, raw_lane or None)
    except ValueError:
        return RedirectResponse(url="/stuff?error=lane", status_code=303)
    per_k: int | None = None
    if raw_k:
        try:
            per_k = int(raw_k)
        except ValueError:
            return RedirectResponse(url="/stuff?error=k", status_code=303)
        if per_k < 1:
            return RedirectResponse(url="/stuff?error=k", status_code=303)
    staged: Path | None = None
    if data is not None:
        suffix = Path(name or "upload.bin").suffix.lower()
        if suffix not in SUPPORTED:
            return RedirectResponse(url="/stuff?error=format", status_code=303)
        if len(data) > MAX_UPLOAD_BYTES:
            return RedirectResponse(url="/stuff?error=size", status_code=303)
        try:
            staged = stage_bytes(ui.cfg, data, name)
        except ExtractError:
            return RedirectResponse(url="/stuff?error=format", status_code=303)
        try:
            staged.resolve().relative_to(
                (ui.cfg.state_dir / "critiques" / "uploads").resolve()
            )
        except ValueError:
            return RedirectResponse(url="/stuff?error=format", status_code=303)

    def work(cmd_id: str) -> None:
        jobs.stuff(
            ui.cfg,
            cmd_id,
            item_key=item_key,
            staged_path=staged,
            collection=prefs.collection,
            lane=lane_id,
            k=per_k,
        )

    cmd_id = commands.enqueue(
        ui.cfg,
        "stuff",
        work,
        args={"item_key": item_key, "upload": name, "lane": lane_id, "k": per_k},
    )
    return ui.after_job("/stuff", cmd_id)


def handle_stuff_download(
    ui: UiContext, name: str, pack_dir: str
) -> FileResponse | RedirectResponse:
    allowed = {"pack.md", "pack.json"}
    if name not in allowed:
        return RedirectResponse(url="/stuff?error=target", status_code=303)
    folder = Path(pack_dir)
    try:
        folder = folder.resolve()
        folder.relative_to((ui.cfg.state_dir / "stuff").resolve())
    except (ValueError, OSError):
        return RedirectResponse(url="/stuff?error=target", status_code=303)
    path = folder / name
    if not path.is_file():
        return RedirectResponse(url="/stuff?error=target", status_code=303)
    return FileResponse(path, filename=name)


def register_stuff(ui: UiContext) -> None:
    app = ui.app

    @app.get("/stuff", response_class=HTMLResponse)
    def page_stuff(request: Request, run: str = "", error: str = "") -> HTMLResponse:
        return handle_page_stuff(ui, request=request, run=run, error=error)

    @app.post("/stuff")
    async def stuff_run(request: Request) -> RedirectResponse:
        return await handle_stuff_run(ui, request=request)

    @app.get("/stuff/download/{name}", response_model=None)
    def stuff_download(
        name: str, pack_dir: str = ""
    ) -> FileResponse | RedirectResponse:
        return handle_stuff_download(ui, name=name, pack_dir=pack_dir)
