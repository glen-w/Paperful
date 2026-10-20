"""Save a browser page into the quiet mirror.

Reads the mirror and, when the manager answers, the live library. Writes
``out/`` only. Does not create library parents and does not attach.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import os
import re
import secrets
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .config import Config
from .download import looks_like_pdf
from .library import LibraryError, get_backend
from .resolve import normalize_doi
from .store import (
    STATUS_OK,
    Manifest,
    Record,
    empty_item_record,
    item_filename,
    item_key_from_dirname,
    items_from_mirror,
    load_json,
    write_json,
)
from .zot import SKIP_TYPES, Item, item_from_json

# Hosts the add-on and the host both refuse. Suffixes ending in "." match
# any registrable label after that stem (sci-hub.se). The others are exact
# hosts, or a subdomain of that host.
REFUSED_HOSTS = (
    "sci-hub.",
    "libgen.",
    "annas-archive.org",
    "libgen.rs",
    "libgen.is",
    "libgen.li",
    "library.lol",
)

DOI_MAX = 256
URL_MAX = 2048
TITLE_MAX = 500
ABSTRACT_MAX = 8000
AUTHOR_MAX = 200
NOTE_MAX = 4000
COLLECTION_MAX = 200
PDF_MAX_BYTES = 150_000_000
HTML_MAX_BYTES = 8_000_000
SNAPSHOT_NAME = "snapshot.html"
SESSION_SCHEMA = "paperful.handoff.session.v1"
_COLL_OK = re.compile(r"^[\w .,'&()+\-]+(?:/[\w .,'&()+\-]+)*$", re.UNICODE)
WORKBENCH_DEFAULT = "http://127.0.0.1:8765"


@dataclass
class IdentityIndex:
    items: list[Item]
    by_doi: dict[str, list[Item]]
    by_url: dict[str, list[Item]]
    live: Any | None
    zotero_up: bool
    refreshed: bool
    collections: dict[str, Any] = field(default_factory=dict)


@dataclass
class Match:
    action: str
    key: str = ""
    has_pdf: bool = False
    reason: str = ""
    duplicate_local: str = ""
    candidates: list[str] = field(default_factory=list)
    maybe: list[dict[str, Any]] = field(default_factory=list)
    hits: dict[str, Item] = field(default_factory=dict)


def clip(value: Any, limit: int) -> str:
    text = str(value or "").replace("\x00", "")
    return text[:limit]


def as_year(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    if year < 1000 or year > 3000:
        return None
    return year


def normalize_url(url: str | None) -> str:
    """Lowercase host, no fragment, one trailing slash removed."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ""
    host = parts.hostname.lower().rstrip(".")
    netloc = host
    if parts.port and not (
        (parts.scheme == "https" and parts.port == 443)
        or (parts.scheme == "http" and parts.port == 80)
    ):
        netloc = f"{host}:{parts.port}"
    path = parts.path or ""
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return urlunsplit((parts.scheme, netloc, path, parts.query, ""))


def host_refused(url: str | None) -> bool:
    host = (urlsplit(url or "").hostname or "").lower().rstrip(".")
    if not host:
        return False
    labels = host.split(".")
    for suffix in REFUSED_HOSTS:
        if suffix.endswith("."):
            stem = suffix[:-1]
            if stem in labels or host.startswith(suffix):
                return True
            continue
        if host == suffix or host.endswith("." + suffix):
            return True
    return False


def drop_dir(cfg: Config) -> Path:
    if cfg.extension_drop.strip():
        path = Path(cfg.extension_drop).expanduser()
    elif (cfg.inbox_dir or "").strip():
        path = Path(cfg.inbox_dir).expanduser()
    else:
        path = cfg.state_dir / "capture" / "drop"
    return path


def session_path(cfg: Config) -> Path:
    return cfg.state_dir / "handoff" / "session.json"


def read_session(cfg: Config) -> dict[str, Any]:
    data = load_json(session_path(cfg))
    if not isinstance(data, dict):
        return {"items": []}
    items = data.get("items")
    if not isinstance(items, list):
        data = {**data, "items": []}
    return data


