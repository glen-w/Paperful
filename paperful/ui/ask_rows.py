"""Ask / Briefs / critique row builders (no HTML)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import Config
from .page_common import DEST_OPTIONS, dest_for_form

ASK_ERROR_MESSAGES = {
    "empty": "Enter a question.",
    "year": "Year from and year to must be integers.",
    "focus": "Focus must be default, questions, gaps, methods, or answered.",
    "disabled": "Turn on [rag] and [llm] in config.toml to use Ask.",
    "llm": "Turn on [llm] in config.toml to summarize and synthesize.",
    "rag": "Turn on [rag] in config.toml to ingest and search.",
    "limit": "Limit and top-k must be positive integers.",
    "dest": "Destination must be disk, zotero, or both.",
    "collection": "Pick a collection in the chip, or set destination to disk.",
    "order": "Order must be library, newest, or oldest.",
    "questions": "Enter at least one question (one per line).",
    "apply": "A Zotero collection note needs dest zotero or both, and a collection.",
    "search": "Search failed. Check that the index exists and the embedder is up.",
    "prompt": "Custom prompt is invalid, empty, or missing.",
    "scope": "Pick a collection, item keys, or whole library.",
    "upload": "Upload is empty or too large.",
    "type": "Item type filter is invalid.",
}

SUMMARIZE_ORDERS = ("library", "newest", "oldest")


def list_threads(cfg: Config, limit: int = 12) -> list[dict[str, Any]]:
    from ..rag.thread import threads_dir

    root = threads_dir(cfg.state_dir)
    if not root.is_dir():
        return []
    files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for path in files[:limit]:
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        turns = body.get("turns") if isinstance(body, dict) else None
        n = len(turns) if isinstance(turns, list) else 0
        out.append(
            {
                "id": str((body or {}).get("id") or path.stem),
                "turns": n // 2,
                "mtime": path.stat().st_mtime,
            }
        )
    return out


def thread_for_display(cfg: Config, thread_id: str) -> list[dict[str, str]]:
    from ..rag.thread import load_thread

    loaded = load_thread(cfg.state_dir, thread_id)
    return [
        {"role": t.get("role") or "", "content": t.get("content") or ""}
        for t in loaded.turns
    ]


def last_ask_result(cfg: Config, thread_id: str) -> dict[str, Any]:
    from . import commands

    if not thread_id:
        return {}
    for rec in commands.list_commands(cfg, limit=50):
        if rec.get("verb") != "ask":
            continue
        result = rec.get("result") if isinstance(rec.get("result"), dict) else {}
        if str(result.get("thread_id") or "") == thread_id:
            return result
    return {}


def ask_page_flags(cfg: Config) -> dict[str, Any]:
    from ..llm import embed_egress_is_remote, llm_egress_is_remote
    from ..rag.status import index_status

    rag_on = bool(cfg.rag_enabled)
    llm_on = bool(cfg.llm_enabled)
    ready = rag_on and llm_on
    status: dict[str, Any] = {}
    if rag_on:
        try:
            status = dict(index_status(cfg) or {})
        except Exception as exc:
            status = {"error": str(exc), "problem": str(exc)}
    problem = str(status.get("problem") or status.get("error") or "")
    items = int(status.get("items") or 0)
    exists = bool(status.get("exists"))
    indexed = exists and items > 0 and not problem
    return {
        "rag_on": rag_on,
        "llm_on": llm_on,
        "ready": ready,
        "can_ingest": rag_on,
        "can_search": rag_on and indexed,
        "can_ask": ready and indexed,
        "remote_llm": llm_on and llm_egress_is_remote(cfg),
        "remote_embed": rag_on and embed_egress_is_remote(cfg),
        "status": status,
    }


def list_recent_critiques(cfg: Config, limit: int = 12) -> list[dict[str, Any]]:
    root = cfg.state_dir / "critiques"
    if not root.is_dir():
        return []
    packs: list[tuple[float, dict[str, Any]]] = []
    for cid_dir in root.iterdir():
        if not cid_dir.is_dir() or cid_dir.name == "uploads":
            continue
        for stamp in cid_dir.iterdir():
            md = stamp / "pack.md"
            js = stamp / "pack.json"
            if not stamp.is_dir() or not js.is_file():
                continue
            body: dict[str, Any] = {}
            try:
                raw = json.loads(js.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    body = raw
            except (OSError, ValueError):
                body = {}
            counts = body.get("counts") or {}
            packs.append(
                (
                    stamp.stat().st_mtime,
                    {
                        "critique_id": cid_dir.name,
                        "stamp": stamp.name,
                        "title": (body.get("input") or {}).get("title") or cid_dir.name,
                        "findings": counts.get("findings", 0),
                        "pack_dir": str(stamp),
                        "has_md": md.is_file(),
                    },
                )
            )
    packs.sort(key=lambda row: row[0], reverse=True)
    return [row[1] for row in packs[:limit]]


def critique_pack_markdown(cfg: Config, pack_dir: str) -> str:
    folder = Path(pack_dir)
    try:
        folder.resolve().relative_to((cfg.state_dir / "critiques").resolve())
    except (ValueError, OSError):
        return ""
    md = folder / "pack.md"
    if not md.is_file():
        return ""
    try:
        return md.read_text(encoding="utf-8")
    except OSError:
        return ""


def list_ask_packs(cfg: Config, limit: int = 12) -> list[dict[str, Any]]:
    from ..rag.batch import batch_dir

    root = batch_dir(cfg)
    if not root.is_dir():
        return []
    dirs = [
        p
        for p in root.iterdir()
        if p.is_dir() and p.name != "by-hash" and (p / "answers.md").is_file()
    ]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for path in dirs[:limit]:
        questions = answered = failed = 0
        pack = path / "pack.json"
        if pack.is_file():
            try:
                body = json.loads(pack.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, ValueError):
                body = {}
            if isinstance(body, dict):
                questions = int(body.get("questions") or 0)
                answered = int(body.get("answered") or 0)
                failed = int(body.get("failed") or 0)
        out.append(
            {
                "stamp": path.name,
                "questions": questions,
                "answered": answered,
                "failed": failed,
                "mtime": path.stat().st_mtime,
            }
        )
    return out


def list_answered_packs(cfg: Config, limit: int = 12) -> list[dict[str, Any]]:
    from ..rag.answered import answered_dir

    root = answered_dir(cfg)
    if not root.is_dir():
        return []
    dirs = [p for p in root.iterdir() if p.is_dir() and (p / "pack.md").is_file()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for path in dirs[:limit]:
        questions = answered = partial = not_found = failed = 0
        pack = path / "pack.json"
        if pack.is_file():
            try:
                body = json.loads(pack.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, ValueError):
                body = {}
            if isinstance(body, dict):
                questions = int(body.get("questions") or 0)
                answered = int(body.get("answered") or 0)
                partial = int(body.get("partial") or 0)
                not_found = int(body.get("not_found") or 0)
                failed = int(body.get("failed") or 0)
        out.append(
            {
                "stamp": path.name,
                "questions": questions,
                "answered": answered,
                "partial": partial,
                "not_found": not_found,
                "failed": failed,
                "mtime": path.stat().st_mtime,
            }
        )
    return out


def list_html_stems(folder: Any, limit: int = 20) -> list[dict[str, Any]]:
    from pathlib import Path

    root = Path(folder)
    if not root.is_dir():
        return []
    files = sorted(
        (p for p in root.glob("*.html") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return [{"name": p.stem, "mtime": p.stat().st_mtime} for p in files[:limit]]


def _summary_model(html: str) -> str:
    from ..notehtml import parse
    from ..summarize import parse_summary_provenance

    meta = parse(html) or {}
    model = str(meta.get("model") or "").strip()
    if model:
        return model
    prov = parse_summary_provenance(html) or {}
    return str(prov.get("model") or "").strip()


def _summary_cite(cfg: Config, key: str) -> str:
    try:
        from ..catalogue import MirrorCatalogue

        item = MirrorCatalogue(cfg.out_dir).get_item(key)
    except OSError:
        item = None
    if item is None:
        return key
    return item.label


def summary_meta(cfg: Config, key: str) -> dict[str, Any] | None:
    """Cite, model, and mtime for ``state/summaries/<key>.html``."""
    path = cfg.summaries_dir / f"{key}.html"
    if not path.is_file():
        return None
    html = path.read_text(encoding="utf-8", errors="replace")
    return {
        "name": key,
        "cite": _summary_cite(cfg, key),
        "model": _summary_model(html),
        "mtime": path.stat().st_mtime,
    }


def list_recent_summaries(cfg: Config, limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stem in list_html_stems(cfg.summaries_dir, limit):
        meta = summary_meta(cfg, stem["name"])
        if meta is not None:
            rows.append(meta)
    return rows


def briefs_synth_form(
    request: Any,
    *,
    dest_default: str,
    collection: str,
    last: dict[str, Any],
) -> dict[str, Any]:
    """Filters for the Briefs synthesize form (query string, then last job, then dest default)."""
    qp = getattr(request, "query_params", {}) or {}
    args = last.get("args") if isinstance(last.get("args"), dict) else {}

    def pick(name: str) -> str:
        raw = qp.get(f"synth_{name}")
        if raw is not None and str(raw).strip() != "":
            return str(raw).strip()
        val = args.get(name)
        if val is None or val is False:
            return ""
        if val is True:
            return "1"
        return str(val)

    q_dest = str(qp.get("synth_dest") or "").strip()
    if q_dest in DEST_OPTIONS:
        dest = q_dest
    else:
        arg_dest = str(args.get("dest") or "").strip()
        dest = dest_for_form(
            arg_dest if arg_dest in DEST_OPTIONS else dest_default,
            collection,
        )
    return {
        "dest": dest,
        "limit": pick("limit"),
        "year_from": pick("year_from"),
        "year_to": pick("year_to"),
        "force": pick("force") in {"1", "true", "True"},
    }


def briefs_page_flags(cfg: Config) -> dict[str, Any]:
    from ..llm import llm_egress_is_remote

    llm_on = bool(cfg.llm_enabled)
    return {
        "llm_on": llm_on,
        "remote_llm": llm_on and llm_egress_is_remote(cfg),
        "summarize_dest": cfg.summarize_dest,
        "synthesize_dest": cfg.synthesize_dest,
        "summarize_order": cfg.summarize_order,
    }


def focus_options() -> list[str]:
    from ..rag.prompt import FOCI

    names = list(FOCI)
    if "default" in names:
        names.remove("default")
        return ["default", *sorted(names)]
    return sorted(names)


def ask_mode_options() -> list[str]:
    return ["simple", "advanced"]
