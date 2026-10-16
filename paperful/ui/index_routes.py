"""Workbench HTTP routes (index)."""

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

def register_index(ui: UiContext) -> None:
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

    @app.get("/ask", response_class=HTMLResponse)
    def page_ask(
        request: Request,
        thread: str = "",
        run: str = "",
        error: str = "",
    ) -> HTMLResponse:
        flags = ask_page_flags(cfg)
        if flags["can_ask"]:
            msg = (
                "Ask questions over PDFs already copied to disk. "
                "Ingest on Index builds the search index from the mirror."
            )
            coach = ""
        elif flags["rag_on"] and flags["llm_on"]:
            msg = "The index is empty. Ingest first, then this page can answer."
            coach = "Ingest the current collection (or the whole mirror), then return here."
        elif flags["rag_on"]:
            msg = (
                "Ingest is on. Turn on [llm] in config.toml for Ask "
                "(Settings does not toggle it)."
            )
            coach = "Ask needs [llm] in config.toml. Settings does not turn it on."
        else:
            msg = (
                "Turn on [rag] and [llm] in config.toml to Ask. "
                "Settings does not toggle them."
            )
            coach = "Ask needs [rag] and [llm] in config.toml. Settings does not turn them on."
        active = (thread or "").strip()
        turns: list[dict[str, str]] = []
        result: dict[str, Any] = {}
        if active:
            turns = thread_for_display(cfg, active)
            result = last_ask_result(cfg, active)
        return templates.TemplateResponse(
            request,
            "ask.html",
            ctx(
                request,
                "ask",
                page_title="Ask",
                message=msg,
                coach=coach,
                flags=flags,
                threads=list_threads(cfg),
                turns=turns,
                active_thread_id=active,
                last_result=result,
                ingest_result=last_job_result(cfg, "rag_ingest", run),
                ask_result=last_job_result(cfg, "ask", run),
                batch_result=last_job_result(cfg, "ask_batch", run),
                packs=list_ask_packs(cfg),
                saved_prompts=list_saved_prompts(cfg),
                rag_config_prompt=cfg.rag_prompt or "",
                dest_options=dest_options(),
                rag_dest=cfg.rag_dest or "disk",
                focus_options=focus_options(),
                year_from="",
                year_to="",
                poll_run=(run or "").strip(),
                error=ASK_ERROR_MESSAGES.get(error, error),
            ),
        )


    @app.get("/index", response_class=HTMLResponse, response_model=None)
    def page_index(
        request: Request,
        thread: str = "",
        run: str = "",
        error: str = "",
        q: str = "",
        k: str = "",
        year_from: str = "",
        year_to: str = "",
    ) -> HTMLResponse:
        active = (thread or "").strip()
        if active:
            return RedirectResponse(
                url=_page_url("/ask", thread=active, run=run, error=error),
                status_code=303,
            )
        flags = ask_page_flags(cfg)
        if flags["rag_on"] and flags["llm_on"]:
            msg = (
                "Build and search the local PDF index. Ingest from the mirror, "
                "then Search here or Ask in the nav. Scope follows the collection chip."
            )
        elif flags["rag_on"]:
            msg = (
                "Ingest and search are on. Turn on [llm] in config.toml "
                "for Ask (Settings does not toggle it)."
            )
        else:
            msg = (
                "Turn on [rag] in config.toml to ingest and search. "
                "Ask also needs [llm]. Settings does not toggle them."
            )
        hits: list[dict[str, Any]] = []
        search_q = (q or "").strip()
        search_error = ""
        if search_q and flags["can_search"]:
            try:
                y_from = _optional_int(year_from)
                y_to = _optional_int(year_to)
            except ValueError:
                search_error = ASK_ERROR_MESSAGES["year"]
            else:
                try:
                    top_k = _optional_int(k, positive=True)
                except ValueError:
                    search_error = ASK_ERROR_MESSAGES["limit"]
            if not search_error:
                try:
                    from ..llm.preflight import validate_embedder
                    from ..rag.index import Index, ledger_path
                    from ..rag.ledger import Ledger
                    from ..rag.retrieve import scope_keys, search

                    prefs = prefs_from_request(request)
                    index = Index.open(cfg)
                    ledger = Ledger(ledger_path(cfg))
                    keys = scope_keys(
                        ledger,
                        collections=[prefs.collection] if prefs.collection else None,
                        year_from=y_from,
                        year_to=y_to,
                    )
                    found = search(
                        cfg,
                        search_q,
                        k=top_k,
                        keys=keys,
                        embedder=validate_embedder(cfg),
                        index=index,
                        ledger=ledger,
                    )
                    for hit in found:
                        text = hit.text or ""
                        if len(text) > 280:
                            text = text[:277] + "…"
                        hits.append(
                            {
                                "score": f"{hit.score:.3f}",
                                "item_key": hit.item_key,
                                "title": hit.title,
                                "pages": hit.pages,
                                "year": hit.year,
                                "text": text,
                            }
                        )
                except Exception as exc:
                    search_error = str(exc) or ASK_ERROR_MESSAGES["search"]
        err = ASK_ERROR_MESSAGES.get(error, error) or search_error
        return templates.TemplateResponse(
            request,
            "index.html",
            ctx(
                request,
                "index",
                page_title="Index",
                message=msg,
                enabled=flags["rag_on"],
                flags=flags,
                status=flags["status"],
                ingest_result=last_job_result(cfg, "rag_ingest", run),
                questions_result=last_job_result(cfg, "rag_questions", run),
                answered_result=last_job_result(cfg, "rag_answered", run),
                answered_packs=list_answered_packs(cfg),
                saved_prompts=list_saved_prompts(cfg),
                rag_config_prompt=cfg.rag_prompt or "",
                extract_questions_llm=cfg.rag_extract_questions_llm,
                hits=hits,
                search_q=search_q,
                search_k=k,
                year_from=year_from,
                year_to=year_to,
                poll_run=(run or "").strip(),
                error=err,
                synthesize_result=last_job_result(cfg, "synthesize", run),
                reports=list_html_stems(cfg.reports_dir),
                synth_dest_options=dest_options(),
                synth_dest=dest_for_form(
                    cfg.synthesize_dest, prefs_from_request(request).collection
                ),
            ),
        )


    @app.post("/index/synthesize")
    async def index_synthesize(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        if not cfg.llm_enabled:
            return RedirectResponse(url=_page_url("/index", error="llm"), status_code=303)
        dry_run = str(form.get("dry_run") or "1") != "0"
        try:
            year_from = _optional_int(form.get("year_from"))
            year_to = _optional_int(form.get("year_to"))
            limit = _optional_int(form.get("limit"), positive=True)
        except ValueError:
            return RedirectResponse(url=_page_url("/index", error="limit"), status_code=303)
        try:
            dest = _parse_dest(
                form.get("dest"), dest_for_form(cfg.synthesize_dest, prefs.collection)
            )
        except ValueError:
            return RedirectResponse(url=_page_url("/index", error="dest"), status_code=303)
        from ..config import wants_zotero

        if wants_zotero(dest) and not prefs.collection and not dry_run:
            return RedirectResponse(url=_page_url("/index", error="collection"), status_code=303)
        force = form.get("force") == "1"

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
        return RedirectResponse(url=_page_url("/index", run=cmd_id), status_code=303)


    @app.get("/index/report/{slug}", response_model=None)
    def index_report(slug: str):
        path = safe_child(cfg.reports_dir, f"{slug}.html")
        if path is None:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        return FileResponse(path, media_type="text/html; charset=utf-8")


    @app.post("/index/ingest")
    async def index_ingest(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        next_path = "/ask" if str(form.get("next") or "").strip() == "ask" else "/index"
        if not cfg.rag_enabled:
            return RedirectResponse(url=_page_url(next_path, error="rag"), status_code=303)
        dry_run = str(form.get("dry_run") or "1") != "0"
        try:
            year_from = _optional_int(form.get("year_from"))
            year_to = _optional_int(form.get("year_to"))
        except ValueError:
            return RedirectResponse(url=_page_url(next_path, error="year"), status_code=303)
        try:
            limit = _optional_int(form.get("limit"), positive=True)
        except ValueError:
            return RedirectResponse(url=_page_url(next_path, error="limit"), status_code=303)

        def work(cmd_id: str) -> None:
            jobs.rag_ingest(
                cfg,
                cmd_id,
                collection=prefs.collection,
                year_from=year_from,
                year_to=year_to,
                limit=limit,
                dry_run=dry_run,
            )

        cmd_id = commands.enqueue(cfg, "rag_ingest", work)
        return RedirectResponse(url=_page_url(next_path, run=cmd_id), status_code=303)


    @app.post("/index/search")
    async def index_search(request: Request) -> RedirectResponse:
        form = await request.form()
        q = str(form.get("q") or "").strip()
        if not q:
            return RedirectResponse(url=_page_url("/index", error="empty"), status_code=303)
        return RedirectResponse(
            url=_page_url(
                "/index",
                q=q,
                k=str(form.get("k") or "").strip(),
                year_from=str(form.get("year_from") or "").strip(),
                year_to=str(form.get("year_to") or "").strip(),
            ),
            status_code=303,
        )


    @app.post("/ask")
    @app.post("/index/ask")
    async def index_ask(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        question = str(form.get("question") or "").strip()
        thread_id = str(form.get("thread_id") or "").strip()
        focus_raw = str(form.get("focus") or "").strip() or None

        def _redir(*, err: str = "", tid: str = "", run: str = "") -> RedirectResponse:
            return RedirectResponse(
                url=_page_url("/ask", thread=tid, run=run, error=err),
                status_code=303,
            )

        if not (cfg.rag_enabled and cfg.llm_enabled):
            return _redir(err="disabled", tid=thread_id)
        if not question:
            return _redir(err="empty", tid=thread_id)
        try:
            year_from = _optional_int(form.get("year_from"))
            year_to = _optional_int(form.get("year_to"))
            scope = parse_rag_scope(
                form,
                prefs.collection,
                year_from=year_from,
                year_to=year_to,
            )
            resolved = await _resolved_prompt(form)
        except ValueError as exc:
            msg = str(exc).lower()
            if "year" in msg or "integer" in msg:
                return _redir(err="year", tid=thread_id)
            if "top_k" in msg or "positive" in msg:
                return _redir(err="limit", tid=thread_id)
            if "type" in msg or "item type" in msg:
                return _redir(err="type", tid=thread_id)
            return _redir(err="prompt", tid=thread_id)
        try:
            from ..rag.prompt import parse_focus

            parse_focus(focus_raw if focus_raw is not None else cfg.rag_focus)
        except ValueError:
            return _redir(err="focus", tid=thread_id)
        if not thread_id:
            from ..rag.thread import new_id

            thread_id = new_id()
        _save_prompt_if_asked(form, resolved)

        def work(cmd_id: str) -> None:
            jobs.ask_turn(
                cfg,
                cmd_id,
                question=question,
                thread_id=thread_id,
                collection=scope.collection,
                year_from=scope.year_from,
                year_to=scope.year_to,
                focus=focus_raw,
                top_k=scope.top_k,
                item_keys=scope.item_keys or None,
                item_types=scope.item_types,
                prompt_path=resolved.prompt_path,
                prompt_text=resolved.prompt_text,
            )

        cmd_id = commands.enqueue(cfg, "ask", work)
        return _redir(tid=thread_id, run=cmd_id)


    @app.post("/ask/batch")
    @app.post("/index/ask-batch")
    async def index_ask_batch(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        if not (cfg.rag_enabled and cfg.llm_enabled):
            return RedirectResponse(url=_page_url("/ask", error="disabled"), status_code=303)
        try:
            q_upload = await _upload_bytes(form, "questions_upload")
            questions = read_questions_upload(form, q_upload)
            year_from = _optional_int(form.get("year_from"))
            year_to = _optional_int(form.get("year_to"))
            scope = parse_rag_scope(
                form,
                prefs.collection,
                year_from=year_from,
                year_to=year_to,
                include_force=True,
            )
            resolved = await _resolved_prompt(form)
        except ValueError as exc:
            msg = str(exc).lower()
            if "upload" in msg or "too large" in msg:
                return RedirectResponse(url=_page_url("/ask", error="upload"), status_code=303)
            if "top_k" in msg or "positive" in msg:
                return RedirectResponse(url=_page_url("/ask", error="limit"), status_code=303)
            if "type" in msg:
                return RedirectResponse(url=_page_url("/ask", error="type"), status_code=303)
            if "year" in msg:
                return RedirectResponse(url=_page_url("/ask", error="year"), status_code=303)
            return RedirectResponse(url=_page_url("/ask", error="prompt"), status_code=303)
        if not questions:
            return RedirectResponse(url=_page_url("/ask", error="questions"), status_code=303)
        try:
            dest = _parse_dest(form.get("dest"), cfg.rag_dest or "disk")
        except ValueError:
            return RedirectResponse(url=_page_url("/ask", error="dest"), status_code=303)
        apply = form.get("apply") == "1"
        if apply and (dest == "disk" or not prefs.collection):
            return RedirectResponse(url=_page_url("/ask", error="apply"), status_code=303)
        focus_raw = str(form.get("focus") or "").strip() or None
        try:
            from ..rag.prompt import parse_focus

            parse_focus(focus_raw if focus_raw is not None else cfg.rag_focus)
        except ValueError:
            return RedirectResponse(url=_page_url("/ask", error="focus"), status_code=303)
        _save_prompt_if_asked(form, resolved)

        def work(cmd_id: str) -> None:
            jobs.ask_batch(
                cfg,
                cmd_id,
                questions=questions,
                collection=scope.collection,
                year_from=scope.year_from,
                year_to=scope.year_to,
                focus=focus_raw,
                dest=dest,
                apply=apply,
                top_k=scope.top_k,
                item_keys=scope.item_keys or None,
                item_types=scope.item_types,
                prompt_path=resolved.prompt_path,
                prompt_text=resolved.prompt_text,
                force=scope.force,
            )

        cmd_id = commands.enqueue(cfg, "ask_batch", work)
        return RedirectResponse(url=_page_url("/ask", run=cmd_id), status_code=303)


    @app.post("/index/rag-questions")
    async def index_rag_questions(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        if not cfg.rag_enabled:
            return RedirectResponse(url=_page_url("/index", error="rag"), status_code=303)
        dry_run = str(form.get("dry_run") or "1") != "0"
        whole_library = form.get("whole_library") == "1"
        use_llm = form.get("use_llm") == "1"
        try:
            year_from = _optional_int(form.get("year_from"))
            year_to = _optional_int(form.get("year_to"))
            limit = _optional_int(form.get("limit"), positive=True)
            scope = parse_rag_scope(
                form,
                prefs.collection,
                year_from=year_from,
                year_to=year_to,
            )
        except ValueError:
            return RedirectResponse(url=_page_url("/index", error="year"), status_code=303)
        if not scope_has_target(scope, whole_library=whole_library):
            return RedirectResponse(url=_page_url("/index", error="scope"), status_code=303)

        def work(cmd_id: str) -> None:
            jobs.rag_questions(
                cfg,
                cmd_id,
                collection=scope.collection,
                whole_library=whole_library,
                year_from=scope.year_from,
                year_to=scope.year_to,
                item_keys=scope.item_keys or None,
                item_types=scope.item_types,
                use_llm=use_llm,
                limit=limit,
                dry_run=dry_run,
            )

        cmd_id = commands.enqueue(cfg, "rag_questions", work)
        return RedirectResponse(url=_page_url("/index", run=cmd_id), status_code=303)


    @app.post("/index/rag-answered")
    async def index_rag_answered(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        if not (cfg.rag_enabled and cfg.llm_enabled):
            return RedirectResponse(url=_page_url("/index", error="disabled"), status_code=303)
        mode = str(form.get("question_mode") or "text").strip()
        after_item = str(form.get("after_item") or "").strip() or None
        try:
            year_from = _optional_int(form.get("year_from"))
            year_to = _optional_int(form.get("year_to"))
            scope = parse_rag_scope(
                form,
                prefs.collection,
                year_from=year_from,
                year_to=year_to,
                include_force=True,
            )
        except ValueError:
            return RedirectResponse(url=_page_url("/index", error="year"), status_code=303)
        questions: list[tuple[str, str, int | None]] = []
        try:
            if mode == "extract":
                from ..rag.answered import questions_from_extract

                extract_keys = scope.item_keys if scope.item_keys else None
                questions = questions_from_extract(cfg, item_keys=extract_keys)
            else:
                upload = await _upload_bytes(form, "answered_upload")
                if mode == "upload" or upload:
                    if not upload:
                        return RedirectResponse(
                            url=_page_url("/index", error="upload"), status_code=303
                        )
                    from ..snowball.seeds import parse_seed_lines

                    lines = parse_seed_lines(
                        upload.decode("utf-8", errors="replace")
                    )
                    questions = [(q, "", None) for q in lines]
                else:
                    from ..snowball.seeds import parse_seed_lines

                    lines = parse_seed_lines(str(form.get("answered_questions") or ""))
                    questions = [(q, "", None) for q in lines]
        except (ValueError, UnicodeError):
            return RedirectResponse(url=_page_url("/index", error="upload"), status_code=303)
        if not questions:
            return RedirectResponse(url=_page_url("/index", error="questions"), status_code=303)

        def work(cmd_id: str) -> None:
            jobs.rag_answered(
                cfg,
                cmd_id,
                collection=scope.collection,
                year_from=scope.year_from,
                year_to=scope.year_to,
                item_keys=scope.item_keys or None,
                item_types=scope.item_types,
                questions=questions,
                after_item=after_item,
                top_k=scope.top_k,
                force=scope.force,
            )

        cmd_id = commands.enqueue(cfg, "rag_answered", work)
        return RedirectResponse(url=_page_url("/index", run=cmd_id), status_code=303)


    @app.get("/index/batch/{stamp}", response_model=None)
    def index_batch_pack(stamp: str):
        from ..rag.batch import batch_dir

        path = safe_child(batch_dir(cfg), stamp, "answers.md")
        if path is None:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        return FileResponse(path, media_type="text/plain; charset=utf-8")


    @app.get("/index/answered/{stamp}", response_model=None)
    def index_answered_pack(stamp: str):
        from ..rag.answered import answered_dir

        path = safe_child(answered_dir(cfg), stamp, "pack.md")
        if path is None:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        return FileResponse(path, media_type="text/plain; charset=utf-8")

