"""Workbench HTTP routes (Advanced Suggest edits; CLI verb rewrite)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from . import commands, jobs
from .context import UiContext
from .pages import (
    ASK_ERROR_MESSAGES,
    command_by_id,
    last_job_result,
    list_recent_critiques,
)
from ..critique_extract import (
    ACCEPT,
    MAX_UPLOAD_BYTES,
    SUPPORTED,
    ExtractError,
    stage_bytes,
)


def _pack_markdown(cfg: Any, pack_dir: str) -> str:
    folder = Path(pack_dir)
    try:
        folder.resolve().relative_to((cfg.state_dir / "rewrites").resolve())
    except (ValueError, OSError):
        return ""
    md = folder / "pack.md"
    if not md.is_file():
        return ""
    try:
        return md.read_text(encoding="utf-8")
    except OSError:
        return ""


def _downloads(pack_dir: str) -> list[dict[str, str]]:
    folder = Path(pack_dir)
    if not folder.is_dir():
        return []
    out: list[dict[str, str]] = []
    for name in (
        "pack.md",
        "plan.json",
        "sidecar.md",
        "sidecar.txt",
        "tracked.docx",
        "tracked.pptx",
        "tracked.odt",
        "tracked.pdf",
    ):
        path = folder / name
        if path.is_file():
            out.append({"name": name, "path": str(path)})
    return out


def handle_page_rewrite(
    ui: UiContext, request: Request, run: str = "", error: str = ""
) -> HTMLResponse:
    result = last_job_result(ui.cfg, "rewrite", run)
    pack_md = ""
    pack_dir = str((result or {}).get("pack_dir") or "")
    if pack_dir:
        pack_md = _pack_markdown(ui.cfg, pack_dir)
    err = ASK_ERROR_MESSAGES.get(error, error)
    return ui.templates.TemplateResponse(
        request,
        "rewrite.html",
        ui.ctx(
            request,
            "rewrite",
            error=err,
            run_rec=command_by_id(ui.cfg, run) if run else None,
            poll_run=run,
            result=result,
            pack_md=pack_md,
            downloads=_downloads(pack_dir),
            recent=list_recent_critiques(ui.cfg),
            accept=ACCEPT,
            llm_on=bool(ui.cfg.llm_enabled),
            rewrite_areas=list(ui.cfg.rewrite_areas),
            rewrite_outputs=list(ui.cfg.rewrite_outputs),
            rewrite_comments=ui.cfg.rewrite_comments,
        ),
    )


async def handle_rewrite_run(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    pack_dir = str(form.get("pack_dir") or "").strip()
    comments = str(form.get("comments") or "").strip() or None
    areas = [str(v).strip() for v in form.getlist("area") if str(v).strip()]
    outputs = [str(v).strip() for v in form.getlist("output") if str(v).strip()]
    upload = form.get("file")
    staged: Path | None = None
    name = ""
    if upload is not None and getattr(upload, "filename", None):
        name = str(upload.filename)
        raw = await upload.read()  # type: ignore[union-attr]
        if raw:
            suffix = Path(name or "upload.bin").suffix.lower()
            if suffix not in SUPPORTED:
                return RedirectResponse(url="/rewrite?error=format", status_code=303)
            if len(raw) > MAX_UPLOAD_BYTES:
                return RedirectResponse(url="/rewrite?error=size", status_code=303)
            try:
                staged = stage_bytes(ui.cfg, raw, name)
            except ExtractError:
                return RedirectResponse(url="/rewrite?error=format", status_code=303)
    if not pack_dir:
        return RedirectResponse(url="/rewrite?error=target", status_code=303)
    try:
        folder = Path(pack_dir).resolve()
        folder.relative_to((ui.cfg.state_dir / "critiques").resolve())
    except (ValueError, OSError):
        return RedirectResponse(url="/rewrite?error=target", status_code=303)
    if not (folder / "pack.json").is_file():
        return RedirectResponse(url="/rewrite?error=target", status_code=303)

    def work(cmd_id: str) -> None:
        jobs.rewrite(
            ui.cfg,
            cmd_id,
            pack_dir=str(folder),
            file_path=staged,
            areas=areas or None,
            outputs=outputs or None,
            comments=comments,
        )

    cmd_id = commands.enqueue(
        ui.cfg,
        "rewrite",
        work,
        args={"pack_dir": str(folder), "upload": name},
    )
    return ui.after_job("/rewrite", cmd_id)


def handle_rewrite_download(
    ui: UiContext, name: str, pack_dir: str
) -> FileResponse | RedirectResponse:
    allowed = {
        "pack.md",
        "plan.json",
        "sidecar.md",
        "sidecar.txt",
        "tracked.docx",
        "tracked.pptx",
        "tracked.odt",
        "tracked.pdf",
    }
    if name not in allowed:
        return RedirectResponse(url="/rewrite?error=target", status_code=303)
    folder = Path(pack_dir)
    try:
        folder = folder.resolve()
        folder.relative_to((ui.cfg.state_dir / "rewrites").resolve())
    except (ValueError, OSError):
        return RedirectResponse(url="/rewrite?error=target", status_code=303)
    path = folder / name
    if not path.is_file():
        return RedirectResponse(url="/rewrite?error=target", status_code=303)
    return FileResponse(path, filename=name)


def register_rewrite(ui: UiContext) -> None:
    app = ui.app

    @app.get("/rewrite", response_class=HTMLResponse)
    def page_rewrite(request: Request, run: str = "", error: str = "") -> HTMLResponse:
        return handle_page_rewrite(ui, request=request, run=run, error=error)

    @app.post("/rewrite")
    async def rewrite_run(request: Request) -> RedirectResponse:
        return await handle_rewrite_run(ui, request=request)

    @app.get("/rewrite/download/{name}", response_model=None)
    def rewrite_download(
        name: str, pack_dir: str = ""
    ) -> FileResponse | RedirectResponse:
        return handle_rewrite_download(ui, name=name, pack_dir=pack_dir)
