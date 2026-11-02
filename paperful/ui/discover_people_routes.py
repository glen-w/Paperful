"""Workbench HTTP routes (Discover people / authorwatch / network)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import commands, jobs
from .context import UiContext
from .discover_common import bad_list_name, safe_list_name
from .prefs import prefs_from_request


async def handle_discover_authors(ui: UiContext, request: Request) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    try:
        min_count = int(form.get("min_count") or 2)
        max_authors = int(form.get("max_authors") or 15)
    except ValueError:
        return RedirectResponse(
            url=ui.page_url(
                "/discover", tab="grow", error="Counts must be whole numbers."
            ),
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
            config=ui.cfg.config_path,
            fmt="json",
        )
        rec = commands.read_command(ui.cfg, cmd_id) or {}
        rec["result"] = {"apply": form.get("apply") == "1"}
        commands.write_command(ui.cfg, rec)

    cmd_id = commands.enqueue(ui.cfg, "authors", work)
    return ui.after_job("/discover", cmd_id, tab="grow")


async def handle_discover_packs_promote(
    ui: UiContext, request: Request
) -> RedirectResponse:
    form = await request.form()
    slug = str(form.get("slug") or "").strip()
    if not slug:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="grow", error="slug"), status_code=303
        )

    def work(cmd_id: str) -> None:
        from ..snowball.preflight import promote_pack

        path = promote_pack(ui.cfg, slug)
        rec = commands.read_command(ui.cfg, cmd_id) or {}
        rec["result"] = {"path": str(path)}
        commands.write_command(ui.cfg, rec)

    cmd_id = commands.enqueue(ui.cfg, "packs_promote", work)
    return ui.after_job("/discover", cmd_id, tab="grow")


async def handle_discover_follow(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    orcid = str(form.get("orcid") or "").strip()
    list_name = safe_list_name(form.get("list_name"), default="followed")
    if list_name is None:
        return bad_list_name()
    backfill = str(form.get("backfill_from") or "").strip() or None
    if not orcid:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="people", error="orcid"), status_code=303
        )

    def work(cmd_id: str) -> None:
        jobs.follow_person(
            ui.cfg, cmd_id, orcid=orcid, list_name=list_name, backfill_from=backfill
        )

    cmd_id = commands.enqueue(ui.cfg, "authorwatch_run", work)
    return ui.after_job("/discover", cmd_id, tab="people", list_name=list_name)


async def handle_discover_aw_save(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    name = safe_list_name(form.get("name"))
    if name is None:
        return bad_list_name()
    if not name:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="people"), status_code=303
        )
    from ..authorwatch import save_list

    save_list(ui.cfg, name)
    return RedirectResponse(
        url=ui.page_url("/discover", tab="people", list_name=name), status_code=303
    )


async def handle_discover_aw_add(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    name = safe_list_name(form.get("list_name"), default="followed")
    if name is None:
        return bad_list_name()
    orcid = str(form.get("orcid") or "").strip()
    display = str(form.get("display_name") or "").strip()
    affiliation = str(form.get("affiliation") or "").strip()
    from ..authorwatch import add_person

    add_person(
        ui.cfg, name, orcid=orcid, display_name=display, affiliation_host=affiliation
    )
    return RedirectResponse(
        url=ui.page_url("/discover", tab="people", list_name=name), status_code=303
    )


async def handle_discover_aw_remove(
    ui: UiContext, request: Request
) -> RedirectResponse:
    form = await request.form()
    name = safe_list_name(form.get("list_name"))
    if name is None:
        return bad_list_name()
    person_id = str(form.get("person_id") or "").strip()
    orcid = str(form.get("orcid") or "").strip()
    from ..authorwatch import remove_person

    remove_person(ui.cfg, name, orcid=orcid, person_id=person_id)
    return RedirectResponse(
        url=ui.page_url("/discover", tab="people", list_name=name), status_code=303
    )


async def handle_discover_aw_resolve(
    ui: UiContext, request: Request
) -> RedirectResponse:
    form = await request.form()
    name = safe_list_name(form.get("list_name"))
    if name is None:
        return bad_list_name()

    def work(_cmd_id: str) -> None:
        from ..authorwatch import resolve_people

        resolve_people(ui.cfg, name)

    cmd_id = commands.enqueue(ui.cfg, "authorwatch_resolve", work)
    return ui.after_job("/discover", cmd_id, tab="people", list_name=name)


async def handle_discover_aw_run(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    name = safe_list_name(form.get("list_name"))
    if name is None:
        return bad_list_name()
    backfill = str(form.get("backfill_from") or "").strip() or None
    max_authors = form.get("max_authors")
    per_author = form.get("per_author_limit")
    try:
        max_authors_n = int(max_authors) if str(max_authors or "").strip() else None
        per_author_n = int(per_author) if str(per_author or "").strip() else None
    except ValueError:
        return RedirectResponse(
            url=ui.page_url(
                "/discover", error="Counts must be whole numbers.", list_name=name
            ),
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
        run_list(ui.cfg, name, **kwargs)

    cmd_id = commands.enqueue(ui.cfg, "authorwatch_run", work)
    return ui.after_job("/discover", cmd_id, tab="people", list_name=name)


async def handle_discover_aw_import(ui: UiContext, request: Request):
    form = await request.form()
    name = safe_list_name(form.get("list_name"), default="followed")
    if name is None:
        return bad_list_name()
    source = str(form.get("source") or "csv").strip().lower()
    upload = form.get("file")
    filename = str(getattr(upload, "filename", "") or "")
    if not filename or upload is None:
        return JSONResponse({"ok": False, "error": "file required"}, status_code=400)
    data = await upload.read()
    dest_dir = ui.cfg.state_dir / "gui" / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(filename).name
    dest.write_bytes(data)
    jobs.authorwatch_import(ui.cfg, list_name=name, path=dest, source=source)
    return RedirectResponse(
        url=ui.page_url("/discover", tab="people", list_name=name), status_code=303
    )


async def handle_discover_aw_suggest(
    ui: UiContext, request: Request
) -> RedirectResponse:
    prefs = prefs_from_request(request)
    form = await request.form()
    name = safe_list_name(form.get("list_name"))
    if name is None:
        return bad_list_name()
    method = str(form.get("method") or "corpus").strip()
    limit = int(str(form.get("limit") or "15") or "15")
    collection = str(form.get("collection") or prefs.collection or "").strip()

    def work(_cmd_id: str) -> None:
        jobs.authorwatch_suggest(
            ui.cfg, list_name=name, collection=collection, method=method, limit=limit
        )

    cmd_id = commands.enqueue(ui.cfg, "authorwatch_suggest", work)
    return ui.after_job("/discover", cmd_id, tab="people", list_name=name)


async def handle_discover_aw_accept(
    ui: UiContext, request: Request
) -> RedirectResponse:
    form = await request.form()
    name = safe_list_name(form.get("list_name"))
    if name is None:
        return bad_list_name()
    ids = [str(v) for v in form.getlist("suggestion_id")]
    seed_from = str(form.get("seed_from") or "").strip() or None

    def work(_cmd_id: str) -> None:
        jobs.authorwatch_accept(
            ui.cfg, list_name=name, suggestion_ids=ids, seed_from=seed_from
        )

    cmd_id = commands.enqueue(ui.cfg, "authorwatch_accept", work)
    return ui.after_job("/discover", cmd_id, tab="people", list_name=name)


async def handle_discover_aw_delete(
    ui: UiContext, request: Request
) -> RedirectResponse:
    form = await request.form()
    name = safe_list_name(form.get("list_name"))
    if name is None:
        return bad_list_name()
    from ..authorwatch import delete_list

    delete_list(ui.cfg, name, yes=True)
    return RedirectResponse(url=ui.page_url("/discover", tab="people"), status_code=303)


async def handle_discover_aw_edit(ui: UiContext, request: Request) -> RedirectResponse:
    form = await request.form()
    name = safe_list_name(form.get("list_name"))
    if name is None:
        return bad_list_name()
    person_id = str(form.get("person_id") or "").strip()
    display = str(form.get("display_name") or "").strip()
    affiliation = str(form.get("affiliation") or "").strip()
    from ..authorwatch import update_person

    update_person(
        ui.cfg, name, person_id, display_name=display, affiliation_host=affiliation
    )
    return RedirectResponse(
        url=ui.page_url("/discover", tab="people", list_name=name), status_code=303
    )


async def handle_discover_aw_briefing(
    ui: UiContext, request: Request
) -> RedirectResponse:
    form = await request.form()
    name = safe_list_name(form.get("list_name"))
    if name is None:
        return bad_list_name()
    if not name:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="people"), status_code=303
        )

    def work(cmd_id: str) -> None:
        from ..authorwatch import write_briefing

        path = write_briefing(ui.cfg, name)
        jobs._attach_result(
            ui.cfg,
            cmd_id,
            {"path": str(path), "markdown": path.read_text(encoding="utf-8")[:4000]},
        )

    cmd_id = commands.enqueue(ui.cfg, "authorwatch_briefing", work)
    return ui.after_job("/discover", cmd_id, tab="people", list_name=name)


def handle_discover_network_meta(ui: UiContext) -> JSONResponse:
    from ..network.store import list_runs

    enabled = ui.cfg.ui_coauthor_network != "off"
    return JSONResponse(
        {
            "ok": True,
            "enabled": enabled,
            "runs": list_runs(ui.cfg) if enabled else [],
        }
    )


def handle_discover_network(
    ui: UiContext, run_id: str = "", phase: str = ""
) -> JSONResponse:
    from ..network.store import NetworkError, load_run

    if ui.cfg.ui_coauthor_network == "off":
        return JSONResponse(
            {"ok": False, "error": "Co-author network is off."}, status_code=404
        )
    cleaned = (run_id or "").strip()
    if not cleaned:
        return JSONResponse({"ok": False, "error": "run_id required"}, status_code=400)
    try:
        bundle = load_run(ui.cfg, cleaned)
    except NetworkError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
    graph = bundle.get("graph") or {}
    metrics = bundle.get("metrics") or {}
    slug = (phase or "").strip()
    if slug:
        payload = (bundle.get("phases") or {}).get(slug) or {}
        if not payload:
            return JSONResponse(
                {"ok": False, "error": f"Phase {slug!r} is not in this run."},
                status_code=404,
            )
        graph = payload.get("graph") or graph
        metrics = payload.get("metrics") or metrics
    return JSONResponse(
        {
            "ok": True,
            "schema": bundle.get("schema"),
            "run_id": bundle.get("run_id"),
            "meta": bundle.get("meta") or {},
            "graph": graph,
            "metrics": metrics,
        }
    )


async def handle_discover_network_run(
    ui: UiContext, request: Request
) -> RedirectResponse:
    form = await request.form()
    orcid = str(form.get("orcid") or "").strip()
    phases = str(form.get("phases") or "bbnj").strip() or "bbnj"
    partition = str(form.get("partition") or "none").strip() or "none"
    try:
        max_works = int(str(form.get("max_works") or "500").strip() or "500")
        max_alters = int(str(form.get("max_alters") or "150").strip() or "150")
    except ValueError:
        return RedirectResponse(
            url=ui.page_url(
                "/discover", tab="people", error="Counts must be whole numbers."
            ),
            status_code=303,
        )
    if not orcid:
        return RedirectResponse(
            url=ui.page_url("/discover", tab="people", error="ORCID is required."),
            status_code=303,
        )

    def work(cmd_id: str) -> None:
        from ..network.run import run_orcid
        from ..network.store import NetworkError

        try:
            bundle = run_orcid(
                ui.cfg,
                orcid,
                phases=phases,
                partition=partition,
                max_works=max_works,
                max_alters=max_alters,
            )
        except (NetworkError, ValueError) as exc:
            raise RuntimeError(str(exc)) from exc
        jobs._attach_result(
            ui.cfg,
            cmd_id,
            {
                "run_id": bundle.get("run_id"),
                "path": bundle.get("path"),
                "nodes": (bundle.get("meta") or {}).get("nodes"),
            },
        )

    cmd_id = commands.enqueue(ui.cfg, "network_orcid", work)
    return ui.after_job("/discover", cmd_id, tab="people")
