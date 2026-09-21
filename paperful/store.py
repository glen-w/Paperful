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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .attach import attach_failure_code
from .zot import Item

# Legacy sibling card. New writes use record.json (paperful.item.v1).
MIRROR_SCHEMA = "paperful.mirror.v1"
ITEM_SCHEMA = "paperful.item.v1"
HISTORY_SCHEMA = "paperful.history.v1"
COLLECTIONS_SCHEMA = "paperful.collections.v1"
PDF_MODES = frozenset({"additional", "all", "none"})
_KEY_MARK = " -- "
# Zotero keys are 8 alphanumeric; Mendeley ids are UUIDs; EndNote ids are integers.
_ITEM_DIR_RE = re.compile(r" -- ([A-Za-z0-9][A-Za-z0-9._-]*)$")

STATUS_OK = "ok"  # PDF on disk, not yet attached
STATUS_ATTACHED = "attached"  # PDF on disk and attached in Zotero
STATUS_NOT_FOUND = "not_found"  # every source said no
STATUS_NO_IDENTIFIER = "no_identifier"  # nothing to search with (no DOI/arXiv/URL)
STATUS_CAPTCHA = "captcha"  # Sci-Hub robot check could not be passed
STATUS_ERROR = "error"  # transient / unexpected failure, retried on next run
STATUS_ATTACH_FAILED = "attach_failed"  # PDF ok, Zotero write failed
# Saved under --strict-pdf-doi. `paperful attach` skips these unless opted in.
REASON_STRICT_PDF_DOI = "strict_pdf_doi"
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
    playbook: str = ""
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

    def pending_attach(self, *, allow_pdf_doi_mismatch: bool = False) -> list[Record]:
        return [
            r
            for r in self.records.values()
            if r.status in {STATUS_OK, STATUS_ATTACH_FAILED}
            and r.path
            and (
                allow_pdf_doi_mismatch or r.reason != REASON_STRICT_PDF_DOI
            )
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


def item_dirname(item: Item) -> str:
    """`Author - Year - Title -- KEY`. The key is never truncated."""
    stem = Path(item_filename(item)).stem
    suffix = f"{_KEY_MARK}{item.key}"
    budget = _MAX_NAME - len(suffix)
    if len(stem) > budget:
        stem = stem[: max(budget, 1)].rstrip(" .,;:-") or "untitled"
    return stem + suffix


def item_key_from_dirname(name: str) -> str | None:
    match = _ITEM_DIR_RE.search(name)
    return match.group(1) if match else None


def is_item_dirname(name: str) -> bool:
    return item_key_from_dirname(name) is not None


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
    """Write once under the first collection's item folder; hardlink the rest.

    A leftover flat ``Author - Year - Title.pdf`` in that collection folder is
    moved into the item directory first.
    """
    filename = item_filename(item)
    dirname = item_dirname(item)
    paths = item.collection_paths or ["_uncollected"]
    primary_dir = out_dir / paths[0] / dirname
    primary_dir.mkdir(parents=True, exist_ok=True)
    migrate_flat_pdf(out_dir / paths[0], filename, primary_dir)
    primary = unique_path(primary_dir, filename, md5)
    if not primary.exists():
        tmp = primary.with_suffix(".part")
        tmp.write_bytes(content)
        os.replace(tmp, primary)
    extras: list[Path] = []
    for p in paths[1:]:
        d = out_dir / p / dirname
        d.mkdir(parents=True, exist_ok=True)
        migrate_flat_pdf(out_dir / p, filename, d)
        target = unique_path(d, filename, md5)
        if not target.exists():
            try:
                os.link(primary, target)
            except OSError:
                target.write_bytes(content)
        extras.append(target)
    return primary, extras


def migrate_flat_pdf(collection_dir: Path, filename: str, item_dir: Path) -> Path | None:
    """Move a flat PDF (and absorb its legacy card) into ``item_dir``.

    Returns the new PDF path when a flat file was moved or already matched.
    """
    flat = collection_dir / filename
    if not flat.is_file() or is_item_dirname(flat.parent.name):
        return None
    item_dir.mkdir(parents=True, exist_ok=True)
    dest = item_dir / filename
    if dest.exists():
        try:
            same = os.path.samefile(flat, dest) or (
                hashlib_md5(flat) == hashlib_md5(dest)
            )
        except OSError:
            same = False
        if same and flat != dest:
            flat.unlink(missing_ok=True)
        elif flat != dest:
            return None
    else:
        os.replace(flat, dest)
    card = mirror_card_path(collection_dir / filename)
    if card.is_file():
        absorb_legacy_card(card, item_dir, dest.name)
    return dest


def hashlib_md5(path: Path) -> str:
    import hashlib

    return hashlib.md5(path.read_bytes()).hexdigest()


def mirror_card_path(pdf: Path) -> Path:
    """Legacy `Author - Year - Title.paperful.json` beside a flat PDF."""
    return pdf.with_name(f"{pdf.stem}.paperful.json")


def record_path(item_dir: Path) -> Path:
    return item_dir / "record.json"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _creators_from_item(item: Item) -> list[dict[str, Any]]:
    if item.first_author:
        return [{"creatorType": "author", "lastName": item.first_author}]
    return []


def empty_item_record(item: Item) -> dict[str, Any]:
    """Catalogue shell from the fetch-side Item. Snapshot fills the rest."""
    return {
        "schema": ITEM_SCHEMA,
        "item_key": item.key,
        "item_type": item.item_type,
        "version": None,
        "date_added": item.date_added,
        "date_modified": None,
        "title": item.title,
        "creators": _creators_from_item(item),
        "year": item.year,
        "date": item.date,
        "publication_title": item.publication_title,
        "doi": item.doi,
        "library_doi": item.library_doi,
        "doi_source": item.doi_source,
        "doi_verified": item.doi_verified,
        "pdf_doi": None,
        "arxiv_id": item.arxiv_id,
        "pmid": item.pmid,
        "url": item.url,
        "extra": item.extra,
        "abstract": item.abstract,
        "tags": [],
        "relations": {},
        "fields": {},
        "collections": [{"key": None, "path": p} for p in item.collection_paths],
        "collection_paths": list(item.collection_paths),
        "attachments": [],
        "fetch": None,
        "notes": [],
    }


def fetch_block(
    *,
    source: str | None,
    fetched_url: str | None,
    md5: str | None,
    pdf_name: str | None,
    pdf_doi: str | None,
    fetched_at: str | None = None,
    origin: str | None = None,
) -> dict[str, Any]:
    when = fetched_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "source": source,
        "fetched_url": fetched_url,
        "fetched_at": when,
        "md5": md5,
        "pdf": pdf_name,
        "pdf_doi": pdf_doi,
        "origin": origin if origin is not None else source,
    }