def workbench_url() -> str:
    return (os.environ.get("PAPERFUL_UI") or WORKBENCH_DEFAULT).rstrip("/")


def safe_collection(raw: Any, fallback: str) -> str:
    text = clip(raw, COLLECTION_MAX).strip().replace("\\", "/").strip("/")
    fallback = clip(fallback, COLLECTION_MAX).strip() or "Capture"
    if not text or ".." in text.split("/"):
        return fallback
    if _COLL_OK.match(text):
        return text
    return fallback


def list_collection_paths(cfg: Config) -> list[str]:
    """Known collection paths for the add-on picker. Caps the native payload."""
    paths: set[str] = set()
    default = safe_collection(cfg.extension_collection, "Capture")
    paths.add(default)
    try:
        from .catalogue import MirrorCatalogue

        for coll in MirrorCatalogue(cfg.out_dir).collections().values():
            path = str(getattr(coll, "path", "") or "").strip()
            if path and not path.startswith("_"):
                paths.add(path)
    except Exception:
        pass
    try:
        if cfg.out_dir.is_dir():
            for child in cfg.out_dir.iterdir():
                if child.is_dir() and not child.name.startswith("_"):
                    paths.add(child.name)
    except OSError:
        pass
    return sorted(paths, key=str.casefold)[:200]


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


def stage_parents(cfg: Config) -> list[Path]:
    """Directories a just-downloaded file may be copied from into the drop dir."""
    parents = [drop_dir(cfg)]
    inbox = (cfg.inbox_dir or "").strip()
    if inbox:
        parents.append(Path(inbox).expanduser())
    home = Path.home()
    for name in ("Downloads", "downloads"):
        candidate = home / name
        if candidate.is_dir():
            parents.append(candidate)
    return parents


def stage_incoming(cfg: Config, src: str) -> dict[str, Any]:
    """Copy a browser download into the drop directory when the parent is allowed."""
    raw = clip(src, URL_MAX)
    if not raw:
        return {"ok": False, "reason": "invalid"}
    try:
        path = Path(raw).expanduser().resolve()
    except (OSError, ValueError):
        return {"ok": False, "reason": "invalid"}
    if not path.is_file():
        return {"ok": False, "reason": "invalid"}
    drop = drop_dir(cfg).resolve()
    drop.mkdir(parents=True, exist_ok=True)
    if _is_under(path, drop):
        return {"ok": True, "path": str(path), "staged": False}
    allowed = False
    for parent in stage_parents(cfg):
        try:
            resolved = parent.resolve()
        except OSError:
            continue
        if _is_under(path, resolved):
            allowed = True
            break
    if not allowed:
        return {"ok": False, "reason": "outside_drop", "drop": str(drop)}
    suffix = path.suffix.lower()
    try:
        size = path.stat().st_size
    except OSError:
        return {"ok": False, "reason": "refused"}
    if suffix == ".pdf":
        if size < cfg.min_pdf_bytes or size > PDF_MAX_BYTES:
            return {"ok": False, "reason": "refused"}
        try:
            head = path.read_bytes()[:16]
        except OSError:
            return {"ok": False, "reason": "refused"}
        if not looks_like_pdf(head):
            return {"ok": False, "reason": "refused"}
    elif suffix in {".html", ".htm"}:
        if size <= 0 or size > HTML_MAX_BYTES:
            return {"ok": False, "reason": "refused"}
    else:
        return {"ok": False, "reason": "refused"}
    dest = drop / path.name
    if dest.exists() and dest.resolve() != path:
        dest = drop / f"{path.stem}-{secrets.token_hex(3)}{path.suffix}"
    if dest.resolve() != path:
        try:
            shutil.copyfile(path, dest)
        except OSError:
            return {"ok": False, "reason": "refused"}
        return {"ok": True, "path": str(dest.resolve()), "staged": True}
    return {"ok": True, "path": str(path), "staged": False}


def reveal_path(path: Path, opener: Any = None) -> None:
    """Open a folder the host already resolved (drop dir or an item folder)."""
    fn = opener or _reveal
    fn(path)


