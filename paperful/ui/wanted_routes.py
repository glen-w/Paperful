"""Workbench HTTP routes (wanted)."""

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

def register_wanted(ui: UiContext) -> None:
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

    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse(url="/wanted", status_code=302)


    def _wanted_token(verb: str) -> str:
        for rec in commands.list_commands(cfg, limit=30):
            if rec.get("verb") == verb and rec.get("review_token"):
                return str(rec["review_token"])
        return ""


    def _parse_int(raw: object) -> int | None:
        text = str(raw or "").strip()
        if not text:
            return None
        return int(text)


    def _wanted_run_flags(form: Any) -> dict[str, Any]:
        types = [t.strip() for t in str(form.get("item_type") or "").split(",") if t.strip()]
        return {
            "year_from": _parse_int(form.get("year_from")),
            "year_to": _parse_int(form.get("year_to")),
            "item_type": types,
            "limit": _parse_int(form.get("limit")),
            "retry_failed": form.get("retry_failed") == "1",
            "try_all": form.get("try_all") == "1",
            "upgrade_linked": form.get("upgrade_linked") == "1",
            "upgrade_snapshot": form.get("upgrade_snapshot") == "1",
            "browser_agent": form.get("browser_agent") == "1",
            "htmlpdf": form.get("htmlpdf") == "1",
        }


    def _pending_fill(data: dict[str, Any]) -> dict[str, Any]:
        """Discover output not yet in the scoped collection (read-only ledgers)."""
        from ..pending_fill import pending_fill

        dois = {
            str(r.get("doi") or "")
            for name in ("have", "held", "missing")
            for r in data.get(name, [])
        }
        try:
            return pending_fill(cfg, dois)
        except Exception:
            return {"rows": [], "total": 0, "by_source": {}}

    @app.get("/wanted", response_class=HTMLResponse)
    def page_wanted(request: Request, tab: str | None = None, error: str = "") -> HTMLResponse:
        from .pages import resolve_wanted_tab

        prefs = prefs_from_request(request)
        load_error = ""
        data = {
            "have": [],
            "held": [],
            "missing": [],
            "counts": {"have": 0, "held": 0, "missing": 0, "attach": 0},
        }
        if prefs.collection:
            try:
                data = _load_wanted(cfg, prefs.collection)
            except Exception as exc:
                load_error = str(exc)
        counts = data["counts"]
        pending = _pending_fill(data)
        tab = resolve_wanted_tab(tab, counts)
        bucket = data.get(tab, []) if tab in {"have", "held", "missing"} else data["missing"]
        per_page = library_per_page_from_request(request, cfg)
        persist_per_page = request.query_params.get("per_page") is not None
        page = library_page_from_request(request)
        order = wanted_order_from_request(request)
        filt = wanted_filter_from_request(request)
        query = wanted_query_from_request(request)
        rows, wanted_total, page, wanted_page_count = wanted_items_page(
            bucket,
            page=page,
            per_page=per_page,
            order=order,
            filt=filt,
            query=query,
        )
        page_sizes = library_page_size_options(cfg)
        wanted_pagination = pagination_meta(
            page=page,
            per_page=per_page,
            page_count=wanted_page_count,
            total=wanted_total,
            page_sizes=page_sizes,
        )

        def _wanted_qs(*, page_no: int | None = None, with_per_page: bool = False) -> dict[str, Any]:
            params: dict[str, Any] = {
                "tab": tab,
                "order": order if order != "title" else "",
                "filter": filt if filt != "all" else "",
                "q": query,
            }
            if with_per_page or persist_per_page:
                params["per_page"] = per_page
            if page_no is not None and int(page_no) > 1:
                params["page"] = page_no
            return params

        wanted_pagination.update(
            {
                "order": order,
                "filt": filt,
                "q": query,
                "orders": WANTED_ORDER_LABELS,
                "filter_options": WANTED_FILTER_LABELS,
                "prev_url": (
                    _page_url("/wanted", **_wanted_qs(page_no=page - 1, with_per_page=True))
                    if page > 1
                    else ""
                ),
                "next_url": (
                    _page_url("/wanted", **_wanted_qs(page_no=page + 1, with_per_page=True))
                    if page < wanted_page_count
                    else ""
                ),
                "tab_urls": {
                    name: _page_url("/wanted", **{**_wanted_qs(page_no=1), "tab": name})
                    for name in ("missing", "held", "have")
                },
            }
        )
        briefs = briefs_page_flags(cfg)
        coach = ""
        if not prefs.collection:
            coach = "Pick a collection in Library, then return here to preview missing PDFs."
        else:
            for row in _cached_doctor():
                code = str(row.get("code") or "")
                if code in {"zotero_down", "zotero_api_off"} and row.get("status") in {
                    "red",
                    "amber",
                }:
                    coach = next_step(code, str(row.get("detail") or ""))
                    break
        banner = load_error or error
        response = templates.TemplateResponse(
            request,
            "wanted.html",
            ctx(
                request,
                "wanted",
                tab=tab,
                rows=rows,
                counts=data["counts"],
                pending=pending,
                error=banner,
                coach=coach,
                briefs=briefs,
                dest_options=dest_options(),
                grab_token=_wanted_token("preview_run"),
                attach_mode=cfg.ui_attach_mode,
                show_auto_attach_setting=library_has_attached_pdf(cfg),
                attach_token=_wanted_token("attach"),
                recover_token=_wanted_token("recover"),
                wanted_pagination=wanted_pagination,
                job=job_view(
                    command_by_id(
                        cfg,
                        str(
                            request.query_params.get("run")
                            or request.query_params.get("poll")
                            or ""
                        ),
                    )
                ),
            ),
        )
        if persist_per_page:
            set_cookie(response, COOKIE_LIBRARY_PER_PAGE, str(per_page))
        return response


    @app.get("/wanted/report", response_model=None)
    def wanted_report(request: Request, format: str = "md"):
        """Read-only report cards: same stamps as the Wanted table."""
        from ..wanted_cards import render_markdown, render_misses_csv, report_cards
        from fastapi.responses import PlainTextResponse

        prefs = prefs_from_request(request)
        if not prefs.collection:
            return PlainTextResponse("Pick a collection first.", status_code=400)
        try:
            data = _load_wanted(cfg, prefs.collection)
        except Exception as exc:
            return PlainTextResponse(str(exc), status_code=502)
        report = report_cards(data, collection=prefs.collection)
        if format == "json":
            return JSONResponse(report)
        if format == "csv":
            return PlainTextResponse(
                render_misses_csv(report), media_type="text/csv; charset=utf-8"
            )
        return PlainTextResponse(
            render_markdown(report), media_type="text/markdown; charset=utf-8"
        )

    @app.post("/wanted/summarize")
    async def wanted_summarize(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        key = str(form.get("key") or "").strip()
        if not cfg.llm_enabled:
            return RedirectResponse(url="/wanted?error=llm", status_code=303)
        if not key:
            return RedirectResponse(url="/wanted", status_code=303)
        try:
            dest = _parse_dest(form.get("dest"), cfg.summarize_dest)
        except ValueError:
            return RedirectResponse(url="/wanted?error=dest", status_code=303)
        force = form.get("force") == "1"

        def work(cmd_id: str) -> None:
            jobs.summarize(
                cfg,
                cmd_id,
                collection=prefs.collection,
                year_from=None,
                year_to=None,
                limit=None,
                max_new=None,
                dest=dest,
                order=cfg.summarize_order,
                force=force,
                item_keys=[key],
            )

        cmd_id = commands.enqueue(cfg, "summarize_item", work)
        return RedirectResponse(url=f"/wanted?run={cmd_id}", status_code=303)


    @app.get("/item/{key}/summary", response_model=None)
    def item_summary(key: str):
        path = safe_child(cfg.summaries_dir, f"{key}.html")
        if path is None:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        return FileResponse(path, media_type="text/html; charset=utf-8")


    @app.post("/wanted/preview")
    async def wanted_preview(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        keys = [str(k) for k in form.getlist("keys")]
        try:
            flags = _wanted_run_flags(form) if prefs.advanced else {}
        except ValueError:
            return RedirectResponse(
                url="/wanted?error=Year and limit must be whole numbers.",
                status_code=303,
            )

        def work(cmd_id: str) -> None:
            jobs.preview_run(
                cfg,
                cmd_id,
                collection=prefs.collection,
                preset=prefs.preset,
                keys=keys or None,
                flags=flags,
            )

        cmd_id = commands.enqueue(cfg, "preview_run", work)
        resp = RedirectResponse(url=f"/wanted?poll={cmd_id}", status_code=303)
        return resp


    @app.post("/wanted/grab", response_model=None)
    async def wanted_grab(request: Request):
        prefs = prefs_from_request(request)
        form = await request.form()
        try:
            flags = _wanted_run_flags(form) if prefs.advanced else {}
        except ValueError:
            return RedirectResponse(
                url="/wanted?error=Year and limit must be whole numbers.",
                status_code=303,
            )
        posted = [str(k).strip() for k in form.getlist("keys") if str(k).strip()]
        review, why = jobs.matching_preview(
            cfg,
            collection=prefs.collection,
            preset=prefs.preset,
            posted_keys=posted,
            flags=flags,
            explicit_token=str(
                form.get("grab_review_token") or form.get("review_token") or ""
            ),
        )
        if review is None:
            return RedirectResponse(url=_page_url("/wanted", error=why), status_code=303)
        ok, msg = jobs.grab_run(cfg, token=str(review.get("token") or ""))
        if not ok:
            return RedirectResponse(url=_page_url("/wanted", error=msg), status_code=303)
        return RedirectResponse(url="/wanted", status_code=303)


    @app.post("/wanted/attach/preview")
    async def wanted_attach_preview(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        keys = [str(k) for k in form.getlist("keys")]
        from . import wanted_jobs

        def work(cmd_id: str) -> None:
            wanted_jobs.attach_preview(
                cfg,
                cmd_id,
                collection=prefs.collection,
                keys=keys or None,
                allow_mismatch=form.get("allow_mismatch") == "1",
                allow_short=form.get("allow_short") == "1",
            )

        cmd_id = commands.enqueue(cfg, "attach", work)
        return RedirectResponse(url=f"/wanted?run={cmd_id}", status_code=303)


    @app.post("/wanted/attach", response_model=None)
    async def wanted_attach(request: Request):
        form = await request.form()
        from . import wanted_jobs

        token = str(form.get("review_token") or "")
        if token:
            review = commands.load_review(cfg, token)
            if review is None or review.get("verb") != "attach":
                token = ""
        if token:
            ok, msg = wanted_jobs.attach_apply(cfg, token=token)
        else:
            prefs = prefs_from_request(request)
            keys = [str(k) for k in form.getlist("keys")]
            ok, msg, _n = jobs.attach_run(cfg, keys=keys, collection=prefs.collection)
        if not ok:
            return JSONResponse({"ok": False, "error": msg}, status_code=409)
        return RedirectResponse(url="/wanted", status_code=303)


    @app.post("/wanted/recover/preview")
    async def wanted_recover_preview(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        keys = [str(k) for k in form.getlist("keys")]
        from . import wanted_jobs

        try:
            recover_limit = _parse_int(form.get("limit"))
        except ValueError:
            return RedirectResponse(
                url="/wanted?error=Year and limit must be whole numbers.",
                status_code=303,
            )

        def work(cmd_id: str) -> None:
            wanted_jobs.recover_preview(
                cfg,
                cmd_id,
                collection=prefs.collection,
                keys=keys,
                from_last_run=form.get("from_last_run") == "1",
                from_last_run_mode=str(form.get("from_last_run_mode") or "browser_agent_miss"),
                limit=recover_limit,
            )

        cmd_id = commands.enqueue(cfg, "recover", work)
        return RedirectResponse(url=f"/wanted?run={cmd_id}", status_code=303)


    @app.post("/wanted/recover", response_model=None)
    async def wanted_recover(request: Request):
        form = await request.form()
        from . import wanted_jobs

        token = str(form.get("review_token") or "") or _wanted_token("recover")
        ok, msg = wanted_jobs.recover_apply(cfg, token=token)
        if not ok:
            return JSONResponse({"ok": False, "error": msg}, status_code=409)
        return RedirectResponse(url="/wanted", status_code=303)


    @app.post("/wanted/handoff")
    async def wanted_handoff(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        keys = [str(k) for k in form.getlist("keys")]
        from . import wanted_jobs

        def work(cmd_id: str) -> None:
            wanted_jobs.handoff_run(
                cfg,
                cmd_id,
                collection=prefs.collection,
                keys=keys or None,
                mode=str(form.get("mode") or "list"),
                include_doi_tabs=form.get("include_doi_tabs") == "1",
            )

        cmd_id = commands.enqueue(cfg, "handoff", work)
        return RedirectResponse(url=f"/wanted?run={cmd_id}", status_code=303)


    @app.post("/wanted/inbox/drain")
    async def wanted_inbox_drain(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        from . import wanted_jobs

        def work(cmd_id: str) -> None:
            wanted_jobs.inbox_drain(cfg, cmd_id, collection=prefs.collection)

        cmd_id = commands.enqueue(cfg, "inbox_drain", work)
        return RedirectResponse(url=f"/wanted?run={cmd_id}", status_code=303)


    @app.post("/wanted/reachout")
    async def wanted_reachout(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        keys = [str(k) for k in form.getlist("keys")]
        from . import wanted_jobs

        def work(cmd_id: str) -> None:
            wanted_jobs.reachout_run(
                cfg,
                cmd_id,
                collection=prefs.collection,
                keys=keys or None,
                non_oa_only=form.get("non_oa_only") == "1",
                lookup=form.get("lookup") == "1",
                handoff_mode=str(form.get("handoff_mode") or ""),
            )

        cmd_id = commands.enqueue(cfg, "reachout", work)
        return RedirectResponse(url=f"/wanted?run={cmd_id}", status_code=303)

