"""Disk layout, filenames and the append-only manifest that makes runs resumable."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .attach import attach_failure_code
from .zot import Item

STATUS_OK = "ok"  # PDF on disk, not yet attached
STATUS_ATTACHED = "attached"  # PDF on disk and attached in Zotero
STATUS_NOT_FOUND = "not_found"  # every source said no
STATUS_NO_IDENTIFIER = "no_identifier"  # nothing to search with (no DOI/arXiv/URL)
STATUS_CAPTCHA = "captcha"  # Sci-Hub robot check could not be passed
STATUS_ERROR = "error"  # transient / unexpected failure, retried on next run
STATUS_ATTACH_FAILED = "attach_failed"  # PDF ok, Zotero write failed
TERMINAL_SKIP = {STATUS_OK, STATUS_ATTACHED}
FAILED = {STATUS_NOT_FOUND, STATUS_NO_IDENTIFIER}
RETRY_ALWAYS = {STATUS_ERROR, STATUS_CAPTCHA, STATUS_ATTACH_FAILED}

_MAX_TITLE = 90
_MAX_NAME = 180
_UNSAFE = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")


@dataclass
class Record:
    itemKey: str
    status: str
    title: str = ""
    doi: str | None = None
    doi_source: str = "none"
    library_doi: str | None = None
    doi_verified: str = ""
    pdf_doi: str | None = None
    source: str | None = None
    url: str | None = None
    path: str | None = None
    extra_paths: list[str] = field(default_factory=list)
    md5: str | None = None
    reason: str = ""
    attempts: list[str] = field(default_factory=list)
    ts: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> Record:
        data = json.loads(line)
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


class Manifest:
    """Append-only JSONL; latest record per item key wins."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.records: dict[str, Record] = {}
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = Record.from_json(line)
                    except (ValueError, TypeError):
                        continue
                    self.records[rec.itemKey] = rec

    def get(self, key: str) -> Record | None:
        return self.records.get(key)

    def write(self, rec: Record) -> None:
        rec.ts = time.time()
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(rec.to_json() + "\n")
            self.records[rec.itemKey] = rec

    def should_process(self, key: str, retry_failed: bool) -> bool:
        rec = self.records.get(key)
        if rec is None:
            return True
        if rec.status in TERMINAL_SKIP:
            return False
        if rec.status in FAILED:
            return retry_failed
        return True  # error / captcha / attach_failed

    def pending_attach(self) -> list[Record]:
        return [
            r
            for r in self.records.values()
            if r.status in {STATUS_OK, STATUS_ATTACH_FAILED} and r.path
        ]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.records.values():
            out[r.status] = out.get(r.status, 0) + 1
        return out

    def by_source(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.records.values():
            if r.status in {STATUS_OK, STATUS_ATTACHED} and r.source:
                out[r.source] = out.get(r.source, 0) + 1
        return out

    def attach_failed_by_code(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.records.values():
            if r.status != STATUS_ATTACH_FAILED:
                continue
            code = attach_failure_code(r.reason)
            out[code] = out.get(code, 0) + 1
        return out

    def report_payload(self, last_run: dict | None = None) -> dict:
        counts = self.counts()
        no_doi = sum(1 for r in self.records.values() if not r.doi)
        payload: dict = {
            "counts": counts,
            "by_source": self.by_source(),
            "no_identifier": counts.get(STATUS_NO_IDENTIFIER, 0),
            "no_doi": no_doi,
            "attach_failed_by_code": self.attach_failed_by_code(),
        }
        if last_run:
            payload["last_run"] = last_run
            if "linked_url_skipped" in last_run:
                payload["linked_url"] = last_run["linked_url_skipped"]
        return payload


# ---- filenames ---------------------------------------------------------------


def _ascii(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def safe_filename(author: str | None, year: int | None, title: str) -> str:
    """`Author - Year - Title.pdf`, ASCII-safe, truncated."""
    who = _ascii(author or "Unknown").strip()
    who = _UNSAFE.sub("", who)[:40] or "Unknown"
    yr = str(year) if year else "n.d."
    t = _ascii(title or "untitled")
    t = re.sub(r"<[^>]+>", "", t)
    t = _UNSAFE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip(" .")
    if len(t) > _MAX_TITLE:
        t = t[:_MAX_TITLE].rsplit(" ", 1)[0].rstrip(" .,;:-")
    name = f"{who} - {yr} - {t or 'untitled'}.pdf"
    if len(name) > _MAX_NAME:
        name = name[: _MAX_NAME - 4].rstrip() + ".pdf"
    return name


def item_filename(item: Item) -> str:
    return safe_filename(item.first_author, item.year, item.title)


def unique_path(directory: Path, filename: str, md5: str) -> Path:
    """Avoid clobbering a different file with the same name; reuse identical ones."""
    import hashlib

    dest = directory / filename
    if not dest.exists():
        return dest
    if hashlib.md5(dest.read_bytes()).hexdigest() == md5:
        return dest
    stem, suffix = os.path.splitext(filename)
    for i in range(2, 100):
        alt = directory / f"{stem} ({i}){suffix}"
        if not alt.exists() or hashlib.md5(alt.read_bytes()).hexdigest() == md5:
            return alt
    return directory / f"{stem} ({md5[:8]}){suffix}"


def save_pdf(
    out_dir: Path, item: Item, content: bytes, md5: str
) -> tuple[Path, list[Path]]:
    """Write once under the first collection path; hardlink under the others."""
    filename = item_filename(item)
    paths = item.collection_paths or ["_uncollected"]
    primary_dir = out_dir / paths[0]
    primary_dir.mkdir(parents=True, exist_ok=True)
    primary = unique_path(primary_dir, filename, md5)
    if not primary.exists():
        tmp = primary.with_suffix(".part")
        tmp.write_bytes(content)
        os.replace(tmp, primary)
    extras: list[Path] = []
    for p in paths[1:]:
        d = out_dir / p
        d.mkdir(parents=True, exist_ok=True)
        target = unique_path(d, filename, md5)
        if not target.exists():
            try:
                os.link(primary, target)
            except OSError:
                target.write_bytes(content)
        extras.append(target)
    return primary, extras


def relpaths(out_dir: Path, paths: Iterable[Path]) -> list[str]:
    out = []
    for p in paths:
        try:
            out.append(str(p.relative_to(out_dir)))
        except ValueError:
            out.append(str(p))
    return out