def _reveal(path: Path) -> None:
    target = str(path)
    if sys.platform == "darwin":
        subprocess.Popen(["open", target], start_new_session=True)
    elif sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", target], start_new_session=True)


def open_target(
    cfg: Config,
    kind: str,
    key: str = "",
    *,
    opener: Any = None,
) -> dict[str, Any]:
    """Reveal the drop directory, the mirror root, or one item folder."""
    want = str(kind or "").strip().lower()
    if want == "drop":
        path = drop_dir(cfg)
        path.mkdir(parents=True, exist_ok=True)
    elif want == "out":
        path = Path(cfg.out_dir)
    elif want == "item":
        files = _record_files(cfg.out_dir, clip(key, 64))
        if not files:
            return {"ok": False, "reason": "missing_item"}
        path = files[0].parent
    else:
        return {"ok": False, "reason": "invalid"}
    try:
        resolved = path.resolve()
    except OSError:
        return {"ok": False, "reason": "invalid"}
    reveal_path(resolved, opener=opener)
    return {"ok": True, "path": str(resolved)}


def mark_session_saved(cfg: Config, keys: list[Any]) -> dict[str, Any]:
    """Stamp matching handoff rows so the tab checklist can drop them."""
    want = {clip(key, 64) for key in keys if clip(key, 64)}
    data = read_session(cfg)
    items = data.get("items")
    if not want or not isinstance(items, list):
        return {"ok": True, "marked": 0, **data}
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    marked = 0
    for row in items:
        if not isinstance(row, dict):
            continue
        if clip(row.get("key"), 64) in want and not row.get("saved_at"):
            row["saved_at"] = now
            marked += 1
    if marked:
        write_json(session_path(cfg), data)
    return {"ok": True, "marked": marked, **data}


def _open_live(cfg: Config) -> Any | None:
    try:
        backend = get_backend(cfg)
        backend.ping()
    except Exception:
        return None
    return backend


def _search_rows(backend: Any, query: str) -> list[dict[str, Any]]:
    getter = getattr(backend, "get", None)
    if getter is None:
        zl = getattr(backend, "zl", None)
        getter = getattr(zl, "get", None) if zl is not None else None
    if getter is None or not query:
        return []
    try:
        resp = getter("/items", q=query, qmode="everything", limit=25)
    except Exception:
        return []
    rows = resp.json() if hasattr(resp, "json") else resp
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _live_items(index: IdentityIndex, query: str) -> list[Item]:
    if index.live is None or not index.zotero_up:
        return []
    found: list[Item] = []
    for row in _search_rows(index.live, query):
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        if str(data.get("itemType") or "") in SKIP_TYPES:
            continue
        if "key" not in row or "data" not in row:
            continue
        try:
            found.append(item_from_json(row, index.collections, None))
        except (KeyError, TypeError, ValueError):
            continue
    return found


def prepare(
    cfg: Config,
    *,
    opener: Any = None,
    run_sync_fn: Any = None,
) -> IdentityIndex:
    """One refresh (when snapshot is auto) and a mirror index.

    ``opener`` returns the live backend or None. The default pings the
    manager. A failure does not abort capture.
    """
    open_fn = opener or _open_live
    live = open_fn(cfg)
    refreshed = False
    if live is not None and cfg.extension_snapshot == "auto":
        sync = run_sync_fn
        if sync is None:
            from .sync import run_sync as sync
        try:
            sync(cfg, live, backfill=False)
            refreshed = True
        except LibraryError:
            refreshed = False
        except Exception:
            refreshed = False
    collections: dict[str, Any] = {}
    if live is not None and hasattr(live, "collections"):
        try:
            loaded = live.collections() or {}
            if isinstance(loaded, dict):
                collections = loaded
        except Exception:
            collections = {}
    items = items_from_mirror(cfg.out_dir)
    by_doi: dict[str, list[Item]] = {}
    by_url: dict[str, list[Item]] = {}
    for item in items:
        doi = normalize_doi(item.doi) if item.doi else None
        if doi:
            by_doi.setdefault(doi, []).append(item)
        url = normalize_url(item.url)
        if url:
            by_url.setdefault(url, []).append(item)
    return IdentityIndex(
        items=items,
        by_doi=by_doi,
        by_url=by_url,
        live=live,
        zotero_up=live is not None,
        refreshed=refreshed,
        collections=collections,
    )