def write_fetch_records(
    pdfs: Iterable[Path],
    item: Item,
    *,
    md5: str,
    source: str | None,
    fetched_url: str | None,
    pdf_doi: str | None,
) -> list[Path]:
    """Write or refresh ``record.json`` beside each PDF. Fetch overwrites; catalogue stays."""
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    written: list[Path] = []
    for pdf in pdfs:
        dest = record_path(pdf.parent)
        rec = load_json(dest) or empty_item_record(item)
        rec["schema"] = ITEM_SCHEMA
        rec["item_key"] = item.key
        fetch = fetch_block(
            source=source,
            fetched_url=fetched_url,
            md5=md5,
            pdf_name=pdf.name,
            pdf_doi=pdf_doi,
            fetched_at=fetched_at,
        )
        rec["fetch"] = fetch
        rec["pdf_doi"] = pdf_doi
        if item.title:
            rec["title"] = item.title
        write_json(dest, rec)
        written.append(dest)
    return written


def absorb_legacy_card(card_path: Path, item_dir: Path, pdf_name: str) -> Path | None:
    """Fold a ``*.paperful.json`` card into ``record.json`` and delete the card."""
    card = load_json(card_path)
    if card is None:
        return None
    dest = record_path(item_dir)
    rec = load_json(dest) or {
        "schema": ITEM_SCHEMA,
        "item_key": card.get("item_key"),
        "item_type": card.get("item_type"),
        "version": None,
        "date_added": None,
        "date_modified": None,
        "title": card.get("title") or "",
        "creators": (
            [{"creatorType": "author", "lastName": card["first_author"]}]
            if card.get("first_author")
            else []
        ),
        "year": card.get("year"),
        "date": card.get("date"),
        "publication_title": card.get("publication_title"),
        "doi": card.get("doi"),
        "library_doi": card.get("library_doi"),
        "doi_source": card.get("doi_source") or "none",
        "doi_verified": card.get("doi_verified") or "",
        "pdf_doi": card.get("pdf_doi"),
        "arxiv_id": card.get("arxiv_id"),
        "pmid": None,
        "url": card.get("url"),
        "extra": "",
        "abstract": None,
        "tags": [],
        "relations": {},
        "fields": {},
        "collections": [
            {"key": None, "path": p} for p in (card.get("collection_paths") or [])
        ],
        "collection_paths": list(card.get("collection_paths") or []),
        "attachments": [],
        "fetch": None,
        "notes": [],
    }
    rec["schema"] = ITEM_SCHEMA
    rec["fetch"] = fetch_block(
        source=card.get("source"),
        fetched_url=card.get("fetched_url"),
        md5=card.get("md5"),
        pdf_name=pdf_name,
        pdf_doi=card.get("pdf_doi"),
        fetched_at=card.get("fetched_at"),
    )
    rec["pdf_doi"] = card.get("pdf_doi")
    write_json(dest, rec)
    card_path.unlink(missing_ok=True)
    return dest


def iter_flat_pdfs(out_dir: Path) -> list[Path]:
    """PDFs sitting directly in a collection folder, not inside an item directory."""
    if not out_dir.is_dir():
        return []
    found: list[Path] = []
    for pdf in out_dir.rglob("*.pdf"):
        if pdf.name.startswith("."):
            continue
        if is_item_dirname(pdf.parent.name):
            continue
        if pdf.parent.name in {"notes", "pdf-cache"}:
            continue
        found.append(pdf)
    return found


