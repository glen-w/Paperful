"""Firefox native-messaging host for ``paperful capture``.

Stdout is the framed protocol. Logs stay on stderr. The launcher execs a
fixed argument list; page text never becomes a shell command.
"""

from __future__ import annotations

import json
import os
import shlex
import struct
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from .capture import (
    AUTHOR_MAX,
    COLLECTION_MAX,
    NOTE_MAX,
    apply_page,
    clip_tags,
    drop_dir,
    list_collection_paths,
    list_tag_names,
    mark_session_saved,
    suggest_tag_names,
    open_target,
    plan_page,
    prepare,
    read_session,
    stage_incoming,
    workbench_url,
    _open_live,
)
from .config import Config

MAX_MSG = 1024 * 1024
ADDON_ID = "addon@paperful.local"
HOST_NAME = "paperful"


def host_manifest_dir() -> Path | None:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Mozilla/NativeMessagingHosts"
    if sys.platform.startswith("linux"):
        return Path.home() / ".mozilla/native-messaging-hosts"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Mozilla" / "NativeMessagingHosts"
    return None


def host_launcher_path(cfg: Config) -> Path:
    """Path to the native-messaging launcher Firefox executes.

    macOS blocks Firefox from running helpers under Documents, Desktop, or
    Downloads (TCC). Keep the launcher under Application Support / .local.
    """
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library/Application Support/Paperful/capture/paperful-host"
        )
    if sys.platform.startswith("linux"):
        return Path.home() / ".local/share/paperful/capture/paperful-host"
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(
            Path.home() / "AppData" / "Local"
        )
        return Path(local) / "Paperful" / "capture" / "paperful-host.bat"
    return cfg.state_dir / "capture" / "paperful-host"


def hello_payload(cfg: Config) -> dict[str, Any]:
    path = drop_dir(cfg)
    path.mkdir(parents=True, exist_ok=True)
    live = _open_live(cfg)
    return {
        "ok": True,
        "snapshot": cfg.extension_snapshot,
        "collection": cfg.extension_collection,
        "collections": list_collection_paths(cfg),
        "tags": list_tag_names(cfg, live=live),
        "drop": str(path.resolve()),
        "out": str(Path(cfg.out_dir).resolve()),
        "concurrency": cfg.extension_concurrency,
        "workbench": workbench_url(),
        "platform": sys.platform,
    }


def _win_quote(part: str) -> str:
    if not part or any(ch in part for ch in ' \t"&|^<>'):
        return '"' + part.replace('"', '\\"') + '"'
    return part


def _launcher_script(argv: list[str]) -> str:
    if sys.platform == "win32":
        return "@echo off\r\n" + " ".join(_win_quote(part) for part in argv) + "\r\n"
    return "#!/bin/sh\nexec " + " ".join(shlex.quote(part) for part in argv) + "\n"


def install_host(cfg: Config, config_path: Path | None = None) -> str:
    """Write the user-level Firefox host manifest. Returns a status line."""
    dest_dir = host_manifest_dir()
    if dest_dir is None:
        return "not installed"
    launcher = host_launcher_path(cfg)
    launcher.parent.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "paperful.cli", "capture"]
    if sys.platform == "win32":
        argv.insert(1, "-u")
    cfg_file = config_path or cfg.config_path
    if cfg_file is not None:
        argv.extend(["--config", str(cfg_file.resolve())])
    argv.append("--stdio")
    launcher.write_text(_launcher_script(argv), encoding="utf-8")
    if sys.platform != "win32":
        launcher.chmod(0o755)
    manifest = {
        "name": HOST_NAME,
        "description": "Paperful capture",
        "path": str(launcher.resolve()),
        "type": "stdio",
        "allowed_extensions": [ADDON_ID],
    }
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "paperful.json"
    dest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return str(dest)


def _read_frame() -> dict[str, Any] | None:
    raw = sys.stdin.buffer.read(4)
    if not raw:
        return None
    if len(raw) < 4:
        return {"type": "invalid"}
    size = struct.unpack("<I", raw)[0]
    if size <= 0 or size > MAX_MSG:
        return {"type": "oversize"}
    body = sys.stdin.buffer.read(size)
    if len(body) < size:
        return {"type": "invalid"}
    try:
        msg = json.loads(body.decode("utf-8"))
    except (UnicodeError, ValueError):
        return {"type": "invalid"}
    if not isinstance(msg, dict):
        return {"type": "invalid"}
    return msg


