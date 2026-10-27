"""FastAPI routes for the server-rendered workbench."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
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


def _ui_dir() -> Path:
    return Path(__file__).resolve().parent


def _health_status(checks: list[dict[str, Any]]) -> str:
    if not checks:
        return "amber"
    if any(c.get("status") == "red" for c in checks):
        return "red"
    if any(c.get("status") == "amber" for c in checks):
        return "amber"
    return "green"


def _row_health_label(row: dict[str, Any]) -> str:
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
    return "Issue"


def _health_label(checks: list[dict[str, Any]]) -> str:
    """Short label for the worst doctor row (red, then amber)."""
    for status in ("red", "amber"):
        for row in checks:
            if row.get("status") == status:
                return _row_health_label(row)
    return ""


def _health_tooltip(checks: list[dict[str, Any]]) -> str:
    if not checks:
        return "Health not loaded — open System to refresh"
    for status in ("red", "amber"):
        for row in checks:
            if row.get("status") != status:
                continue
            label = _row_health_label(row)
            step = next_step(str(row.get("code") or ""), str(row.get("detail") or ""))
            if step and step != label:
                return f"{status} · {label} — {step}"
            return f"{status} · {label}"
    return "All checks OK"


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


def _patch_section_assignment(text: str, section: str, key: str, literal: str) -> str:
    """Insert or replace ``key = literal`` inside one TOML table."""
    line = f"{key} = {literal}"
    header = re.compile(rf"^\[{re.escape(section)}\]\s*$", re.MULTILINE)
    found = header.search(text)
    if not found:
        return text.rstrip() + f"\n\n[{section}]\n{line}\n"
    start = found.end()
    nxt = re.search(r"^\[", text[start:], re.MULTILINE)
    end = start + nxt.start() if nxt else len(text)
    block = text[start:end]
    key_re = re.compile(rf"^[ \t]*{re.escape(key)}\s*=.*$", re.MULTILINE)
    if key_re.search(block):
        block = key_re.sub(line, block, count=1)
    else:
        if block and not block.endswith("\n"):
            block += "\n"
        block += line + "\n"
    return text[:start] + block + text[end:]


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
    from .context import UiContext
    from .wanted_routes import register_wanted
    from .discover_routes import register_discover
    from .repair_routes import register_repair
    from .index_routes import register_index
    from .shell_routes import register_shell
    from .critique_routes import register_critique
    from .rewrite_routes import register_rewrite

    templates = Jinja2Templates(directory=str(_ui_dir() / "templates"))
    static_dir = _ui_dir() / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    ui = UiContext(app=app, cfg=cfg, templates=templates)
    register_wanted(ui)
    register_discover(ui)
    register_shell(ui)
    register_repair(ui)
    register_index(ui)
    register_critique(ui)
    register_rewrite(ui)
