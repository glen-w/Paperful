"""Advanced Review page. Screening stays on disk. Library create needs a token."""

from __future__ import annotations

import hashlib
import time
import uuid

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..sr.identify import identified_ids, load_identification
from ..sr.protocol import load_protocol
from ..sr.screen import latest_decisions, load_screen_ledger
from ..sr.prisma import prisma_svg
from ..sr_cmd import review_counts, run_sr_import, run_sr_screen
from . import commands
from .context import UiContext


def _fingerprint(ui: UiContext, slug: str) -> str:
    from ..sr.protocol import review_dir

    path = review_dir(ui.cfg.state_dir, slug) / "screening.jsonl"
    if not path.is_file():
        return "empty"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def handle_page_review(
    ui: UiContext, request: Request, slug: str = "", error: str = ""
) -> HTMLResponse:
    slug = (slug or "default").strip() or "default"
    protocol = load_protocol(ui.cfg.state_dir, slug)
    try:
        counts = review_counts(ui.cfg, slug)
    except Exception:
        counts = {}
    decisions = latest_decisions(load_screen_ledger(ui.cfg.state_dir, slug))
    identified = identified_ids(load_identification(ui.cfg.state_dir, protocol))
    pending = [ident for ident in identified if ident not in decisions]
    token = ""
    for rec in commands.list_commands(ui.cfg, limit=20):
        if rec.get("verb") == "sr_import" and rec.get("review_token"):
            token = str(rec["review_token"])
            break
    return ui.templates.TemplateResponse(
        request,
        "review.html",
        ui.ctx(
            request,
            "review",
            slug=slug,
            protocol=protocol,
            counts=counts,
            pending=pending[:50],
            decisions=list(decisions.values())[:50],
            review_token=token,
            error=error,
        ),
    )


def handle_screen(ui: UiContext, request: Request, form: dict) -> RedirectResponse:
    slug = str(form.get("slug") or "default")
    identity = str(form.get("identity") or "").strip()
    decision = str(form.get("decision") or "")
    if not identity or decision not in {"include", "exclude", "maybe"}:
        return RedirectResponse(
            url=f"/review?slug={slug}&error=decision", status_code=303
        )
    run_sr_screen(
        ui.cfg,
        slug=slug,
        identity=identity,
        decision=decision,
        reason=str(form.get("reason") or ""),
        reviewer=str(form.get("reviewer") or "operator"),
    )
    return RedirectResponse(url=f"/review?slug={slug}", status_code=303)


def handle_preview(ui: UiContext, form: dict) -> RedirectResponse:
    slug = str(form.get("slug") or "default")
    cmd_id = uuid.uuid4().hex[:12]
    commands.write_command(
        ui.cfg,
        {
            "id": cmd_id,
            "verb": "sr_import",
            "status": "done",
            "created": time.time(),
            "finished": time.time(),
            "slug": slug,
        },
    )
    commands.create_review_token(
        ui.cfg,
        verb="sr_import",
        collection=str(form.get("collection") or ""),
        preset="",
        keys=[],
        fingerprint=_fingerprint(ui, slug),
        command_id=cmd_id,
        flags={
            "slug": slug,
            "path": str(form.get("path") or ""),
            "format": str(form.get("format") or "csv"),
            "collection": str(form.get("collection") or ""),
        },
    )
    return RedirectResponse(url=f"/review?slug={slug}", status_code=303)


def handle_apply(ui: UiContext, form: dict) -> RedirectResponse:
    slug = str(form.get("slug") or "default")
    token = str(form.get("review_token") or "")
    ok, msg = commands.consume_review(
        ui.cfg, token, fingerprint=_fingerprint(ui, slug), keys=None
    )
    if not ok:
        return RedirectResponse(
            url=f"/review?slug={slug}&error={msg or 'token'}", status_code=303
        )
    saved = commands.load_review(ui.cfg, token) or {}
    flags = saved.get("flags") or {}
    path = str(form.get("path") or flags.get("path") or "").strip()
    collection = str(form.get("collection") or flags.get("collection") or "")
    if path:
        run_sr_import(
            ui.cfg,
            slug=slug,
            path=path,
            fmt=str(form.get("format") or flags.get("format") or "csv"),
            apply=True,
            reviewer=str(form.get("reviewer") or "operator"),
            collection=collection,
        )
    elif collection:
        from ..library import LibraryError
        from ..sr.exchange import create_included_parents
        from ..sr.screen import latest_decisions, load_screen_ledger

        included = [
            row
            for row in latest_decisions(
                load_screen_ledger(ui.cfg.state_dir, slug)
            ).values()
            if row.get("decision") == "include"
        ]
        try:
            create_included_parents(ui.cfg, included, collection)
        except LibraryError:
            return RedirectResponse(
                url=f"/review?slug={slug}&error=library", status_code=303
            )
    return RedirectResponse(url=f"/review?slug={slug}", status_code=303)


def register_review(ui: UiContext) -> None:
    app = ui.app

    @app.get("/review/prisma.svg")
    def review_prisma(slug: str = "default") -> Response:
        counts = review_counts(ui.cfg, slug or "default")
        protocol = load_protocol(ui.cfg.state_dir, slug or "default")
        body = prisma_svg(counts, title=str(protocol.get("title") or slug or "PRISMA"))
        return Response(content=body, media_type="image/svg+xml")

    @app.get("/review", response_class=HTMLResponse)
    def page_review(request: Request, slug: str = "", error: str = "") -> HTMLResponse:
        return handle_page_review(ui, request, slug=slug, error=error)

    @app.post("/review/screen")
    async def review_screen(request: Request) -> RedirectResponse:
        form = dict(await request.form())
        return handle_screen(ui, request, form)

    @app.post("/review/preview")
    async def review_preview(request: Request) -> RedirectResponse:
        return handle_preview(ui, dict(await request.form()))

    @app.post("/review/apply")
    async def review_apply(request: Request) -> RedirectResponse:
        return handle_apply(ui, dict(await request.form()))