def _choose(mirror_items: list[Item], live_items: list[Item]) -> Match | None:
    hits: dict[str, Item] = {}
    for item in mirror_items + live_items:
        hits[item.key] = item
    live_keys = list(dict.fromkeys(item.key for item in live_items))
    mirror_keys = list(dict.fromkeys(item.key for item in mirror_items))
    if len(live_keys) > 1:
        return Match(
            action="ambiguous",
            candidates=sorted(set(live_keys)),
            hits=hits,
        )
    if len(live_keys) == 1:
        key = live_keys[0]
        same = next((item for item in mirror_items if item.key == key), None)
        pf = next(
            (k for k in mirror_keys if k != key and k.startswith("pf")),
            "",
        )
        return Match(
            action="update",
            key=key,
            has_pdf=bool(same and same.has_pdf),
            duplicate_local=pf,
            hits=hits,
        )
    if len(set(mirror_keys)) > 1:
        return Match(
            action="ambiguous",
            candidates=sorted(set(mirror_keys)),
            hits=hits,
        )
    if len(mirror_keys) == 1:
        item = hits[mirror_keys[0]]
        return Match(
            action="update",
            key=item.key,
            has_pdf=bool(item.has_pdf),
            hits=hits,
        )
    return None


def lookup(
    index: IdentityIndex,
    *,
    doi: str = "",
    url: str = "",
    title: str = "",
    year: int | None = None,
    pdf_url: str = "",
) -> Match:
    if host_refused(url) or host_refused(pdf_url):
        return Match(action="blocked", reason="refused_host")
    doi_n = normalize_doi(clip(doi, DOI_MAX)) if doi else None
    chosen: Match | None = None
    if doi_n:
        live = [
            item
            for item in _live_items(index, doi_n)
            if normalize_doi(item.doi) == doi_n
        ]
        chosen = _choose(list(index.by_doi.get(doi_n, [])), live)
    if chosen is None:
        url_n = normalize_url(url)
        if url_n:
            live = [
                item
                for item in _live_items(index, url)
                if normalize_url(item.url) == url_n
            ]
            chosen = _choose(list(index.by_url.get(url_n, [])), live)
    if chosen is None:
        if index.zotero_up:
            chosen = Match(action="create")
        else:
            chosen = Match(action="blocked", reason="zotero_unread")
    skip = {chosen.key} if chosen.key else set()
    want = title.casefold().strip()
    if want and year is not None:
        for item in index.items:
            if item.key in skip:
                continue
            if (item.title or "").casefold().strip() == want and item.year == year:
                chosen.maybe.append(
                    {"key": item.key, "title": item.title, "year": item.year}
                )
    return chosen


def plan_dict(
    index: IdentityIndex,
    match: Match,
    *,
    doi: str,
    url: str,
    title: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "action": match.action,
        "key": match.key,
        "has_pdf": match.has_pdf,
        "zotero_up": index.zotero_up,
        "refreshed": index.refreshed,
        "reason": match.reason,
        "duplicate_local": match.duplicate_local,
        "candidates": list(match.candidates),
        "maybe": list(match.maybe),
        "doi": doi,
        "url": url,
        "title": title,
    }


def plan_page(
    cfg: Config,
    *,
    doi: str = "",
    url: str = "",
    title: str = "",
    year: int | None = None,
    pdf_url: str = "",
    index: IdentityIndex | None = None,
    opener: Any = None,
    run_sync_fn: Any = None,
) -> dict[str, Any]:
    doi = clip(doi, DOI_MAX)
    url = clip(url, URL_MAX)
    title = clip(title, TITLE_MAX)
    pdf_url = clip(pdf_url, URL_MAX)
    if host_refused(url) or host_refused(pdf_url):
        empty = IdentityIndex([], {}, {}, None, False, False)
        match = Match(action="blocked", reason="refused_host")
        return plan_dict(empty, match, doi=doi, url=url, title=title)
    if index is None:
        index = prepare(cfg, opener=opener, run_sync_fn=run_sync_fn)
    match = lookup(
        index, doi=doi, url=url, title=title, year=year, pdf_url=pdf_url
    )
    return plan_dict(index, match, doi=doi, url=url, title=title)


