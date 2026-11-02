"""Atomic on-disk writes and cross-process file locks for state/ and out/."""

from __future__ import annotations

import itertools
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from filelock import FileLock

_part_seq = itertools.count()


def _part_path(path: Path) -> Path:
    # Unique per process / thread / call so concurrent writers of the same
    # file (GUI worker + request thread) never race on one ``.part`` name.
    tag = f"{os.getpid()}-{threading.get_ident()}-{next(_part_seq)}"
    return path.with_name(f"{path.name}.{tag}.part")


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _part_path(path)
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _part_path(path)
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Any, *, indent: int = 2) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=indent) + "\n"
    atomic_write_text(path, text)


def append_jsonl(
    path: Path,
    lines: str | list[str],
    *,
    lock: tuple[Path, str] | None = None,
) -> None:
    """Append JSONL and fsync. A crash can tear only the last line.

    ``lock`` is ``(state_dir, name)`` for the cross-process lock. Readers
    must skip a final line that is not valid JSON.
    """
    if isinstance(lines, str):
        chunk = lines if lines.endswith("\n") else lines + "\n"
    else:
        parts: list[str] = []
        for line in lines:
            parts.append(line if line.endswith("\n") else line + "\n")
        chunk = "".join(parts)
        if not chunk:
            return

    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(chunk)
            fh.flush()
            os.fsync(fh.fileno())

    if lock is None:
        _write()
        return
    state_dir, name = lock
    with file_lock(state_dir, name):
        _write()


def lock_path(state_dir: Path, name: str) -> Path:
    d = state_dir / ".locks"
    d.mkdir(parents=True, exist_ok=True)
    safe = name.replace("/", "_").replace("\\", "_")
    return d / f"{safe}.lock"


@contextmanager
def file_lock(state_dir: Path, name: str, *, timeout: float = 120.0) -> Iterator[None]:
    """Cross-process lock under ``state/.locks/``."""
    path = lock_path(state_dir, name)
    lock = FileLock(str(path), timeout=timeout)
    with lock:
        yield