def _write_frame(payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_MSG:
        data = json.dumps({"ok": False, "reason": "too_large"}).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _clip_authors(raw: Any) -> Any:
    from .capture import clip

    if isinstance(raw, list):
        return [clip(part, AUTHOR_MAX) for part in raw[:20]]
    if raw is None:
        return raw
    return clip(raw, AUTHOR_MAX * 5)


def _clip_message(msg: dict[str, Any]) -> dict[str, Any]:
    from .capture import ABSTRACT_MAX, DOI_MAX, TITLE_MAX, URL_MAX, clip

    out = dict(msg)
    for key, limit in (
        ("doi", DOI_MAX),
        ("url", URL_MAX),
        ("title", TITLE_MAX),
        ("pdf_url", URL_MAX),
        ("pdf_path", URL_MAX),
        ("html_path", URL_MAX),
        ("confirm_key", 64),
        ("path", URL_MAX),
        ("key", 64),
        ("collection", COLLECTION_MAX),
        ("note", NOTE_MAX),
        ("abstract", ABSTRACT_MAX),
        ("publication_title", TITLE_MAX),
        ("target", 16),
    ):
        if key in out and out[key] is not None:
            out[key] = clip(out[key], limit)
    if "authors" in out:
        out["authors"] = _clip_authors(out["authors"])
    if "tags" in out:
        out["tags"] = clip_tags(out["tags"])
    keys = out.get("keys")
    if isinstance(keys, list):
        out["keys"] = [clip(key, 64) for key in keys[:200]]
    page = out.get("page")
    if isinstance(page, dict):
        page = dict(page)
        for key, limit in (
            ("doi", DOI_MAX),
            ("url", URL_MAX),
            ("title", TITLE_MAX),
            ("pdf_url", URL_MAX),
            ("abstract", ABSTRACT_MAX),
            ("publication_title", TITLE_MAX),
        ):
            if key in page and page[key] is not None:
                page[key] = clip(page[key], limit)
        if "authors" in page:
            page["authors"] = _clip_authors(page["authors"])
        out["page"] = page
    return out


def _echo_id(msg: dict[str, Any], reply: dict[str, Any]) -> dict[str, Any]:
    req_id = msg.get("id")
    if isinstance(req_id, bool) or not isinstance(req_id, int):
        return reply
    if 0 < req_id < 1_000_000_000:
        out = dict(reply)
        out["id"] = req_id
        return out
    return reply


def handle_message(
    cfg: Config,
    msg: dict[str, Any],
    index: list[Any],
) -> dict[str, Any]:
    """``index`` is a one-slot cache so a tab batch refreshes once."""
    kind = str(msg.get("type") or "")
    if kind == "oversize" or kind == "invalid":
        return _echo_id(msg, {"ok": False, "reason": "invalid"})
    if kind == "hello":
        return _echo_id(msg, hello_payload(cfg))
    if kind == "handoff.session":
        return _echo_id(msg, {"ok": True, **read_session(cfg)})
    if kind == "handoff.mark":
        keys = msg.get("keys")
        if not isinstance(keys, list):
            keys = []
        return _echo_id(msg, mark_session_saved(cfg, keys))
    if kind == "capture.tag_suggest":
        live = _open_live(cfg)
        tags = suggest_tag_names(
            cfg,
            query=str(msg.get("query") or ""),
            doi=str(msg.get("doi") or ""),
            live=live,
        )
        return _echo_id(msg, {"ok": True, "tags": tags})
    if kind == "capture.stage":
        return _echo_id(msg, stage_incoming(cfg, str(msg.get("path") or "")))
    if kind == "capture.open":
        return _echo_id(
            msg,
            open_target(
                cfg,
                str(msg.get("target") or ""),
                key=str(msg.get("key") or ""),
            ),
        )
    if kind in {"capture.plan", "capture.apply"}:
        if not index:
            index.append(prepare(cfg))
        cached = index[0]
        msg = _clip_message(msg)
        if kind == "capture.plan":
            from .capture import as_year

            page = msg.get("page") if isinstance(msg.get("page"), dict) else {}
            year = msg.get("year")
            if year in (None, "") and isinstance(page, dict):
                year = page.get("year")
            return _echo_id(
                msg,
                plan_page(
                    cfg,
                    doi=str(msg.get("doi") or page.get("doi") or ""),
                    url=str(msg.get("url") or page.get("url") or ""),
                    title=str(msg.get("title") or page.get("title") or ""),
                    year=as_year(year),
                    pdf_url=str(msg.get("pdf_url") or page.get("pdf_url") or ""),
                    index=cached,
                ),
            )
        result = apply_page(cfg, msg, index=cached)
        result.pop("code", None)
        return _echo_id(msg, result)
    return _echo_id(msg, {"ok": False, "reason": "unknown"})


def serve_stdio(cfg: Config) -> None:
    index: list[Any] = []
    while True:
        msg = _read_frame()
        if msg is None:
            return
        if msg.get("type") == "oversize":
            _write_frame(_echo_id(msg, {"ok": False, "reason": "invalid"}))
            return
        with redirect_stdout(sys.stderr):
            reply = handle_message(cfg, msg, index)
        _write_frame(reply)