def _record_files(out_dir: Path, key: str) -> list[Path]:
    if not out_dir.is_dir() or not key:
        return []
    found: list[Path] = []
    for path in out_dir.rglob("record.json"):
        try:
            rel = path.relative_to(out_dir)
        except ValueError:
            continue
        if any(part.startswith("_") for part in rel.parts):
            continue
        if item_key_from_dirname(path.parent.name) == key:
            found.append(path)
    return found


def _folder_has_pdf(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    return any(path.is_file() and path.stat().st_size > 0 for path in folder.glob("*.pdf"))


def _fill_blanks(rec: dict[str, Any], page: dict[str, Any]) -> None:
    abstract = clip(page.get("abstract"), ABSTRACT_MAX).strip()
    if not str(rec.get("abstract") or "").strip() and abstract:
        rec["abstract"] = abstract
    url = clip(page.get("url"), URL_MAX).strip()
    if not str(rec.get("url") or "").strip() and url:
        rec["url"] = url
    pub = clip(page.get("publication_title"), TITLE_MAX).strip()
    if not str(rec.get("publication_title") or "").strip() and pub:
        rec["publication_title"] = pub
    title = clip(page.get("title"), TITLE_MAX).strip()
    if not str(rec.get("title") or "").strip() and title:
        rec["title"] = title
    year = as_year(page.get("year"))
    if rec.get("year") in (None, "", 0) and year is not None:
        rec["year"] = year
    creators = rec.get("creators")
    authors = _authors(page.get("authors"))
    if (not isinstance(creators, list) or not creators) and authors:
        rec["creators"] = [
            {"creatorType": "author", "lastName": name} for name in authors
        ]
    if not str(rec.get("doi") or "").strip():
        doi = normalize_doi(clip(page.get("doi"), DOI_MAX))
        if doi:
            rec["doi"] = doi
            rec["library_doi"] = doi
            rec["doi_source"] = "url"


def _authors(raw: Any) -> list[str]:
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, list):
        parts = [str(part).strip() for part in raw]
    else:
        return []
    out: list[str] = []
    for part in parts:
        name = clip(part, AUTHOR_MAX).strip()
        if name:
            out.append(name)
        if len(out) >= 20:
            break
    return out


def _page_from(body: dict[str, Any]) -> dict[str, Any]:
    page = body.get("page")
    merged: dict[str, Any] = {}
    if isinstance(page, dict):
        merged.update(page)
    for key in (
        "doi",
        "url",
        "title",
        "year",
        "pdf_url",
        "abstract",
        "publication_title",
        "authors",
    ):
        if key not in merged and body.get(key) not in (None, ""):
            merged[key] = body.get(key)
    return merged


def _key_taken(index: IdentityIndex, key: str) -> bool:
    if any(item.key == key for item in index.items):
        return True
    if index.live is None:
        return False
    getter = getattr(index.live, "get", None)
    if getter is None:
        zl = getattr(index.live, "zl", None)
        getter = getattr(zl, "get", None) if zl is not None else None
    if getter is None:
        return False
    try:
        getter(f"/items/{key}")
    except Exception:
        return False
    return True


def _new_key(index: IdentityIndex) -> str:
    for _ in range(8):
        key = "pf" + secrets.token_hex(3)
        if not _key_taken(index, key):
            return key
    raise RuntimeError("could not allocate a mirror key")


def _pdf_source(cfg: Config, url: str) -> str:
    base = urlsplit(cfg.ezproxy_base or "")
    page = urlsplit(url or "")
    if (
        base.hostname
        and page.hostname
        and base.hostname.lower() == page.hostname.lower()
    ):
        return "campus:ezproxy"
    return "web:extension"


def _inside_drop(cfg: Config, pdf_path: str) -> Path | None:
    drop = drop_dir(cfg).resolve()
    try:
        path = Path(pdf_path).expanduser().resolve()
        path.relative_to(drop)
    except (OSError, ValueError):
        return None
    return path


