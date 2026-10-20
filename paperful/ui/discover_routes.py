"""Workbench HTTP routes (discover)."""

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
    snowball_stop_view,
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

def register_discover(ui: UiContext) -> None:
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

    def _last_review_token(verb: str) -> str:
        for rec in commands.list_commands(cfg, limit=20):
            if rec.get("verb") == verb and rec.get("review_token"):
                return str(rec["review_token"])
        return ""

    def _safe_aw_suggestions(active: str) -> list[dict[str, Any]]:
        if not active:
            return []
        try:
            return authorwatch_suggestion_rows(cfg, active)
        except Exception:
            return []

    @app.get("/discover", response_class=HTMLResponse)
    def page_discover(
        request: Request,
        list_name: str = "",
        error: str = "",
        run: str = "",
        watch_name: str = "",
        compare_run: str = "",
    ) -> HTMLResponse:
        run_id, candidates = newest_snowball_queue(cfg)
        stop_pending, stop_note = snowball_stop_view(cfg, run_id)
        active_list = (list_name or "followed").strip()
        people: list[dict[str, Any]] = []
        if active_list:
            try:
                people = authorwatch_people_rows(cfg, active_list)
            except Exception:
                people = []
        return templates.TemplateResponse(
            request,
            "discover.html",
            ctx(
                request,
                "discover",
                run_id=run_id,
                candidates=candidates,
                stop_pending=stop_pending,
                stop_note=stop_note,
                following=following_lists(cfg),
                inbox=authorwatch_inbox_rows(cfg),
                aw_lists=authorwatch_lists(cfg),
                aw_list=active_list,
                aw_people=people,
                aw_suggestions=_safe_aw_suggestions(active_list),
                profiles=list_snowball_profiles(cfg),
                deferred_run=snowball_deferred_run_id(cfg),
                snowball_token=_last_review_token("snowball_apply"),
                aw_token=_last_review_token("authorwatch_apply"),
                ingest_token=_last_review_token("ingest_dois"),
                note=(
                    last_job_result(cfg, "snowball_briefing")
                    or last_job_result(cfg, "snowball_digest")
                    or last_job_result(cfg, "authorwatch_briefing")
                    or last_job_result(cfg, "refs_gap")
                    or last_job_result(cfg, "authors")
                ),
                job=job_view(command_by_id(cfg, (run or "").strip())),
                poll_run=(run or "").strip(),
                error=error,
                map_watch_name=(watch_name or "").strip(),
                map_compare_run=(compare_run or "").strip(),
            ),
        )


    @app.post("/discover/topic")
    async def discover_topic(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        payload = parse_discover_topic(form, advanced=prefs.advanced)

        def work(cmd_id: str) -> None:
            jobs.snowball_run(cfg, cmd_id, payload=payload, collection=prefs.collection)

        cmd_id = commands.enqueue(cfg, f"snowball_{payload.kind}", work)
        return _after_job("/discover", cmd_id)


    @app.post("/discover/profile-save")
    async def discover_profile_save(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        name = str(form.get("profile_name") or "").strip()
        if not name:
            return RedirectResponse(url="/discover?error=profile", status_code=303)
        from .snowball_form import profile_body_from_payload
        from ..snowball.profile import save_profile
        from ..snowball.command import SnowballError

        payload = parse_discover_topic(form, advanced=True)
        try:
            body = profile_body_from_payload(payload, collection=prefs.collection)
            save_profile(cfg, name, body, force=form.get("force") == "1")
        except (SnowballError, ValueError) as exc:
            return RedirectResponse(
                url=f"/discover?error={str(exc)[:80]}", status_code=303
            )
        return RedirectResponse(url="/discover", status_code=303)


    @app.post("/discover/refs-gap")
    async def discover_refs_gap(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)

        def work(cmd_id: str) -> None:
            from ..agent_ops import run_refs_gap

            result = run_refs_gap(cfg, prefs.collection)
            rec = commands.read_command(cfg, cmd_id) or {}
            rec["result"] = result
            commands.write_command(cfg, rec)

        cmd_id = commands.enqueue(cfg, "refs_gap", work)
        return _after_job("/discover", cmd_id)


    @app.post("/discover/ingest-preview")
    async def discover_ingest_preview(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        pack_path = str(form.get("pack_path") or "").strip()
        upload = form.get("file")
        dest = cfg.state_dir / "gui" / "uploads"
        dest.mkdir(parents=True, exist_ok=True)
        source_path = ""
        if upload is not None and getattr(upload, "filename", None):
            path = dest / Path(str(upload.filename)).name
            path.write_bytes(await upload.read())
            source_path = str(path)
        elif pack_path:
            source_path = pack_path

        def work(cmd_id: str) -> None:
            from . import discover_jobs

            discover_jobs.ingest_preview(
                cfg,
                cmd_id,
                collection=prefs.collection,
                source_path=source_path,
            )

        cmd_id = commands.enqueue(cfg, "ingest_dois", work)
        return _after_job("/discover", cmd_id)


    @app.post("/discover/ingest-apply", response_model=None)
    async def discover_ingest_apply(request: Request):
        prefs = prefs_from_request(request)
        form = await request.form()
        from . import discover_jobs

        token = str(form.get("review_token") or "") or _last_review_token("ingest_dois")
        ok, msg = discover_jobs.ingest_apply(
            cfg, token=token, collection=prefs.collection
        )
        if not ok:
            return JSONResponse({"ok": False, "error": msg}, status_code=409)
        return RedirectResponse(url="/discover", status_code=303)


    @app.post("/discover/authors")
    async def discover_authors(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        try:
            min_count = int(form.get("min_count") or 2)
            max_authors = int(form.get("max_authors") or 15)
        except ValueError:
            return RedirectResponse(
                url="/discover?error=Counts must be whole numbers.",
                status_code=303,
            )

        def work(cmd_id: str) -> None:
            from rich.console import Console

            from ..authors_cmd import run_authors

            run_authors(
                Console(quiet=True, file=None),
                collection=[prefs.collection] if prefs.collection else [],
                library=not bool(prefs.collection),
                year_from=None,
                year_to=None,
                item_type=[],
                min_count=min_count,
                max_authors=max_authors,
                apply=form.get("apply") == "1",
                profile=None,
                run_config=None,
                config=cfg.config_path,
                fmt="json",
            )
            rec = commands.read_command(cfg, cmd_id) or {}
            rec["result"] = {"apply": form.get("apply") == "1"}
            commands.write_command(cfg, rec)

        cmd_id = commands.enqueue(cfg, "authors", work)
        return _after_job("/discover", cmd_id)


    @app.post("/discover/packs-promote")
    async def discover_packs_promote(request: Request) -> RedirectResponse:
        form = await request.form()
        slug = str(form.get("slug") or "").strip()
        if not slug:
            return RedirectResponse(url="/discover?error=slug", status_code=303)

        def work(cmd_id: str) -> None:
            from ..snowball.preflight import promote_pack

            path = promote_pack(cfg, slug)
            rec = commands.read_command(cfg, cmd_id) or {}
            rec["result"] = {"path": str(path)}
            commands.write_command(cfg, rec)

        cmd_id = commands.enqueue(cfg, "packs_promote", work)
        return _after_job("/discover", cmd_id)


    @app.post("/discover/follow")
    async def discover_follow(request: Request) -> RedirectResponse:
        form = await request.form()
        orcid = str(form.get("orcid") or "").strip()
        list_name = str(form.get("list_name") or "followed").strip()
        backfill = str(form.get("backfill_from") or "").strip() or None
        if not orcid:
            return RedirectResponse(url="/discover?error=orcid", status_code=303)

        def work(cmd_id: str) -> None:
            jobs.follow_person(
                cfg,
                cmd_id,
                orcid=orcid,
                list_name=list_name,
                backfill_from=backfill,
            )

        cmd_id = commands.enqueue(cfg, "authorwatch_run", work)
        return _after_job("/discover", cmd_id)


    @app.post("/discover/apply-preview")
    async def discover_apply_preview(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        kind = str(form.get("kind") or "snowball")
        run_id = str(form.get("run_id") or "")
        list_name = str(form.get("list_name") or "followed")

        def work(cmd_id: str) -> None:
            jobs.discover_apply_preview(
                cfg,
                cmd_id,
                kind=kind,
                run_id=run_id,
                list_name=list_name,
                collection=prefs.collection,
            )

        verb = "authorwatch_apply" if kind == "authorwatch" else "snowball_apply"
        cmd_id = commands.enqueue(cfg, verb, work)
        return _after_job("/discover", cmd_id)


    @app.post("/discover/apply", response_model=None)
    async def discover_apply(request: Request):
        prefs = prefs_from_request(request)
        form = await request.form()
        kind = str(form.get("kind") or "snowball")
        run_id = str(form.get("run_id") or "")
        list_name = str(form.get("list_name") or "followed")
        token = str(form.get("review_token") or "")
        if not token:
            token = _last_review_token(
                "authorwatch_apply" if kind == "authorwatch" else "snowball_apply"
            )
        ok, msg = jobs.discover_apply_consume(
            cfg,
            token=token,
            kind=kind,
            run_id=run_id,
            list_name=list_name,
            collection=prefs.collection,
        )
        if not ok:
            return JSONResponse({"ok": False, "error": msg}, status_code=409)
        return RedirectResponse(url="/wanted", status_code=303)


    @app.post("/discover/check-again")
    async def discover_check(request: Request) -> RedirectResponse:
        form = await request.form()
        kind = str(form.get("kind") or "")
        name = str(form.get("name") or "")

        def work(cmd_id: str) -> None:
            if kind == "person":
                from ..authorwatch import run_list

                run_list(cfg, name, console=jobs._quiet_console())
            elif kind == "topic":
                from ..snowball.watch import run_watch

                run_watch(cfg, name, console=jobs._quiet_console())

        cmd_id = commands.enqueue(cfg, "check_again", work)
        return _after_job("/discover", cmd_id)


    @app.post("/discover/keep")
    async def discover_keep(request: Request):
        from ..snowball.citation_graph import CitationGraphError, graph_for_run

        form = await request.form()
        run_id = str(form.get("run_id") or "")
        doi = str(form.get("doi") or "")
        keep = str(form.get("keep") or "1") == "1"
        wants_json = str(form.get("format") or "") == "json"
        accept = (request.headers.get("accept") or "").lower()
        if "application/json" in accept:
            wants_json = True
        if run_id and doi:
            jobs.set_snowball_keep(cfg, run_id, [doi], keep)
        if wants_json:
            if not run_id:
                return JSONResponse({"ok": False, "error": "Missing run."}, status_code=400)
            try:
                graph = graph_for_run(cfg.state_dir, run_id)
            except CitationGraphError as exc:
                status = 404 if "queue" in str(exc).lower() else 400
                return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)
            return JSONResponse({"ok": True, "graph": graph, "doi": doi, "keep": keep})
        return RedirectResponse(url="/discover", status_code=303)

    def _graph_overlay_context(watch_name: str, compare_run_id: str) -> tuple[set[str] | None, set[str] | None]:
        from ..snowball.citation_graph import valid_run_id
        from ..snowball.queue import load_queue
        from ..snowball.watch import load_seen

        watch_seen: set[str] | None = None
        compare_ids: set[str] | None = None
        if watch_name.strip():
            try:
                watch_seen = load_seen(cfg, watch_name.strip())
            except Exception:
                watch_seen = set()
        if compare_run_id.strip() and valid_run_id(compare_run_id.strip()):
            try:
                _, rows = load_queue(cfg.state_dir, compare_run_id.strip())
                compare_ids = {row.identity for row in rows}
            except FileNotFoundError:
                compare_ids = set()
        return watch_seen, compare_ids

    @app.get("/discover/graph")
    def discover_graph(
        run_id: str = "",
        watch_name: str = "",
        compare_run: str = "",
    ) -> JSONResponse:
        from ..snowball.citation_graph import CitationGraphError, graph_for_run

        watch_seen, compare_ids = _graph_overlay_context(watch_name, compare_run)
        try:
            graph = graph_for_run(
                cfg.state_dir,
                run_id,
                watch_seen=watch_seen,
                compare_ids=compare_ids,
            )
        except CitationGraphError as exc:
            status = 404 if "queue" in str(exc).lower() else 400
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)
        return JSONResponse(graph)

    @app.post("/discover/graph/repair")
    async def discover_graph_repair(request: Request) -> JSONResponse:
        from ..snowball.citation_graph import CitationGraphError, repair_queue_links
        from ..snowball.command import _openalex_client
        from ..snowball.openalex import OpenAlexBudgetExceeded

        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        run_id = str(body.get("run_id") or "")
        try:
            graph = repair_queue_links(cfg.state_dir, run_id, _openalex_client(cfg))
        except CitationGraphError as exc:
            status = 404 if "queue" in str(exc).lower() else 400
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)
        except OpenAlexBudgetExceeded as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=429)
        return JSONResponse(graph)

    @app.post("/discover/graph/halo")
    async def discover_graph_halo(request: Request) -> JSONResponse:
        from ..identity import LibraryFingerprint
        from ..mirror import items_in_mirror
        from ..snowball.citation_graph import CitationGraphError, library_halo
        from ..snowball.command import _openalex_client
        from ..snowball.openalex import OpenAlexBudgetExceeded
        from ..snowball.queue import load_queue

        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        run_id = str(body.get("run_id") or "")
        node_id = str(body.get("node_id") or "")
        try:
            dest, rows = load_queue(cfg.state_dir, run_id)
        except FileNotFoundError:
            return JSONResponse({"ok": False, "error": "No queue for that run."}, status_code=404)
        target = next((row for row in rows if row.identity == node_id), None)
        if target is None:
            return JSONResponse({"ok": False, "error": "That paper is not in this queue."}, status_code=400)
        items = items_in_mirror(cfg.out_dir)
        fp = LibraryFingerprint.from_items(items)
        library_dois = set(fp.by_doi.keys())
        try:
            overlay = library_halo(_openalex_client(cfg), target, library_dois)
        except CitationGraphError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except OpenAlexBudgetExceeded as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=429)
        return JSONResponse({"ok": True, **overlay})

    @app.post("/discover/graph/expand")
    async def discover_graph_expand(request: Request) -> JSONResponse:
        from ..snowball.citation_graph import CitationGraphError, expand_queue
        from ..snowball.command import _openalex_client
        from ..snowball.openalex import OpenAlexBudgetExceeded

        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        run_id = str(body.get("run_id") or "")
        node_id = str(body.get("node_id") or "")
        direction = str(body.get("direction") or "both")
        try:
            graph = expand_queue(
                cfg.state_dir,
                run_id,
                node_id,
                direction,
                _openalex_client(cfg),
            )
        except CitationGraphError as exc:
            status = 404 if "queue" in str(exc).lower() else 400
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)
        except OpenAlexBudgetExceeded as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=429)
        return JSONResponse(graph)


    @app.post("/discover/watch")
    async def discover_watch(request: Request) -> RedirectResponse:
        form = await request.form()
        name = str(form.get("watch_name") or "topic-watch").strip()
        profile = str(form.get("profile") or "").strip()
        if not profile:
            return RedirectResponse(url="/discover?error=watch", status_code=303)
        from ..snowball.watch import save_watch

        try:
            save_watch(cfg, name, profile)
        except Exception:
            return RedirectResponse(url="/discover?error=watch", status_code=303)
        return RedirectResponse(url="/discover", status_code=303)


    @app.post("/discover/continue")
    async def discover_continue(request: Request) -> RedirectResponse:
        form = await request.form()
        run_id = str(form.get("run_id") or "").strip()
        if not run_id:
            return RedirectResponse(url="/discover", status_code=303)

        def work(cmd_id: str) -> None:
            from ..snowball.command import SnowballError, run_continue

            try:
                run_continue(cfg, run_id, console=jobs._quiet_console())
            except SnowballError as exc:
                rec = commands.read_command(cfg, cmd_id) or {}
                rec["status"] = "failed"
                rec["error"] = str(exc)
                commands.write_command(cfg, rec)
                raise

        cmd_id = commands.enqueue(cfg, "snowball_continue", work)
        return _after_job("/discover", cmd_id)


    @app.post("/discover/resume")
    async def discover_resume(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        run_id = str(form.get("run_id") or snowball_deferred_run_id(cfg)).strip()
        if not run_id:
            return RedirectResponse(url="/discover", status_code=303)

        def work(cmd_id: str) -> None:
            from ..snowball.command import SnowballRequest, run_resume

            req = SnowballRequest(gate="dry-run", collection=prefs.collection or "")
            run_resume(cfg, run_id, req, console=jobs._quiet_console())

        cmd_id = commands.enqueue(cfg, "snowball_resume", work)
        return _after_job("/discover", cmd_id)


    @app.post("/discover/profile-run")
    async def discover_profile_run(request: Request) -> RedirectResponse:
        form = await request.form()
        profile = str(form.get("profile") or "").strip()
        if not profile:
            return RedirectResponse(url="/discover", status_code=303)

        def work(cmd_id: str) -> None:
            from ..snowball.command import (
                SnowballError,
                run_collection,
                run_doi,
                run_hybrid,
                run_orcid,
                run_search,
            )
            from ..snowball.profile import (
                composed_query_from_profile,
                load_profile,
                orcids_from_profile,
                request_from_profile,
            )

            console = jobs._quiet_console()
            raw = load_profile(cfg, profile)
            req = request_from_profile(raw, cfg)
            mode = str(raw.get("mode") or "")
            if mode == "search":
                run_search(cfg, composed_query_from_profile(raw), req, console=console)
            elif mode == "hybrid":
                run_hybrid(cfg, composed_query_from_profile(raw), req, console=console)
            elif mode == "doi":
                dois = [str(x) for x in (raw.get("dois") or [])]
                run_doi(cfg, dois, req, console=console)
            elif mode == "orcid":
                run_orcid(cfg, orcids_from_profile(raw), req, console=console)
            elif mode == "collection":
                seed = str(raw.get("seed_collection") or raw.get("collection") or "").strip()
                run_collection(cfg, seed, req, console=console)
            else:
                raise SnowballError(f"Profile {profile!r} has unknown mode.")

        cmd_id = commands.enqueue(cfg, "snowball_profile", work)
        return _after_job("/discover", cmd_id)


    def _maybe_file_note(html: str, apply: bool, collection: str) -> str:
        if not apply:
            return ""
        from . import discover_jobs

        return discover_jobs.file_frontier_note(cfg, html, collection)


    @app.post("/discover/briefing")
    async def discover_briefing(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        run_id = str(form.get("run_id") or "").strip()
        apply_note = form.get("apply") == "1"
        if not run_id:
            return RedirectResponse(url="/discover", status_code=303)

        def work(cmd_id: str) -> None:
            from ..snowball.briefing import write_run_briefing

            briefing = write_run_briefing(cfg, run_id)
            note_key = _maybe_file_note(briefing.html, apply_note, prefs.collection)
            jobs._attach_result(
                cfg,
                cmd_id,
                {
                    "path": str(briefing.path),
                    "markdown": briefing.markdown[:4000],
                    "note_key": note_key,
                },
            )

        cmd_id = commands.enqueue(cfg, "snowball_briefing", work)
        return _after_job("/discover", cmd_id)


    @app.post("/discover/digest")
    async def discover_digest(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        run_id = str(form.get("run_id") or "").strip()
        apply_note = form.get("apply") == "1"
        if not run_id:
            return RedirectResponse(url="/discover", status_code=303)

        def work(cmd_id: str) -> None:
            from ..snowball.digest import write_run_digest

            digest = write_run_digest(cfg, run_id)
            note_key = _maybe_file_note(digest.html, apply_note, prefs.collection)
            jobs._attach_result(
                cfg,
                cmd_id,
                {
                    "path": str(digest.path),
                    "markdown": digest.markdown[:4000],
                    "note_key": note_key,
                },
            )

        cmd_id = commands.enqueue(cfg, "snowball_digest", work)
        return _after_job("/discover", cmd_id)


    @app.post("/discover/watch-briefing")
    async def discover_watch_briefing(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        name = str(form.get("name") or "").strip()
        apply_note = form.get("apply") == "1"
        if not name:
            return RedirectResponse(url="/discover", status_code=303)

        def work(cmd_id: str) -> None:
            from ..snowball.briefing import write_watch_briefing

            briefing = write_watch_briefing(cfg, name)
            note_key = _maybe_file_note(briefing.html, apply_note, prefs.collection)
            jobs._attach_result(
                cfg,
                cmd_id,
                {
                    "path": str(briefing.path),
                    "markdown": briefing.markdown[:4000],
                    "note_key": note_key,
                },
            )

        cmd_id = commands.enqueue(cfg, "watch_briefing", work)
        return _after_job("/discover", cmd_id)


    @app.post("/discover/watch-digest")
    async def discover_watch_digest(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        name = str(form.get("name") or "").strip()
        apply_note = form.get("apply") == "1"
        if not name:
            return RedirectResponse(url="/discover", status_code=303)

        def work(cmd_id: str) -> None:
            from ..snowball.digest import write_watch_digest

            digest = write_watch_digest(cfg, name)
            note_key = _maybe_file_note(digest.html, apply_note, prefs.collection)
            jobs._attach_result(
                cfg,
                cmd_id,
                {
                    "path": str(digest.path),
                    "markdown": digest.markdown[:4000],
                    "note_key": note_key,
                },
            )

        cmd_id = commands.enqueue(cfg, "watch_digest", work)
        return _after_job("/discover", cmd_id)


    @app.post("/discover/aw/save")
    async def discover_aw_save(request: Request) -> RedirectResponse:
        form = await request.form()
        name = str(form.get("name") or "").strip()
        if not name:
            return RedirectResponse(url="/discover", status_code=303)
        from ..authorwatch import save_list

        save_list(cfg, name)
        return RedirectResponse(url=_page_url("/discover", list_name=name), status_code=303)


    @app.post("/discover/aw/add")
    async def discover_aw_add(request: Request) -> RedirectResponse:
        form = await request.form()
        name = str(form.get("list_name") or "followed").strip()
        orcid = str(form.get("orcid") or "").strip()
        display = str(form.get("display_name") or "").strip()
        affiliation = str(form.get("affiliation") or "").strip()
        from ..authorwatch import add_person

        add_person(
            cfg,
            name,
            orcid=orcid,
            display_name=display,
            affiliation_host=affiliation,
        )
        return RedirectResponse(url=_page_url("/discover", list_name=name), status_code=303)


    @app.post("/discover/aw/remove")
    async def discover_aw_remove(request: Request) -> RedirectResponse:
        form = await request.form()
        name = str(form.get("list_name") or "").strip()
        person_id = str(form.get("person_id") or "").strip()
        orcid = str(form.get("orcid") or "").strip()
        from ..authorwatch import remove_person

        remove_person(cfg, name, orcid=orcid, person_id=person_id)
        return RedirectResponse(url=_page_url("/discover", list_name=name), status_code=303)


    @app.post("/discover/aw/resolve")
    async def discover_aw_resolve(request: Request) -> RedirectResponse:
        form = await request.form()
        name = str(form.get("list_name") or "").strip()

        def work(_cmd_id: str) -> None:
            from ..authorwatch import resolve_people

            resolve_people(cfg, name)

        cmd_id = commands.enqueue(cfg, "authorwatch_resolve", work)
        return _after_job("/discover", cmd_id, list_name=name)


    @app.post("/discover/aw/run")
    async def discover_aw_run(request: Request) -> RedirectResponse:
        form = await request.form()
        name = str(form.get("list_name") or "").strip()
        backfill = str(form.get("backfill_from") or "").strip() or None
        max_authors = form.get("max_authors")
        per_author = form.get("per_author_limit")
        try:
            max_authors_n = int(max_authors) if str(max_authors or "").strip() else None
            per_author_n = int(per_author) if str(per_author or "").strip() else None
        except ValueError:
            return RedirectResponse(
                url=_page_url("/discover", error="Counts must be whole numbers.", list_name=name),
                status_code=303,
            )

        def work(_cmd_id: str) -> None:
            from ..authorwatch import run_list

            kwargs: dict[str, Any] = {
                "console": jobs._quiet_console(),
                "backfill_from": backfill,
            }
            if max_authors_n is not None:
                kwargs["max_authors"] = max_authors_n
            if per_author_n is not None:
                kwargs["per_author_limit"] = per_author_n
            run_list(cfg, name, **kwargs)

        cmd_id = commands.enqueue(cfg, "authorwatch_run", work)
        return _after_job("/discover", cmd_id, list_name=name)


    @app.post("/discover/aw/import", response_model=None)
    async def discover_aw_import(request: Request):
        form = await request.form()
        name = str(form.get("list_name") or "followed").strip()
        source = str(form.get("source") or "csv").strip().lower()
        upload = form.get("file")
        filename = str(getattr(upload, "filename", "") or "")
        if not filename or upload is None:
            return JSONResponse({"ok": False, "error": "file required"}, status_code=400)
        data = await upload.read()  # type: ignore[union-attr]
        dest_dir = cfg.state_dir / "gui" / "uploads"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / Path(filename).name
        dest.write_bytes(data)
        jobs.authorwatch_import(cfg, list_name=name, path=dest, source=source)
        return RedirectResponse(url=_page_url("/discover", list_name=name), status_code=303)


    @app.post("/discover/aw/suggest")
    async def discover_aw_suggest(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        name = str(form.get("list_name") or "").strip()
        method = str(form.get("method") or "corpus").strip()
        limit = int(str(form.get("limit") or "15") or "15")
        collection = str(form.get("collection") or prefs.collection or "").strip()

        def work(_cmd_id: str) -> None:
            jobs.authorwatch_suggest(
                cfg,
                list_name=name,
                collection=collection,
                method=method,
                limit=limit,
            )

        cmd_id = commands.enqueue(cfg, "authorwatch_suggest", work)
        return _after_job("/discover", cmd_id, list_name=name)


    @app.post("/discover/aw/accept")
    async def discover_aw_accept(request: Request) -> RedirectResponse:
        form = await request.form()
        name = str(form.get("list_name") or "").strip()
        ids = [str(v) for v in form.getlist("suggestion_id")]
        seed_from = str(form.get("seed_from") or "").strip() or None

        def work(_cmd_id: str) -> None:
            jobs.authorwatch_accept(
                cfg,
                list_name=name,
                suggestion_ids=ids,
                seed_from=seed_from,
            )

        cmd_id = commands.enqueue(cfg, "authorwatch_accept", work)
        return _after_job("/discover", cmd_id, list_name=name)


    @app.post("/discover/aw/delete")
    async def discover_aw_delete(request: Request) -> RedirectResponse:
        form = await request.form()
        name = str(form.get("list_name") or "").strip()
        from ..authorwatch import delete_list

        delete_list(cfg, name, yes=True)
        return RedirectResponse(url="/discover", status_code=303)


    @app.post("/discover/aw/edit")
    async def discover_aw_edit(request: Request) -> RedirectResponse:
        form = await request.form()
        name = str(form.get("list_name") or "").strip()
        person_id = str(form.get("person_id") or "").strip()
        display = str(form.get("display_name") or "").strip()
        affiliation = str(form.get("affiliation") or "").strip()
        from ..authorwatch import update_person

        update_person(
            cfg,
            name,
            person_id,
            display_name=display,
            affiliation_host=affiliation,
        )
        return RedirectResponse(url=_page_url("/discover", list_name=name), status_code=303)


    @app.post("/discover/aw/briefing")
    async def discover_aw_briefing(request: Request) -> RedirectResponse:
        form = await request.form()
        name = str(form.get("list_name") or "").strip()
        if not name:
            return RedirectResponse(url="/discover", status_code=303)

        def work(cmd_id: str) -> None:
            from ..authorwatch import write_briefing

            path = write_briefing(cfg, name)
            jobs._attach_result(
                cfg,
                cmd_id,
                {"path": str(path), "markdown": path.read_text(encoding="utf-8")[:4000]},
            )

        cmd_id = commands.enqueue(cfg, "authorwatch_briefing", work)
        return _after_job("/discover", cmd_id, list_name=name)

