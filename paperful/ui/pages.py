"""Row builders for workbench pages (no HTML)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import Config
from ..miss_surface import honesty_row_for_item, miss_surface_plain, project_miss_surface
from ..store import Manifest, STATUS_ATTACHED, STATUS_OK
from .verify import file_verification


def _item_row_base(item: Any) -> dict[str, Any]:
    return {
        "key": item.key,
        "title": item.title or "",
        "doi": item.doi or "",
        "year": getattr(item, "year", None),
    }


def wanted_rows(
    cfg: Config,
    items: list[Any],
    manifest: Manifest,
) -> dict[str, Any]:
    have: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for item in items:
        rec = manifest.records.get(item.key)
        base = _item_row_base(item)
        if item.has_pdf or (
            rec is not None and rec.status in {STATUS_OK, STATUS_ATTACHED}
        ):
            ver = file_verification(rec, item_doi=item.doi)
            row = {**base, **ver, "ticked": ver["state"] == "doi_match"}
            state = ver["state"]
            if state == "doi_match":
                have.append(row)
            else:
                held.append(row)
            continue
        honesty = honesty_row_for_item(cfg, item, rec)
        code = str(honesty.get("miss_surface") or "")
        if code == "import_ok":
            continue
        plain = str(honesty.get("miss_plain") or "")
        if not plain and not code:
            code = project_miss_surface(
                doi=item.doi,
                arxiv_id=getattr(item, "arxiv_id", None),
                url=getattr(item, "url", None),
                has_pdf=False,
                status=str(getattr(rec, "status", "") or "") if rec else "",
                attempts=list(getattr(rec, "attempts", None) or []) if rec else [],
                source=getattr(rec, "source", None) if rec else None,
            )
            if code == "import_ok":
                continue
            plain = miss_surface_plain(code) if code else "No stored PDF"
        if not plain:
            continue
        missing.append(
            {
                **base,
                "miss_surface": code,
                "miss_plain": plain,
                "miss_detail": str(honesty.get("miss_detail") or ""),
            }
        )

    return {
        "have": have,
        "held": held,
        "missing": missing,
        "counts": {
            "have": len(have),
            "held": len(held),
            "missing": len(missing),
        },
    }


def scope_fingerprint(items: list[Any], manifest: Manifest) -> str:
    import hashlib

    lines: list[str] = []
    for item in sorted(items, key=lambda i: i.key):
        rec = manifest.records.get(item.key)
        status = rec.status if rec else "none"
        doi = item.doi or ""
        lines.append(f"{item.key}|{doi}|{status}")
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return digest


def newest_snowball_queue(cfg: Config) -> tuple[str, list[dict[str, Any]]]:
    root = cfg.state_dir / "snowball"
    if not root.is_dir():
        return "", []
    runs = sorted(
        [p for p in root.iterdir() if p.is_dir() and (p / "candidates.jsonl").is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not runs:
        return "", []
    run_id = runs[0].name
    rows: list[dict[str, Any]] = []
    with (runs[0] / "candidates.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            rows.append(
                {
                    "title": data.get("title") or "",
                    "doi": data.get("doi") or "",
                    "keep": data.get("keep"),
                    "run_id": run_id,
                }
            )
    return run_id, rows


def authorwatch_inbox_rows(cfg: Config) -> list[dict[str, Any]]:
    root = cfg.state_dir / "authorwatch"
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for list_dir in sorted(root.iterdir()):
        if not list_dir.is_dir():
            continue
        inbox = list_dir / "inbox.jsonl"
        if not inbox.is_file():
            continue
        with inbox.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                out.append(
                    {
                        "list": list_dir.name,
                        "title": data.get("title") or "",
                        "doi": data.get("doi") or "",
                    }
                )
    return out


def following_lists(cfg: Config) -> list[dict[str, Any]]:
    """Snowball watches and authorwatch lists for Discover."""
    out: list[dict[str, Any]] = []
    watches = cfg.state_dir / "snowball" / "watches"
    if watches.is_dir():
        for p in sorted(watches.iterdir()):
            if p.is_dir():
                out.append({"kind": "topic", "name": p.name})
    aw = cfg.state_dir / "authorwatch"
    if aw.is_dir():
        for p in sorted(aw.iterdir()):
            if p.is_dir() and (p / "watch.json").is_file():
                out.append({"kind": "person", "name": p.name})
    return out


REPAIR_VERBS = ("lint", "fix-metadata", "dedupe", "versions", "attachments", "ocr")
MIRROR_VERBS = ("sync", "snapshot", "restore", "cache clean")


def repair_queues(cfg: Config) -> list[dict[str, Any]]:
    """On-disk repair packs/reports for the Repair page."""
    rows: list[dict[str, Any]] = []
    mapping = (
        ("lint", cfg.state_dir / "runs", "*-lint.json"),
        ("fix-metadata", cfg.state_dir, "metadata-patches.jsonl"),
        ("dedupe", cfg.state_dir / "dedupe-packs", "*.json"),
        ("versions", cfg.state_dir / "version-packs", "*.json"),
        ("attachments", cfg.state_dir / "runs", "*-attachments.json"),
        ("ocr", cfg.state_dir / "runs", "*-ocr.json"),
    )
    for verb, folder, pattern in mapping:
        names: list[str] = []
        if folder.is_file() and pattern in folder.name:
            names = [folder.name]
        elif folder.is_dir():
            names = [p.name for p in sorted(folder.glob(pattern)) if p.is_file()]
        rows.append({"verb": verb, "files": names})
    return rows


ASK_ERROR_MESSAGES = {
    "empty": "Enter a question.",
    "year": "Year from and year to must be integers.",
    "focus": "Focus must be default, questions, gaps, methods, or answered.",
    "disabled": "Turn on [rag] and [llm] in config.toml to use Ask.",
}


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
    return [{"role": t.get("role") or "", "content": t.get("content") or ""} for t in loaded.turns]


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

    ready = bool(cfg.rag_enabled and cfg.llm_enabled)
    status: dict[str, Any] = {}
    if ready:
        try:
            status = dict(index_status(cfg) or {})
        except Exception as exc:
            status = {"error": str(exc), "problem": str(exc)}
    problem = str(status.get("problem") or status.get("error") or "")
    items = int(status.get("items") or 0)
    exists = bool(status.get("exists"))
    return {
        "ready": ready,
        "can_ask": ready and exists and items > 0 and not problem,
        "remote_llm": ready and llm_egress_is_remote(cfg),
        "remote_embed": ready and embed_egress_is_remote(cfg),
        "status": status,
    }


def focus_options() -> list[str]:
    from ..rag.prompt import FOCI

    names = list(FOCI)
    if "default" in names:
        names.remove("default")
        return ["default", *sorted(names)]
    return sorted(names)


def queue_fingerprint(cfg: Config, verb: str) -> str:
    import hashlib

    lines: list[str] = []
    for row in repair_queues(cfg):
        if row["verb"] != verb:
            continue
        for name in row["files"]:
            lines.append(f"{verb}|{name}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