def _place_pdf(
    cfg: Config,
    folder: Path,
    item: Item,
    pdf_path: str,
    page_url: str,
) -> str:
    """Copy a drop-dir PDF beside the record. ``kept`` when one is already there."""
    if _folder_has_pdf(folder):
        return "kept"
    if not pdf_path:
        return "none"
    path = _inside_drop(cfg, pdf_path)
    if path is None or not path.is_file():
        return "refused"
    try:
        content = path.read_bytes()
    except OSError:
        return "refused"
    if not looks_like_pdf(content) or len(content) < cfg.min_pdf_bytes:
        return "refused"
    dest = folder / item_filename(item)
    if dest.exists():
        return "kept"
    dest.write_bytes(content)
    digest = hashlib.md5(content).hexdigest()
    source = _pdf_source(cfg, page_url)
    Manifest(cfg.manifest_path).write(
        Record(
            itemKey=item.key,
            status=STATUS_OK,
            title=item.title,
            doi=item.doi,
            source=source,
            url=page_url or None,
            path=str(dest),
            md5=digest,
            attempts=[f"{source}:extension"],
        )
    )
    return "saved"


_SCRIPT_BLOCK = re.compile(r"(?is)<script\b[^>]*>.*?</script>")
_SCRIPT_TAG = re.compile(r"(?is)<script\b[^>]*/?>")
_FRAME_BLOCK = re.compile(r"(?is)<(iframe|object|embed)\b[^>]*>.*?</\1>")
_FRAME_TAG = re.compile(r"(?is)<(iframe|object|embed)\b[^>]*/?>")
_ON_ATTR = re.compile(r"""(?i)\s+on[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""")
_JS_URL = re.compile(r"(?i)javascript\s*:")


def _strip_active_html(text: str) -> str:
    """Drop scripts and event handlers so a saved page does not run when opened."""
    cleaned = _SCRIPT_BLOCK.sub("", text)
    cleaned = _SCRIPT_TAG.sub("", cleaned)
    cleaned = _FRAME_BLOCK.sub("", cleaned)
    cleaned = _FRAME_TAG.sub("", cleaned)
    cleaned = _ON_ATTR.sub("", cleaned)
    return _JS_URL.sub("", cleaned)


def _looks_like_html(text: str) -> bool:
    sample = text.lstrip()[:400].lower()
    return sample.startswith("<!doctype html") or sample.startswith("<html") or "<html" in sample


def _note_snapshot(cfg: Config, key: str, page_url: str) -> None:
    for path in _record_files(cfg.out_dir, key):
        rec = load_json(path) or {}
        rows = rec.get("attachments")
        if not isinstance(rows, list):
            rows = []
        if not any(
            isinstance(row, dict) and row.get("filename") == SNAPSHOT_NAME for row in rows
        ):
            rows.append(
                {
                    "filename": SNAPSHOT_NAME,
                    "contentType": "text/html",
                    "linkMode": "imported_file",
                    "title": "Snapshot",
                    "url": page_url or "",
                    "note": "snapshot:extension",
                }
            )
        rec["attachments"] = rows
        fetch = rec.get("fetch")
        if not isinstance(fetch, dict):
            fetch = {}
        fetch["snapshot"] = "extension"
        rec["fetch"] = fetch
        write_json(path, rec)


def _place_note(folder: Path, item: Item, note_text: str) -> str:
    """Write a capture remark under notes/. Mirror only; no library child note."""
    text = clip(note_text, NOTE_MAX).strip()
    if not text:
        return "none"
    from .notehtml import wrap

    notes_dir = folder / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    dest = notes_dir / "paperful-capture.html"
    body = "<p>" + html_lib.escape(text).replace("\n", "<br>\n") + "</p>"
    dest.write_text(
        wrap(body, note_type="capture", verb="capture", extra=item.key),
        encoding="utf-8",
    )
    rec_path = folder / "record.json"
    rec = load_json(rec_path) or {}
    rows = rec.get("notes")
    if not isinstance(rows, list):
        rows = []
    if not any(
        isinstance(row, dict) and row.get("file") == "paperful-capture.html"
        for row in rows
    ):
        rows.append({"file": "paperful-capture.html", "tag": "paperful-capture"})
    rec["notes"] = rows
    write_json(rec_path, rec)
    return "saved"


