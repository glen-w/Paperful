"""Persistent skip list for ``paperful ocr`` failures (missing PDF, OCR errors, etc.)."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class OcrIgnoreEntry:
    itemKey: str
    reason: str = ""
    source: str = "manual"  # manual | auto
    ts: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> OcrIgnoreEntry:
        data = json.loads(line)
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


class OcrIgnoreList:
    """Append-only JSONL; latest entry per item key wins."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.entries: dict[str, OcrIgnoreEntry] = {}
        if path.is_file():
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = OcrIgnoreEntry.from_json(line)
                    except (ValueError, TypeError, json.JSONDecodeError):
                        continue
                    if entry.source == "removed":
                        self.entries.pop(entry.itemKey, None)
                    else:
                        self.entries[entry.itemKey] = entry

    def get(self, key: str) -> OcrIgnoreEntry | None:
        return self.entries.get(key)

    def is_ignored(self, key: str) -> bool:
        return key in self.entries

    def add(self, key: str, reason: str = "", *, source: str = "manual") -> None:
        entry = OcrIgnoreEntry(
            itemKey=key,
            reason=(reason or "")[:500],
            source=source,
            ts=time.time(),
        )
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(entry.to_json() + "\n")
            self.entries[key] = entry

    def remove(self, key: str) -> bool:
        if key not in self.entries:
            return False
        tomb = OcrIgnoreEntry(itemKey=key, reason="", source="removed", ts=time.time())
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(tomb.to_json() + "\n")
            self.entries.pop(key, None)
        return True

    def list_entries(self) -> list[OcrIgnoreEntry]:
        return sorted(self.entries.values(), key=lambda e: e.ts, reverse=True)


def import_failures_from_report(path: Path) -> list[tuple[str, str]]:
    """Return (itemKey, reason) for failed or missing rows in an OCR run report."""
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    if str(body.get("command") or "") != "ocr":
        return []
    out: list[tuple[str, str]] = []
    for row in body.get("items") or []:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "")
        if status not in {"failed", "missing"}:
            continue
        key = str(row.get("itemKey") or row.get("key") or "").strip()
        if not key:
            continue
        reason = str(row.get("reason") or status)
        out.append((key, reason))
    return out


def latest_ocr_report(state_dir: Path) -> Path | None:
    runs = state_dir / "runs"
    if not runs.is_dir():
        return None
    files = sorted(runs.glob("*-ocr.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None
