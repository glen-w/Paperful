"""Atomic on-disk writes and cross-process file locks for state/ and out/."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from filelock import FileLock


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def atomic_write_json(path: Path, payload: Any, *, indent: int = 2) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=indent) + "\n"
    atomic_write_text(path, text)


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
