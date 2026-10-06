"""FastAPI routes for the server-rendered workbench."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..agent_ops import collections_tree, doctor_payload, last_run
from ..config import Config
from . import commands, jobs
from .doctor_steps import next_step
from .pages import (
    ASK_ERROR_MESSAGES,
    ask_page_flags,
    authorwatch_inbox_rows,
    focus_options,
    following_lists,
    last_ask_result,
    list_threads,
    newest_snowball_queue,
    repair_queues,
    thread_for_display,
    wanted_rows,
    MIRROR_VERBS,
)
from .prefs import (
    COOKIE_ADVANCED,
    COOKIE_ATTACH_VERIFIED,
    COOKIE_COLLECTION,
    COOKIE_PRESET,
    WorkbenchPrefs,
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

    def ctx(request: Request, active: str, **extra: Any) -> dict[str, Any]:
        prefs = prefs_from_request(request)
        checks = doctor_payload(cfg)
        return {
            "request": request,
            "prefs": prefs,
            "active": active,
            "health": _health_status(checks),
            **extra,
        }

    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse(url="/wanted", status_code=302)

    @app.get("/wanted", response_class=HTMLResponse)
    def page_wanted(request: Request, tab: str = "missing") -> HTMLResponse:
        prefs = prefs_from_request(request)
        error = ""
        data = {"have": [], "held": [], "missing": [], "counts": {"have": 0, "held": 0, "missing": 0}}
        if prefs.collection:
            try:
                data = _load_wanted(cfg, prefs.collection)
            except Exception as exc:
                error = str(exc)
        rows = data.get(tab, []) if tab in {"have", "held", "missing"} else data["missing"]
        return templates.TemplateResponse(
            request,
            "wanted.html",
            ctx(
                request,
                "wanted",
                tab=tab,
                rows=rows,
                counts=data["counts"],
                error=error,
            ),
        )

    @app.post("/wanted/preview")
    async def wanted_preview(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        keys = [str(k) for k in form.getlist("keys")]

        def work(cmd_id: str) -> None:
            jobs.preview_run(
                cfg,
                cmd_id,
                collection=prefs.collection,
                preset=prefs.preset,
                keys=keys or None,
            )

        cmd_id = commands.enqueue(cfg, "preview_run", work)
        resp = RedirectResponse(url=f"/wanted?poll={cmd_id}", status_code=303)
        return resp

    @app.post("/wanted/grab", response_model=None)
    async def wanted_grab(request: Request):
        prefs = prefs_from_request(request)
        form = await request.form()
        token = str(form.get("review_token") or "")
        if not token:
            review_cmds = commands.list_commands(cfg, limit=5)
            for c in review_cmds:
                if c.get("review_token"):
                    token = c["review_token"]
                    break
        ok, msg = jobs.grab_run(cfg, token=token, attach_verified=prefs.attach_verified)
        if not ok:
            return JSONResponse({"ok": False, "error": msg}, status_code=409)
        return RedirectResponse(url="/wanted", status_code=303)

    @app.get("/discover", response_class=HTMLResponse)
    def page_discover(request: Request) -> HTMLResponse:
        run_id, candidates = newest_snowball_queue(cfg)
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
                error="",
            ),
        )

    @app.post("/discover/topic")
    async def discover_topic(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        query = str(form.get("query") or "")
        direction = str(form.get("direction") or "").strip() or None
        if not prefs.advanced:
            direction = None

        def work(cmd_id: str) -> None:
            jobs.track_topic(
                cfg, cmd_id, query=query, collection=prefs.collection, direction=direction
            )

        commands.enqueue(cfg, "snowball_search", work)
        return RedirectResponse(url="/discover", status_code=303)

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

    @app.post("/discover/apply")
    async def discover_apply(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        kind = str(form.get("kind") or "snowball")
        run_id = str(form.get("run_id") or "")
        if kind == "snowball" and run_id:
            jobs.discover_apply_snowball(cfg, run_id, prefs.collection)
        elif kind == "authorwatch":
            jobs.discover_apply_authorwatch(cfg, str(form.get("list_name") or "followed"), prefs.collection)
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
        name = str(form.get("watch_name") or "topic-watch")
        dest = cfg.state_dir / "snowball" / "watches" / name
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "watch.json").write_text("{}", encoding="utf-8")
        return RedirectResponse(url="/discover", status_code=303)

    @app.get("/library", response_class=HTMLResponse)
    def page_library(request: Request) -> HTMLResponse:
        tree = collections_tree(cfg)
        error = ""
        rows = []
        if tree.get("ok"):
            rows = tree.get("collections") or []
        else:
            error = str(tree.get("error") or "Library unavailable")
        return templates.TemplateResponse(
            request,
            "library.html",
            ctx(request, "library", collections=rows, error=error),
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
        prefs = prefs_from_request(request)
        form = await request.form()
        email = str(form.get("email") or "")
        host = str(form.get("zotero_host") or "")
        out_dir = str(form.get("out_dir") or "")
        preset = str(form.get("preset") or "oa")
        attach = form.get("attach_verified") == "1"
        if email:
            _patch_config_field(cfg, "", "email", email)
        if host:
            _patch_config_field(cfg, "zotero", "host", host)
        if out_dir:
            _patch_config_field(cfg, "", "out_dir", out_dir)
        resp = RedirectResponse(url="/settings?saved=1", status_code=303)
        if preset in {"oa", "eoi"}:
            set_cookie(resp, COOKIE_PRESET, preset)
        set_cookie(resp, COOKIE_ATTACH_VERIFIED, "1" if attach else "0")
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

    @app.get("/repair", response_class=HTMLResponse)
    def page_repair(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "repair.html",
            ctx(
                request,
                "repair",
                queues=repair_queues(cfg),
                message="",
            ),
        )

    @app.post("/repair/preview")
    async def repair_preview(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        verb = str(form.get("verb") or "dedupe")

        def work(cmd_id: str) -> None:
            jobs.repair_preview(cfg, cmd_id, verb=verb, collection=prefs.collection)

        commands.enqueue(cfg, f"repair_{verb}", work)
        return RedirectResponse(url="/repair", status_code=303)

    @app.post("/repair/apply", response_model=None)
    async def repair_apply(request: Request) -> JSONResponse | RedirectResponse:
        form = await request.form()
        overwrite = form.get("overwrite") == "1"
        token = str(form.get("review_token") or "")
        if not token:
            for c in commands.list_commands(cfg, limit=8):
                if str(c.get("verb") or "").startswith("repair_") and c.get("review_token"):
                    token = c["review_token"]
                    break
        ok, msg = jobs.repair_apply(cfg, token=token, overwrite=overwrite)
        if not ok:
            return JSONResponse({"ok": False, "error": msg}, status_code=409)
        return RedirectResponse(url="/repair", status_code=303)

    @app.get("/mirror", response_class=HTMLResponse)
    def page_mirror(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "mirror.html",
            ctx(request, "mirror", verbs=MIRROR_VERBS, message=""),
        )

    @app.post("/mirror/preview")
    async def mirror_preview(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        verb = str(form.get("verb") or "sync")

        def work(cmd_id: str) -> None:
            jobs.mirror_preview(cfg, cmd_id, verb=verb, collection=prefs.collection)

        commands.enqueue(cfg, f"mirror_{verb}", work)
        return RedirectResponse(url="/mirror", status_code=303)

    @app.post("/mirror/apply", response_model=None)
    async def mirror_apply(request: Request) -> JSONResponse | RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        token = str(form.get("review_token") or "")
        if not token:
            for c in commands.list_commands(cfg, limit=8):
                if str(c.get("verb") or "").startswith("mirror_") and c.get("review_token"):
                    token = c["review_token"]
                    break
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
    ) -> HTMLResponse:
        flags = ask_page_flags(cfg)
        if flags["ready"]:
            msg = "Ask a question over the indexed mirror. Scope follows the collection chip."
        else:
            msg = (
                "Turn on [rag] and [llm] in config.toml "
                "(Settings does not toggle them yet) to use Index."
            )
        active = (thread or "").strip()
        turns: list[dict[str, str]] = []
        result: dict[str, Any] = {}
        if active:
            turns = thread_for_display(cfg, active)
            result = last_ask_result(cfg, active)
        poll_run = (run or "").strip()
        return templates.TemplateResponse(
            request,
            "index.html",
            ctx(
                request,
                "index",
                page_title="Index",
                message=msg,
                enabled=flags["ready"],
                flags=flags,
                status=flags["status"],
                threads=list_threads(cfg),
                turns=turns,
                active_thread_id=active,
                last_result=result,
                focus_options=focus_options(),
                poll_run=poll_run,
                error=ASK_ERROR_MESSAGES.get(error, error),
            ),
        )

    @app.post("/index/ask")
    async def index_ask(request: Request) -> RedirectResponse:
        prefs = prefs_from_request(request)
        form = await request.form()
        question = str(form.get("question") or "").strip()
        thread_id = str(form.get("thread_id") or "").strip()
        focus_raw = str(form.get("focus") or "").strip() or None
        year_from_raw = str(form.get("year_from") or "").strip()
        year_to_raw = str(form.get("year_to") or "").strip()

        def _redir(*, err: str = "", tid: str = "", run: str = "") -> RedirectResponse:
            parts: list[str] = []
            if tid:
                parts.append(f"thread={tid}")
            if run:
                parts.append(f"run={run}")
            if err:
                parts.append(f"error={err}")
            qs = ("?" + "&".join(parts)) if parts else ""
            return RedirectResponse(url=f"/index{qs}", status_code=303)

        if not (cfg.rag_enabled and cfg.llm_enabled):
            return _redir(err="disabled", tid=thread_id)
        if not question:
            return _redir(err="empty", tid=thread_id)
        try:
            year_from = int(year_from_raw) if year_from_raw else None
            year_to = int(year_to_raw) if year_to_raw else None
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