def _place_html(
    cfg: Config,
    folder: Path,
    item: Item,
    html_path: str,
    page_url: str,
) -> str:
    """Copy a page snapshot beside the record when the item has no PDF."""
    if _folder_has_pdf(folder):
        return "none"
    dest = folder / SNAPSHOT_NAME
    if dest.is_file() and dest.stat().st_size > 0:
        return "kept"
    if not html_path:
        return "none"
    path = _inside_drop(cfg, html_path)
    if path is None or not path.is_file():
        return "refused"
    if path.suffix.lower() not in {".html", ".htm"}:
        return "refused"
    try:
        if path.stat().st_size > HTML_MAX_BYTES:
            return "refused"
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "refused"
    if not _looks_like_html(text):
        return "refused"
    dest.write_text(_strip_active_html(text), encoding="utf-8")
    _note_snapshot(cfg, item.key, page_url)
    return "saved"


def _pull_snapshot(
    cfg: Config,
    index: IdentityIndex,
    item: Item,
    snapshot_item_fn: Any,
) -> None:
    if _record_files(cfg.out_dir, item.key):
        return
    fn = snapshot_item_fn
    if fn is None:
        from .snapshot import snapshot_item as fn
    fn(
        cfg.out_dir,
        item,
        index.live,
        index.collections,
        cfg.summaries_dir,
        cfg.mirror_pdfs,
        dry_run=False,
    )


def _remember(index: IdentityIndex, item: Item) -> None:
    index.items.append(item)
    doi = normalize_doi(item.doi) if item.doi else None
    if doi:
        index.by_doi.setdefault(doi, []).append(item)
    url = normalize_url(item.url)
    if url:
        index.by_url.setdefault(url, []).append(item)


def _fail(reason: str, **extra: Any) -> dict[str, Any]:
    body = {"ok": False, "action": "blocked", "reason": reason, "code": 2}
    body.update(extra)
    return body


def _run_lanes(cfg: Config, key: str, run_fetch_fn: Any) -> str:
    import sys

    fn = run_fetch_fn
    if fn is None:
        from .run_cmd import run_fetch as fn

        def _call() -> None:
            from rich.console import Console

            fn(
                Console(file=sys.stderr, highlight=False),
                cfg,
                collection=[],
                library=True,
                dry_run=False,
                year_from=None,
                year_to=None,
                item_type=[],
                limit=None,
                no_attach=True,
                retry_failed=False,
                try_all=False,
                sources=None,
                preset=None,
                scihub=False,
                relogin=False,
                browser_agent=False,
                upgrade_linked=False,
                want_snapshot_upgrade=False,
                strict_pdf_doi=False,
                handoff=None,
                include_doi_tabs=False,
                downloads_dir=None,
                re_request=False,
                json_out=False,
                item_keys=[key],
                force_mirror_only=True,
            )

        try:
            _call()
        except Exception:
            return "error"
        return "ok"
    try:
        fn(
            cfg,
            key,
            force_mirror_only=True,
            no_attach=True,
            scihub=False,
        )
    except Exception:
        return "error"
    return "ok"


