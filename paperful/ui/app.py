"""FastAPI routes for the server-rendered workbench."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..agent_ops import collections_tree, doctor_payload, last_run
from ..config import Config
from . import commands, jobs
from .doctor_steps import next_step
from .pages import (
    ASK_ERROR_MESSAGES,
    DEST_OPTIONS,
    SUMMARIZE_ORDERS,
    ask_page_flags,
    authorwatch_inbox_rows,
    authorwatch_lists,
    authorwatch_people_rows,
    briefs_page_flags,
    dest_options,
    focus_options,
    following_lists,
    last_ask_result,
    last_job_result,
    library_item_rows,
    list_ask_packs,
    list_html_stems,
    list_snowball_profiles,
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
from .snowball_form import parse_discover_topic
from .prefs import (
    COOKIE_ADVANCED,
    COOKIE_COLLECTION,
    COOKIE_PRESET,
    prefs_from_request,
    set_cookie,
)


def _ui_dir() -> Path:
    return Path(__file__).resolve().parent


def _health_status(checks: list[dict[str, Any]]) -> str:
    if any(c.get("status") == "red" for c in checks):
        return "red"
    if any(c.get("status") == "amber" for c in checks):
        return "amber"
    return "green"


def _health_label(checks: list[dict[str, Any]]) -> str:
    """Short label for the worst doctor row (red, then amber)."""
    for status in ("red", "amber"):
        for row in checks:
            if row.get("status") != status:
                continue
            code = str(row.get("code") or "")
            if code == "zotero_down":
                return "Zotero offline"
            if code == "zotero_api_off":
                return "Zotero API off"
            name = str(row.get("name") or "").strip()
            if name:
                return name
            if code:
                return code.replace("_", " ")
    return ""


def _trust_line(cfg: Config) -> str:
    report = last_run(cfg)
    if not report:
        return ""
    s = report.get("summary") or report
    parts = []
    for key, label in (
        ("downloaded", "downloaded"),
        ("attached", "attached"),
        ("deferred", "held"),
        ("not_found", "missed"),
    ):
        if key in s:
            parts.append(f"{label} {s[key]}")
    return " · ".join(parts)


def _load_wanted(cfg: Config, collection: str) -> dict[str, Any]:
    items, manifest = jobs._load_scope_items(cfg, collection)
    return wanted_rows(cfg, items, manifest)


def _patch_config_field(cfg: Config, section: str, key: str, value: str) -> None:
    path = cfg.config_path
    if path is None or not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    line = f'{key} = "{value}"'
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=.*$", re.MULTILINE)
    if section:
        sec_pattern = re.compile(rf"^\[{re.escape(section)}\]\s*$", re.MULTILINE)
        if sec_pattern.search(text):
            if pattern.search(text):
                text = pattern.sub(line, text, count=1)
            else:
                text = text.rstrip() + f"\n{line}\n"
        else:
            text = text.rstrip() + f"\n\n[{section}]\n{line}\n"
    else:
        if pattern.search(text):
            text = pattern.sub(line, text, count=1)
        else:
            text = line + "\n" + text
    path.write_text(text, encoding="utf-8")


def mount_ui(app: FastAPI, cfg: Config) -> None:
    templates = Jinja2Templates(directory=str(_ui_dir() / "templates"))
    static_dir = _ui_dir() / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    # Health chip only — avoid re-running the full doctor on every HTML request.
    _health_cache: dict[str, Any] = {"at": 0.0, "checks": []}

    def _cached_doctor() -> list[dict[str, Any]]:
        import time

        now = time.time()
        if now - float(_health_cache["at"]) < 30.0 and _health_cache["checks"]:
            return list(_health_cache["checks"])
        checks = doctor_payload(cfg)
        _health_cache["at"] = now
        _health_cache["checks"] = checks
        return checks

    def ctx(request: Request, active: str, **extra: Any) -> dict[str, Any]:
        prefs = prefs_from_request(request)
        checks = _cached_doctor()
        return {
            "request": request,
            "prefs": prefs,
            "active": active,
            "health": _health_status(checks),
            "health_label": _health_label(checks),
            **extra,
        }

    def _page_url(path: str, **kwargs: Any) -> str:
        from urllib.parse import urlencode

        pairs = [(k, str(v)) for k, v in kwargs.items() if v not in (None, "")]
        return path + (("?" + urlencode(pairs)) if pairs else "")

    def _optional_int(raw: object, *, positive: bool = False) -> int | None:
        text = str(raw or "").strip()
        if not text:
            return None
        value = int(text)
        if positive and value <= 0:
            raise ValueError("limit")
        return value

    def _parse_dest(raw: object, default: str) -> str:
        value = str(raw or "").strip() or default
        if value not in DEST_OPTIONS:
            raise ValueError("dest")
        return value

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

    @app.get("/wanted", response_class=HTMLResponse)
    def page_wanted(request: Request, tab: str = "missing", error: str = "") -> HTMLResponse:
        prefs = prefs_from_request(request)
        load_error = ""
        data = {"have": [], "held": [], "missing": [], "counts": {"have": 0, "held": 0, "missing": 0}}
        if prefs.collection:
            try:
                data = _load_wanted(cfg, prefs.collection)
            except Exception as exc:
                load_error = str(exc)
        rows = data.get(tab, []) if tab in {"have", "held", "missing"} else data["missing"]
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
        return templates.TemplateResponse(
            request,
            "wanted.html",
            ctx(
                request,
                "wanted",
                tab=tab,
                rows=rows,
                counts=data["counts"],
                error=banner,
                coach=coach,
                briefs=briefs,
                dest_options=dest_options(),
                attach_token=_wanted_token("attach"),
                recover_token=_wanted_token("recover"),
            ),
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
        flags = _wanted_run_flags(form) if prefs.advanced else {}

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
        form = await request.form()
        token = str(form.get("review_token") or "")
        if not token:
            review_cmds = commands.list_commands(cfg, limit=5)
            for c in review_cmds:
                if c.get("review_token"):
                    token = c["review_token"]
                    break
        if not token:
            token = _wanted_token("preview_run")
        ok, msg = jobs.grab_run(cfg, token=token)
        if not ok:
            return JSONResponse({"ok": False, "error": msg}, status_code=409)
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

        token = str(form.get("review_token") or "") or _wanted_token("attach")
        ok, msg = wanted_jobs.attach_apply(cfg, token=token)
        if not ok:
            return JSONResponse({"ok": False, "error": msg}, status_code=409)
        return RedirectResponse(url="/wanted", status_code=303)

    @app.post("/wanted/recover/preview")
    async def wanted_recover_preview(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        keys = [str(k) for k in form.getlist("keys")]
        from . import wanted_jobs

        def work(cmd_id: str) -> None:
            wanted_jobs.recover_preview(
                cfg,
                cmd_id,
                collection=prefs.collection,
                keys=keys,
                from_last_run=form.get("from_last_run") == "1",
                from_last_run_mode=str(form.get("from_last_run_mode") or "not_found"),
                limit=_parse_int(form.get("limit")),
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

    def _last_review_token(verb: str) -> str:
        for rec in commands.list_commands(cfg, limit=20):
            if rec.get("verb") == verb and rec.get("review_token"):
                return str(rec["review_token"])
        return ""

    @app.get("/discover", response_class=HTMLResponse)
    def page_discover(
        request: Request, list_name: str = "", error: str = ""
    ) -> HTMLResponse:
        run_id, candidates = newest_snowball_queue(cfg)
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
                following=following_lists(cfg),
                inbox=authorwatch_inbox_rows(cfg),
                aw_lists=authorwatch_lists(cfg),
                aw_list=active_list,
                aw_people=people,
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
                error=error,
            ),
        )

    @app.post("/discover/topic")
    async def discover_topic(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        payload = parse_discover_topic(form, advanced=prefs.advanced)

        def work(cmd_id: str) -> None:
            jobs.snowball_run(cfg, cmd_id, payload=payload, collection=prefs.collection)

        commands.enqueue(cfg, f"snowball_{payload.kind}", work)
        return RedirectResponse(url="/discover", status_code=303)

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
        return RedirectResponse(url=f"/discover?run={cmd_id}", status_code=303)

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
        return RedirectResponse(url=f"/discover?run={cmd_id}", status_code=303)

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
                min_count=int(form.get("min_count") or 2),
                max_authors=int(form.get("max_authors") or 15),
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
        return RedirectResponse(url=f"/discover?run={cmd_id}", status_code=303)

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
        return RedirectResponse(url=f"/discover?run={cmd_id}", status_code=303)

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

        commands.enqueue(cfg, "authorwatch_run", work)
        return RedirectResponse(url="/discover", status_code=303)

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
        commands.enqueue(cfg, verb, work)
        return RedirectResponse(url="/discover", status_code=303)

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

        commands.enqueue(cfg, "check_again", work)
        return RedirectResponse(url="/discover", status_code=303)

    @app.post("/discover/keep")
    async def discover_keep(request: Request) -> RedirectResponse:
        form = await request.form()
        run_id = str(form.get("run_id") or "")
        doi = str(form.get("doi") or "")
        keep = str(form.get("keep") or "1") == "1"
        if run_id and doi:
            jobs.set_snowball_keep(cfg, run_id, [doi], keep)
        return RedirectResponse(url="/discover", status_code=303)

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

        commands.enqueue(cfg, "snowball_resume", work)
        return RedirectResponse(url="/discover", status_code=303)

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

        commands.enqueue(cfg, "snowball_profile", work)
        return RedirectResponse(url="/discover", status_code=303)

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

        commands.enqueue(cfg, "snowball_briefing", work)
        return RedirectResponse(url="/discover", status_code=303)

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

        commands.enqueue(cfg, "snowball_digest", work)
        return RedirectResponse(url="/discover", status_code=303)

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

        commands.enqueue(cfg, "watch_briefing", work)
        return RedirectResponse(url="/discover", status_code=303)

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

        commands.enqueue(cfg, "watch_digest", work)
        return RedirectResponse(url="/discover", status_code=303)

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

        commands.enqueue(cfg, "authorwatch_resolve", work)
        return RedirectResponse(url=_page_url("/discover", list_name=name), status_code=303)

    @app.post("/discover/aw/run")
    async def discover_aw_run(request: Request) -> RedirectResponse:
        form = await request.form()
        name = str(form.get("list_name") or "").strip()
        backfill = str(form.get("backfill_from") or "").strip() or None
        max_authors = form.get("max_authors")
        per_author = form.get("per_author_limit")
        max_authors_n = int(max_authors) if str(max_authors or "").strip() else None
        per_author_n = int(per_author) if str(per_author or "").strip() else None

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

        commands.enqueue(cfg, "authorwatch_run", work)
        return RedirectResponse(url=_page_url("/discover", list_name=name), status_code=303)

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

        commands.enqueue(cfg, "authorwatch_briefing", work)
        return RedirectResponse(url=_page_url("/discover", list_name=name), status_code=303)

    @app.get("/library", response_class=HTMLResponse)
    def page_library(request: Request) -> HTMLResponse:
        prefs = prefs_from_request(request)
        tree = collections_tree(cfg)
        error = ""
        rows = []
        if tree.get("ok"):
            rows = tree.get("collections") or []
        else:
            error = str(tree.get("error") or "Library unavailable")
        items: list[dict[str, Any]] = []
        if prefs.collection:
            try:
                scope_items, manifest = jobs._load_scope_items(cfg, prefs.collection)
                items = library_item_rows(cfg, scope_items, manifest)
            except Exception as exc:
                error = error or str(exc)
        briefs = briefs_page_flags(cfg)
        return templates.TemplateResponse(
            request,
            "library.html",
            ctx(
                request,
                "library",
                collections=rows,
                items=items,
                error=error,
                briefs=briefs,
                dest_options=dest_options(),
            ),
        )

    @app.get("/activity", response_class=HTMLResponse)
    def page_activity(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "activity.html",
            ctx(
                request,
                "activity",
                commands=commands.list_commands(cfg),
                trust_line=_trust_line(cfg),
            ),
        )

    @app.get("/system", response_class=HTMLResponse)
    def page_system(request: Request) -> HTMLResponse:
        checks = []
        for row in doctor_payload(cfg):
            checks.append(
                {
                    "name": row["name"],
                    "status": row["status"],
                    "next": next_step(str(row.get("code") or ""), str(row.get("detail") or "")),
                }
            )
        return templates.TemplateResponse(
            request,
            "system.html",
            ctx(request, "system", checks=checks),
        )

    @app.get("/settings", response_class=HTMLResponse)
    def page_settings(request: Request, saved: int = 0) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "settings.html",
            ctx(
                request,
                "settings",
                email=cfg.email,
                zotero_host=__import__("paperful.zot", fromlist=["zotero_local_host"]).zotero_local_host(),
                saved=bool(saved),
                out_dir=str(cfg.out_dir),
            ),
        )

    @app.post("/settings")
    async def save_settings(request: Request) -> RedirectResponse:
        form = await request.form()
        email = str(form.get("email") or "")
        host = str(form.get("zotero_host") or "")
        out_dir = str(form.get("out_dir") or "")
        preset = str(form.get("preset") or "oa")
        if email:
            _patch_config_field(cfg, "", "email", email)
        if host:
            _patch_config_field(cfg, "zotero", "host", host)
        if out_dir:
            _patch_config_field(cfg, "", "out_dir", out_dir)
        resp = RedirectResponse(url="/settings?saved=1", status_code=303)
        if preset in {"oa", "eoi"}:
            set_cookie(resp, COOKIE_PRESET, preset)
        return resp

    @app.post("/prefs/advanced")
    async def prefs_advanced(request: Request) -> RedirectResponse:
        form = await request.form()
        on = form.get("advanced") == "1"
        referer = request.headers.get("referer") or "/wanted"
        resp = RedirectResponse(url=referer, status_code=303)
        set_cookie(resp, COOKIE_ADVANCED, "1" if on else "0")
        return resp

    @app.post("/prefs/collection")
    async def prefs_collection(request: Request) -> RedirectResponse:
        form = await request.form()
        coll = str(form.get("collection") or "")
        resp = RedirectResponse(url="/library", status_code=303)
        set_cookie(resp, COOKIE_COLLECTION, coll)
        return resp

    def _review_tokens_for(prefix: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for c in commands.list_commands(cfg, limit=40):
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

    @app.get("/repair", response_class=HTMLResponse)
    def page_repair(request: Request, run: str = "", error: str = "") -> HTMLResponse:
        run_rec = command_by_id(cfg, run) if run else None
        return templates.TemplateResponse(
            request,
            "repair.html",
            ctx(
                request,
                "repair",
                queues=repair_queues(cfg),
                tokens=_review_tokens_for("repair_"),
                message="",
                run_rec=run_rec,
                poll_run=run,
                error=error,
            ),
        )

    @app.post("/repair/preview")
    async def repair_preview_route(request: Request) -> RedirectResponse:
        from .repair_mirror_jobs import GuiScopeError

        prefs = prefs_from_request(request)
        form = await request.form()
        verb = str(form.get("verb") or "dedupe")
        if verb not in {"lint", "fix-metadata", "dedupe", "versions", "attachments", "ocr"}:
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
        }

        def work(cmd_id: str) -> None:
            try:
                jobs.repair_preview(
                    cfg,
                    cmd_id,
                    verb=verb,
                    collection=prefs.collection,
                    overwrite=overwrite,
                    apply_medium=apply_medium,
                    surgery=surgery,
                )
            except GuiScopeError as exc:
                rec = commands.read_command(cfg, cmd_id) or {}
                rec["status"] = "failed"
                rec["error"] = str(exc)
                commands.write_command(cfg, rec)
                raise

        cmd_id = commands.enqueue(cfg, f"repair_{verb}", work)
        return RedirectResponse(url=f"/repair?run={cmd_id}", status_code=303)

    @app.post("/repair/apply", response_model=None)
    async def repair_apply_route(request: Request) -> JSONResponse | RedirectResponse:
        form = await request.form()
        token = str(form.get("review_token") or "")
        if not token:
            return JSONResponse({"ok": False, "error": "missing review token"}, status_code=409)
        ok, msg = jobs.repair_apply(cfg, token=token)
        if not ok:
            return JSONResponse({"ok": False, "error": msg}, status_code=409)
        return RedirectResponse(url="/repair", status_code=303)

    @app.get("/mirror", response_class=HTMLResponse)
    def page_mirror(request: Request, run: str = "", error: str = "") -> HTMLResponse:
        run_rec = command_by_id(cfg, run) if run else None
        return templates.TemplateResponse(
            request,
            "mirror.html",
            ctx(
                request,
                "mirror",
                verbs=MIRROR_VERBS,
                message="",
                run_rec=run_rec,
                poll_run=run,
                error=error,
            ),
        )

    @app.post("/mirror/preview")
    async def mirror_preview_route(request: Request) -> RedirectResponse:
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
                    cfg,
                    cmd_id,
                    verb=verb,
                    collection=prefs.collection,
                    pdfs=pdfs,
                    accept_gone=accept_gone,
                )
            except GuiScopeError as exc:
                rec = commands.read_command(cfg, cmd_id) or {}
                rec["status"] = "failed"
                rec["error"] = str(exc)
                commands.write_command(cfg, rec)
                raise

        cmd_id = commands.enqueue(cfg, f"mirror_{verb.replace(' ', '_')}", work)
        return RedirectResponse(url=f"/mirror?run={cmd_id}", status_code=303)

    @app.post("/mirror/apply", response_model=None)
    async def mirror_apply_route(request: Request) -> JSONResponse | RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        verb = str(form.get("verb") or "")
        token = str(form.get("review_token") or "")
        if not token:
            return JSONResponse({"ok": False, "error": "missing review token"}, status_code=409)
        ok, msg = jobs.mirror_apply(cfg, token=token, collection=prefs.collection)
        if not ok:
            return JSONResponse({"ok": False, "error": msg}, status_code=409)
        return RedirectResponse(url="/mirror", status_code=303)

    @app.get("/index", response_class=HTMLResponse)
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
        flags = ask_page_flags(cfg)
        if flags["rag_on"] and flags["llm_on"]:
            msg = (
                "Ingest the mirror, search passages, then ask. "
                "Scope follows the collection chip."
            )
        elif flags["rag_on"]:
            msg = (
                "Ingest and search are on. Turn on [llm] in config.toml "
                "for Ask and batch Ask (Settings does not toggle it)."
            )
        else:
            msg = (
                "Turn on [rag] in config.toml to ingest and search. "
                "Ask also needs [llm]. Settings does not toggle them."
            )
        active = (thread or "").strip()
        turns: list[dict[str, str]] = []
        result: dict[str, Any] = {}
        if active:
            turns = thread_for_display(cfg, active)
            result = last_ask_result(cfg, active)
        hits: list[dict[str, Any]] = []
        search_q = (q or "").strip()
        search_error = ""
        if search_q and flags["can_search"]:
            try:
                from ..llm.preflight import validate_embedder
                from ..rag.index import Index, ledger_path
                from ..rag.ledger import Ledger
                from ..rag.retrieve import scope_keys, search

                prefs = prefs_from_request(request)
                y_from = _optional_int(year_from)
                y_to = _optional_int(year_to)
                top_k = _optional_int(k, positive=True)
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
            except ValueError:
                search_error = ASK_ERROR_MESSAGES["year"] if error != "limit" else ASK_ERROR_MESSAGES["limit"]
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
                threads=list_threads(cfg),
                turns=turns,
                active_thread_id=active,
                last_result=result,
                ingest_result=last_job_result(cfg, "rag_ingest"),
                batch_result=last_job_result(cfg, "ask_batch"),
                packs=list_ask_packs(cfg),
                hits=hits,
                search_q=search_q,
                search_k=k,
                year_from=year_from,
                year_to=year_to,
                dest_options=dest_options(),
                rag_dest=cfg.rag_dest or "disk",
                focus_options=focus_options(),
                poll_run=(run or "").strip(),
                error=err,
                synthesize_result=last_job_result(cfg, "synthesize"),
                reports=list_html_stems(cfg.reports_dir),
                synth_dest_options=dest_options(),
                synth_dest=cfg.synthesize_dest,
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
            dest = _parse_dest(form.get("dest"), cfg.synthesize_dest)
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

        cmd_id = commands.enqueue(cfg, "synthesize", work)
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
        if not cfg.rag_enabled:
            return RedirectResponse(url=_page_url("/index", error="rag"), status_code=303)
        dry_run = str(form.get("dry_run") or "1") != "0"
        try:
            year_from = _optional_int(form.get("year_from"))
            year_to = _optional_int(form.get("year_to"))
        except ValueError:
            return RedirectResponse(url=_page_url("/index", error="year"), status_code=303)
        try:
            limit = _optional_int(form.get("limit"), positive=True)
        except ValueError:
            return RedirectResponse(url=_page_url("/index", error="limit"), status_code=303)

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
        return RedirectResponse(url=_page_url("/index", run=cmd_id), status_code=303)

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

    @app.post("/index/ask")
    async def index_ask(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        question = str(form.get("question") or "").strip()
        thread_id = str(form.get("thread_id") or "").strip()
        focus_raw = str(form.get("focus") or "").strip() or None

        def _redir(*, err: str = "", tid: str = "", run: str = "") -> RedirectResponse:
            return RedirectResponse(
                url=_page_url("/index", thread=tid, run=run, error=err),
                status_code=303,
            )

        if not (cfg.rag_enabled and cfg.llm_enabled):
            return _redir(err="disabled", tid=thread_id)
        if not question:
            return _redir(err="empty", tid=thread_id)
        try:
            year_from = _optional_int(form.get("year_from"))
            year_to = _optional_int(form.get("year_to"))
        except ValueError:
            return _redir(err="year", tid=thread_id)
        try:
            from ..rag.prompt import parse_focus

            parse_focus(focus_raw if focus_raw is not None else cfg.rag_focus)
        except ValueError:
            return _redir(err="focus", tid=thread_id)
        if not thread_id:
            from ..rag.thread import new_id

            thread_id = new_id()

        def work(cmd_id: str) -> None:
            jobs.ask_turn(
                cfg,
                cmd_id,
                question=question,
                thread_id=thread_id,
                collection=prefs.collection,
                year_from=year_from,
                year_to=year_to,
                focus=focus_raw,
            )

        cmd_id = commands.enqueue(cfg, "ask", work)
        return _redir(tid=thread_id, run=cmd_id)

    @app.post("/index/ask-batch")
    async def index_ask_batch(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        if not (cfg.rag_enabled and cfg.llm_enabled):
            return RedirectResponse(url=_page_url("/index", error="disabled"), status_code=303)
        from ..snowball.seeds import parse_seed_lines

        questions = parse_seed_lines(str(form.get("questions") or ""))
        if not questions:
            return RedirectResponse(url=_page_url("/index", error="questions"), status_code=303)
        try:
            year_from = _optional_int(form.get("year_from"))
            year_to = _optional_int(form.get("year_to"))
        except ValueError:
            return RedirectResponse(url=_page_url("/index", error="year"), status_code=303)
        try:
            dest = _parse_dest(form.get("dest"), cfg.rag_dest or "disk")
        except ValueError:
            return RedirectResponse(url=_page_url("/index", error="dest"), status_code=303)
        apply = form.get("apply") == "1"
        if apply and (dest == "disk" or not prefs.collection):
            return RedirectResponse(url=_page_url("/index", error="apply"), status_code=303)
        focus_raw = str(form.get("focus") or "").strip() or None
        try:
            from ..rag.prompt import parse_focus

            parse_focus(focus_raw if focus_raw is not None else cfg.rag_focus)
        except ValueError:
            return RedirectResponse(url=_page_url("/index", error="focus"), status_code=303)

        def work(cmd_id: str) -> None:
            jobs.ask_batch(
                cfg,
                cmd_id,
                questions=questions,
                collection=prefs.collection,
                year_from=year_from,
                year_to=year_to,
                focus=focus_raw,
                dest=dest,
                apply=apply,
            )

        cmd_id = commands.enqueue(cfg, "ask_batch", work)
        return RedirectResponse(url=_page_url("/index", run=cmd_id), status_code=303)

    @app.get("/index/batch/{stamp}", response_model=None)
    def index_batch_pack(stamp: str):
        from ..rag.batch import batch_dir

        path = safe_child(batch_dir(cfg), stamp, "answers.md")
        if path is None:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        return FileResponse(path, media_type="text/plain; charset=utf-8")

    @app.get("/briefs", response_class=HTMLResponse)
    def page_briefs(
        request: Request,
        run: str = "",
        error: str = "",
    ) -> HTMLResponse:
        flags = briefs_page_flags(cfg)
        if flags["llm_on"]:
            msg = (
                "Summarize PDFs in scope, then synthesize a collection review. "
                "Scope follows the collection chip."
            )
        else:
            msg = (
                "Turn on [llm] in config.toml to summarize and synthesize. "
                "Settings does not toggle it."
            )
        err = ASK_ERROR_MESSAGES.get(error, error)
        return templates.TemplateResponse(
            request,
            "briefs.html",
            ctx(
                request,
                "briefs",
                message=msg,
                flags=flags,
                dest_options=dest_options(),
                orders=SUMMARIZE_ORDERS,
                summaries=list_html_stems(cfg.summaries_dir),
                reports=list_html_stems(cfg.reports_dir),
                summarize_result=last_job_result(cfg, "summarize"),
                synthesize_result=last_job_result(cfg, "synthesize"),
                poll_run=(run or "").strip(),
                error=err,
            ),
        )

    @app.post("/briefs/summarize")
    async def briefs_summarize(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        if not cfg.llm_enabled:
            return RedirectResponse(url=_page_url("/briefs", error="llm"), status_code=303)
        try:
            year_from = _optional_int(form.get("year_from"))
            year_to = _optional_int(form.get("year_to"))
        except ValueError:
            return RedirectResponse(url=_page_url("/briefs", error="year"), status_code=303)
        try:
            limit = _optional_int(form.get("limit"), positive=True)
            max_new = _optional_int(form.get("max_new"), positive=True)
        except ValueError:
            return RedirectResponse(url=_page_url("/briefs", error="limit"), status_code=303)
        try:
            dest = _parse_dest(form.get("dest"), cfg.summarize_dest)
        except ValueError:
            return RedirectResponse(url=_page_url("/briefs", error="dest"), status_code=303)
        order = str(form.get("order") or "").strip() or cfg.summarize_order
        if order not in SUMMARIZE_ORDERS:
            return RedirectResponse(url=_page_url("/briefs", error="order"), status_code=303)
        force = form.get("force") == "1"

        def work(cmd_id: str) -> None:
            jobs.summarize(
                cfg,
                cmd_id,
                collection=prefs.collection,
                year_from=year_from,
                year_to=year_to,
                limit=limit,
                max_new=max_new,
                dest=dest,
                order=order,
                force=force,
            )

        cmd_id = commands.enqueue(cfg, "summarize", work)
        return RedirectResponse(url=_page_url("/briefs", run=cmd_id), status_code=303)

    @app.post("/briefs/synthesize")
    async def briefs_synthesize(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        if not cfg.llm_enabled:
            return RedirectResponse(url=_page_url("/briefs", error="llm"), status_code=303)
        dry_run = str(form.get("dry_run") or "1") != "0"
        try:
            year_from = _optional_int(form.get("year_from"))
            year_to = _optional_int(form.get("year_to"))
        except ValueError:
            return RedirectResponse(url=_page_url("/briefs", error="year"), status_code=303)
        try:
            limit = _optional_int(form.get("limit"), positive=True)
        except ValueError:
            return RedirectResponse(url=_page_url("/briefs", error="limit"), status_code=303)
        try:
            dest = _parse_dest(form.get("dest"), cfg.synthesize_dest)
        except ValueError:
            return RedirectResponse(url=_page_url("/briefs", error="dest"), status_code=303)
        from ..config import wants_zotero

        if wants_zotero(dest) and not prefs.collection and not dry_run:
            return RedirectResponse(url=_page_url("/briefs", error="collection"), status_code=303)
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

        cmd_id = commands.enqueue(cfg, "synthesize", work)
        return RedirectResponse(url=_page_url("/briefs", run=cmd_id), status_code=303)

    @app.get("/briefs/summary/{key}", response_model=None)
    def briefs_summary(key: str):
        path = safe_child(cfg.summaries_dir, f"{key}.html")
        if path is None:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        return FileResponse(path, media_type="text/html; charset=utf-8")

    @app.get("/briefs/report/{slug}", response_model=None)
    def briefs_report(slug: str):
        path = safe_child(cfg.reports_dir, f"{slug}.html")
        if path is None:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        return FileResponse(path, media_type="text/html; charset=utf-8")

    @app.get("/v1/runs/{cmd_id}")
    def run_status(cmd_id: str) -> JSONResponse:
        rec = commands.read_command(cfg, cmd_id)
        if rec is None:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        return JSONResponse({"ok": True, **rec})

    @app.post("/v1/gui/noop")
    def gui_noop() -> JSONResponse:
        def work(cmd_id: str) -> None:
            jobs.run_noop(cfg, cmd_id)

        cmd_id = commands.enqueue(cfg, "noop", work)
        return JSONResponse({"id": cmd_id, "status": "queued"}, status_code=202)
