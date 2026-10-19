"""Firefox native-messaging host for ``paperful capture``.

Stdout is the framed protocol. Logs stay on stderr. The launcher execs a
fixed argument list; page text never becomes a shell command.
"""

from __future__ import annotations

import json
import shlex
import struct
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from .capture import apply_page, drop_dir, plan_page, prepare, read_session
from .config import Config

MAX_MSG = 1024 * 1024
ADDON_ID = "addon@paperful.local"
HOST_NAME = "paperful"


def host_manifest_dir() -> Path | None:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Mozilla/NativeMessagingHosts"
    if sys.platform.startswith("linux"):
        return Path.home() / ".mozilla/native-messaging-hosts"
    return None


def hello_payload(cfg: Config) -> dict[str, Any]:
    path = drop_dir(cfg)
    path.mkdir(parents=True, exist_ok=True)
    return {
        "ok": True,
        "snapshot": cfg.extension_snapshot,
        "collection": cfg.extension_collection,
        "drop": str(path.resolve()),
        "concurrency": cfg.extension_concurrency,
    }


def install_host(cfg: Config, config_path: Path | None = None) -> str:
    """Write the user-level Firefox host manifest. Returns a status line."""
    dest_dir = host_manifest_dir()
    if dest_dir is None:
        return "not installed"
    launcher = cfg.state_dir / "capture" / "paperful-host"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "paperful.cli", "capture"]
    if config_path is not None:
        argv.extend(["--config", str(config_path.resolve())])
    argv.append("--stdio")
    script = "#!/bin/sh\nexec " + " ".join(shlex.quote(part) for part in argv) + "\n"
    launcher.write_text(script, encoding="utf-8")
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
    ):
        if key in out and out[key] is not None:
            out[key] = clip(out[key], limit)
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
        out["page"] = page
    return out


def handle_message(
    cfg: Config,
    msg: dict[str, Any],
    index: list[Any],
) -> dict[str, Any]:
    """``index`` is a one-slot cache so a tab batch refreshes once."""
    kind = str(msg.get("type") or "")
    if kind == "oversize" or kind == "invalid":
        return {"ok": False, "reason": "invalid"}
    if kind == "hello":
        return hello_payload(cfg)
    if kind == "handoff.session":
        return {"ok": True, **read_session(cfg)}
    if kind in {"capture.plan", "capture.apply"}:
        if not index:
            index.append(prepare(cfg))
        cached = index[0]
        msg = _clip_message(msg)
        if kind == "capture.plan":
            from .capture import as_year

            return plan_page(
                cfg,
                doi=str(msg.get("doi") or ""),
                url=str(msg.get("url") or ""),
                title=str(msg.get("title") or ""),
                year=as_year(msg.get("year")),
                pdf_url=str(msg.get("pdf_url") or ""),
                index=cached,
            )
        result = apply_page(cfg, msg, index=cached)
        result.pop("code", None)
        return result
    return {"ok": False, "reason": "unknown"}


def serve_stdio(cfg: Config) -> None:
    index: list[Any] = []
    while True:
        msg = _read_frame()
        if msg is None:
            return
        if msg.get("type") == "oversize":
            _write_frame({"ok": False, "reason": "invalid"})
            return
        with redirect_stdout(sys.stderr):
            reply = handle_message(cfg, msg, index)
        _write_frame(reply)
