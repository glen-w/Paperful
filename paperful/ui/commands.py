"""GUI command ledger and review tokens."""

from __future__ import annotations

import json
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from ..config import Config

_worker_lock = threading.Lock()
_worker_started = False
_queue: list[tuple[str, Callable[[], None]]] = []
_queue_cond = threading.Condition(_worker_lock)


def _commands_dir(cfg: Config) -> Path:
    d = cfg.state_dir / "gui" / "commands"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _reviews_dir(cfg: Config) -> Path:
    d = cfg.state_dir / "gui" / "reviews"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_command(cfg: Config, record: dict[str, Any]) -> None:
    path = _commands_dir(cfg) / f"{record['id']}.json"
    _atomic_write(path, record)


def read_command(cfg: Config, cmd_id: str) -> dict[str, Any] | None:
    path = _commands_dir(cfg) / f"{cmd_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def list_commands(cfg: Config, limit: int = 50) -> list[dict[str, Any]]:
    d = _commands_dir(cfg)
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for path in files[:limit]:
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return out


def _ensure_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
        thread = threading.Thread(target=_worker_loop, name="paperful-gui-worker", daemon=True)
        thread.start()


def _worker_loop() -> None:
    while True:
        with _queue_cond:
            while not _queue:
                _queue_cond.wait()
            cmd_id, fn = _queue.pop(0)
        try:
            fn()
        except Exception:
            pass


def enqueue(cfg: Config, verb: str, fn: Callable[[str], None]) -> str:
    """Enqueue work; fn receives command id and must update the command record."""
    _ensure_worker()
    cmd_id = uuid.uuid4().hex[:12]
    record = {
        "id": cmd_id,
        "verb": verb,
        "status": "queued",
        "review_token": "",
        "error": "",
        "report_path": "",
        "created": time.time(),
    }
    write_command(cfg, record)

    def _run() -> None:
        rec = read_command(cfg, cmd_id) or record
        rec["status"] = "running"
        write_command(cfg, rec)
        try:
            fn(cmd_id)
            rec = read_command(cfg, cmd_id) or rec
            if rec.get("status") == "running":
                rec["status"] = "done"
            write_command(cfg, rec)
        except Exception as exc:
            rec = read_command(cfg, cmd_id) or rec
            rec["status"] = "failed"
            rec["error"] = str(exc)
            write_command(cfg, rec)

    with _queue_cond:
        _queue.append((cmd_id, _run))
        _queue_cond.notify()
    return cmd_id


def create_review_token(
    cfg: Config,
    *,
    verb: str,
    collection: str,
    preset: str,
    keys: list[str],
    fingerprint: str,
    command_id: str,
) -> str:
    token = secrets.token_urlsafe(16)
    data = {
        "token": token,
        "verb": verb,
        "collection": collection,
        "preset": preset,
        "keys": sorted(keys),
        "fingerprint": fingerprint,
        "command_id": command_id,
        "consumed": False,
    }
    _atomic_write(_reviews_dir(cfg) / f"{token}.json", data)
    rec = read_command(cfg, command_id)
    if rec:
        rec["review_token"] = token
        write_command(cfg, rec)
    return token


def load_review(cfg: Config, token: str) -> dict[str, Any] | None:
    path = _reviews_dir(cfg) / f"{token}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def consume_review(
    cfg: Config,
    token: str,
    *,
    fingerprint: str,
    keys: list[str] | None,
) -> tuple[bool, str]:
    data = load_review(cfg, token)
    if data is None:
        return False, "unknown token"
    if data.get("consumed"):
        return False, "token already used"
    if data.get("fingerprint") != fingerprint:
        return False, "library changed since preview"
    if keys is not None:
        allowed = set(data.get("keys") or [])
        if not set(keys).issubset(allowed):
            return False, "keys not in preview"
    data["consumed"] = True
    _atomic_write(_reviews_dir(cfg) / f"{token}.json", data)
    return True, ""