def apply_page(
    cfg: Config,
    body: dict[str, Any],
    *,
    index: IdentityIndex | None = None,
    opener: Any = None,
    run_sync_fn: Any = None,
    snapshot_item_fn: Any = None,
    run_fetch_fn: Any = None,
) -> dict[str, Any]:
    """Re-check identity, then write the mirror. Client-supplied keys do not win."""
    if not isinstance(body, dict):
        return _fail("invalid")
    page = _page_from(body)
    doi = clip(page.get("doi"), DOI_MAX)
    url = clip(page.get("url"), URL_MAX)
    title = clip(page.get("title"), TITLE_MAX)
    pdf_url = clip(page.get("pdf_url") or body.get("pdf_url"), URL_MAX)
    year = as_year(page.get("year"))
    if host_refused(url) or host_refused(pdf_url):
        return _fail("refused_host")
    if index is None:
        index = prepare(cfg, opener=opener, run_sync_fn=run_sync_fn)
    match = lookup(
        index, doi=doi, url=url, title=title, year=year, pdf_url=pdf_url
    )
    if match.action == "blocked" and match.reason == "refused_host":
        return _fail("refused_host")
    if match.action == "ambiguous":
        confirm = str(body.get("confirm_key") or "")
        if confirm not in match.candidates:
            return _fail("ambiguous", candidates=match.candidates)
        match.action = "update"
        match.key = confirm
    if match.action == "blocked":
        if match.reason == "zotero_unread" and body.get("allow_unread") is True:
            match = Match(action="create")
        else:
            return _fail(match.reason or "blocked")

    page = {
        **page,
        "doi": doi,
        "url": url,
        "title": title,
        "year": year,
    }
    pdf_path = str(body.get("pdf_path") or "")
    html_path = str(body.get("html_path") or "")
    collection = safe_collection(
        body.get("collection"), cfg.extension_collection or "Capture"
    )
    if match.action == "create":
        if not index.zotero_up and body.get("allow_unread") is not True:
            return _fail("zotero_unread")
        key = _new_key(index)
        authors = _authors(page.get("authors"))
        item = Item(
            key=key,
            item_type="journalArticle" if doi else "webpage",
            title=title or "(untitled)",
            doi=normalize_doi(doi) if doi else None,
            arxiv_id=None,
            url=url or None,
            year=year,
            first_author=authors[0] if authors else None,
            collection_paths=[collection],
            doi_source="url" if doi else "none",
            abstract=clip(page.get("abstract"), ABSTRACT_MAX).strip() or None,
            publication_title=clip(page.get("publication_title"), TITLE_MAX).strip()
            or None,
        )
        rec = empty_item_record(item)
        if authors:
            rec["creators"] = [
                {"creatorType": "author", "lastName": name} for name in authors
            ]
        rec["fetch"] = {"origin": "web:extension", "source": "web:extension"}
        from .mirror import place_item_dirs

        folders = place_item_dirs(cfg.out_dir, item)
        folder = folders[0]
        write_json(folder / "record.json", rec)
        _remember(index, item)
        placed = _place_pdf(cfg, folder, item, pdf_path, url)
    else:
        item = match.hits.get(match.key)
        if item is None:
            return _fail("missing_item")
        try:
            _pull_snapshot(cfg, index, item, snapshot_item_fn)
        except Exception as exc:
            return _fail("snapshot_failed", detail=str(exc))
        files = _record_files(cfg.out_dir, item.key)
        if not files:
            return _fail("snapshot_failed")
        for path in files:
            rec = load_json(path) or {}
            _fill_blanks(rec, page)
            write_json(path, rec)
        folder = files[0].parent
        # A snapshot may have copied a PDF the library already holds.
        if _folder_has_pdf(folder):
            item.has_pdf = True
        placed = _place_pdf(cfg, folder, item, pdf_path, url)
        _remember(index, item)

    snapshot = "none"
    if placed not in {"saved", "kept"} and not _folder_has_pdf(folder):
        snapshot = _place_html(cfg, folder, item, html_path, url)
    note = _place_note(folder, item, str(body.get("note") or ""))
    lanes = "skipped"
    if body.get("lanes") is True and placed != "saved" and placed != "kept":
        if not _folder_has_pdf(folder):
            lanes = _run_lanes(cfg, item.key, run_fetch_fn)
    if match.action != "create" and item.key:
        mark_session_saved(cfg, [item.key])
    result = {
        "ok": True,
        "action": "create" if match.action == "create" else "update",
        "key": item.key,
        "pdf": placed,
        "snapshot": snapshot,
        "note": note,
        "lanes": lanes,
        "folder": str(folder),
        "collection": collection if match.action == "create" else (
            (item.collection_paths or [""])[0]
        ),
        "reason": ""
        if placed in {"saved", "kept"} or snapshot in {"saved", "kept"}
        else "no_pdf",
        "duplicate_local": match.duplicate_local,
        "code": 0,
    }
    return result