def _paths_match(stored: str | None, path: Path) -> bool:
    if not stored:
        return False
    try:
        return Path(stored).resolve() == path.resolve()
    except OSError:
        return Path(stored) == path


def retarget_manifest(manifest: Manifest, old: Path, new: Path, out_dir: Path) -> None:
    """Append a fresh manifest line when a PDF moved into an item folder."""
    try:
        rel_new = str(new.relative_to(out_dir))
    except ValueError:
        rel_new = str(new)
    for rec in list(manifest.records.values()):
        changed = False
        if _paths_match(rec.path, old):
            rec.path = str(new)
            changed = True
        extras: list[str] = []
        for ep in rec.extra_paths:
            abs_ep = ep if Path(ep).is_absolute() else out_dir / ep
            if _paths_match(str(abs_ep), old) or _paths_match(ep, old):
                extras.append(rel_new)
                changed = True
            else:
                extras.append(ep)
        if changed:
            rec.extra_paths = extras
            manifest.write(rec)


def migrate_flat_tree(
    out_dir: Path, manifest: Manifest | None = None, *, dry_run: bool = False
) -> int:
    """Move flat PDFs (with a card or a manifest hit) into item folders.

    Idempotent: a second pass finds nothing left to move.
    """
    moved = 0
    for pdf in iter_flat_pdfs(out_dir):
        card_path = mirror_card_path(pdf)
        card = load_json(card_path)
        key = (card or {}).get("item_key") if card else None
        title = (card or {}).get("title") or Path(pdf.stem).stem
        author = (card or {}).get("first_author")
        year = (card or {}).get("year")
        if isinstance(year, str) and year.isdigit():
            year = int(year)
        if not isinstance(year, int):
            year = None
        matched: Record | None = None
        if manifest is not None and key is None:
            for rec in manifest.records.values():
                if _paths_match(rec.path, pdf) or any(
                    _paths_match(ep, pdf) or _paths_match(str(out_dir / ep), pdf)
                    for ep in rec.extra_paths
                ):
                    matched = rec
                    key = rec.itemKey
                    title = rec.title or title
                    break
        if not key:
            continue
        placeholder = Item(
            key=str(key),
            item_type=str((card or {}).get("item_type") or "document"),
            title=str(title or "untitled"),
            doi=(card or {}).get("doi") if card else None,
            arxiv_id=None,
            url=None,
            year=year if isinstance(year, int) else None,
            first_author=str(author) if author else None,
            collection_paths=[],
        )
        dest_dir = pdf.parent / item_dirname(placeholder)
        dest_pdf = dest_dir / pdf.name
        moved += 1
        if dry_run:
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        if dest_pdf.exists() and pdf != dest_pdf:
            try:
                same = os.path.samefile(pdf, dest_pdf) or (
                    hashlib_md5(pdf) == hashlib_md5(dest_pdf)
                )
            except OSError:
                same = False
            if same:
                pdf.unlink(missing_ok=True)
            else:
                moved -= 1
                continue
        elif pdf != dest_pdf:
            os.replace(pdf, dest_pdf)
        if card_path.is_file():
            absorb_legacy_card(card_path, dest_dir, dest_pdf.name)
        elif not record_path(dest_dir).is_file() and matched is not None:
            shell = empty_item_record(placeholder)
            shell["fetch"] = fetch_block(
                source=matched.source,
                fetched_url=matched.url,
                md5=matched.md5,
                pdf_name=dest_pdf.name,
                pdf_doi=matched.pdf_doi,
            )
            shell["pdf_doi"] = matched.pdf_doi
            write_json(record_path(dest_dir), shell)
        if manifest is not None:
            retarget_manifest(manifest, pdf, dest_pdf, out_dir)
    return moved


def relpaths(out_dir: Path, paths: Iterable[Path]) -> list[str]:
    out = []
    for p in paths:
        try:
            out.append(str(p.relative_to(out_dir)))
        except ValueError:
            out.append(str(p))
    return out


def resolve_pdf_path(out_dir: Path, raw: str | None) -> Path | None:
    """Locate a manifest PDF path on this machine.

    Docker Compose mounts PAPERFUL_DATA at /data, so older manifest lines may
    store absolute /data/out/... paths. Rewrite those to the configured out_dir
    when the original path is missing.
    """
    if not raw:
        return None
    path = Path(raw)
    if path.is_file():
        return path
    text = raw.replace("\\", "/")
    for prefix in ("/data/out/", "data/out/"):
        if text.startswith(prefix):
            alt = out_dir / text[len(prefix) :]
            if alt.is_file():
                return alt
    try:
        rel = path.relative_to("/data/out")
    except ValueError:
        rel = None
    if rel is not None:
        alt = out_dir / rel
        if alt.is_file():
            return alt
    return path if path.exists() else None
