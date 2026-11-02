"""Workbench HTTP routes (Discover web search)."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..config import Config
from . import commands, jobs
from .context import UiContext
from .discover_common import last_review_token
from .pages import newest_search_run
from .prefs import prefs_from_request


def _searxng_configured(cfg: Config) -> bool:
    from ..snowball.searxng import searxng_base_url

    return bool(searxng_base_url(cfg))


def handle_discover_search_meta(ui: UiContext) -> JSONResponse:
    from ..search.store import list_runs

    enabled = ui.cfg.ui_web_search != "off"
    return JSONResponse(
        {
            "ok": True,
            "enabled": enabled,
            "searxng": _searxng_configured(ui.cfg),
            "runs": list_runs(ui.cfg) if enabled else [],
        }
    )


def handle_discover_search(ui: UiContext, run_id: str = "") -> JSONResponse:
    from ..search.store import SearchError, load_run

    if ui.cfg.ui_web_search == "off":
        return JSONResponse({"ok": False, "error": "Web search is off."}, status_code=404)
    cleaned = (run_id or "").strip()
    if not cleaned:
        return JSONResponse({"ok": False, "error": "run_id required"}, status_code=400)
    try:
        bundle = load_run(ui.cfg, cleaned)
    except SearchError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
    return JSONResponse(
        {
            "ok": True,
            "schema": bundle.get("schema"),
            "run_id": bundle.get("run_id"),
            "meta": bundle.get("meta") or {},
            "candidates": bundle.get("candidates") or [],
            "summary": bundle.get("summary") or {},
        }
    )


async def handle_discover_search_run(
    ui: UiContext, request: Request
) -> RedirectResponse:
    if ui.cfg.ui_web_search == "off":
        return RedirectResponse(
            url=ui.page_url("/discover", tab="topic", error="Web search is off."),
            status_code=303,
        )
    if not _searxng_configured(ui.cfg):
        return RedirectResponse(
            url=ui.page_url(
                "/discover",
                tab="web",
                error="SearXNG is unset. Set [searxng].base_url or open Settings / System.",
            ),
            status_code=303,
        )
    form = await request.form()
    query = str(form.get("query") or "").strip()
    hosts = str(form.get("hosts") or "").strip()
    filetype = str(form.get("filetype") or "pdf").strip() or "pdf"
    try:
        max_hits = int(str(form.get("max") or ui.cfg.search_max or 20).strip() or "20")
    except ValueError:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="web", error="Max hits must be a whole number."),
            status_code=303,
        )
    if not query:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="web", error="Enter a search query."),
            status_code=303,
        )

    def work(cmd_id: str) -> None:
        from ..search.run import run_search
        from ..search.store import SearchError

        try:
            bundle = run_search(
                ui.cfg,
                [query],
                hosts=hosts,
                filetype=filetype,
                max_hits=max_hits,
            )
        except (SearchError, ValueError) as exc:
            raise RuntimeError(str(exc)) from exc
        jobs._attach_result(
            ui.cfg,
            cmd_id,
            {
                "run_id": bundle.get("run_id"),
                "path": bundle.get("path"),
                "kept": (bundle.get("summary") or {}).get("kept"),
            },
        )

    cmd_id = commands.enqueue(ui.cfg, "search", work)
    return ui.after_job("/discover", cmd_id, tab="web")


async def handle_discover_search_apply(
    ui: UiContext, request: Request
) -> RedirectResponse:
    from . import discover_jobs

    prefs = prefs_from_request(request)
    if ui.cfg.ui_web_search == "off":
        return RedirectResponse(
            url=ui.page_url("/discover", tab="topic", error="Web search is off."),
            status_code=303,
        )
    form = await request.form()
    run_id = str(form.get("run_id") or "").strip()
    preview = str(form.get("preview") or "").strip() in {"1", "true", "on"}
    urls = [str(v).strip() for v in form.getlist("url") if str(v).strip()]
    collection = str(prefs.collection or "").strip()
    if preview:
        if not collection:
            return RedirectResponse(
                url=ui.page_url(
                    "/discover", tab="web", error="Set the collection chip before adding hits."
                ),
                status_code=303,
            )

        def work(cmd_id: str) -> None:
            discover_jobs.search_apply_preview(
                ui.cfg, cmd_id, run_id=run_id, collection=collection, urls=urls
            )

        cmd_id = commands.enqueue(ui.cfg, "search_apply", work)
        return ui.after_job("/discover", cmd_id, tab="web")
    token = str(form.get("review_token") or "") or last_review_token(ui, "search_apply")
    ok, msg = discover_jobs.search_apply(ui.cfg, token=token, collection=collection)
    if not ok:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="web", error=msg or "preview first"),
            status_code=303,
        )
    return RedirectResponse(url=ui.page_url("/discover", tab="web"), status_code=303)


