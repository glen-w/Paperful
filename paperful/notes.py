"""Select and trash Paperful-owned notes. Never parent items."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Config
from .library import LibraryError
from .notehtml import PREFIX, parse
from .zot import Item

NOTE_TYPES = frozenset(PREFIX)
LLM_TYPES = frozenset({"summary", "review"})
FIXED_TAGS = {
    "paperful-found": "attach",
    "paperful-duplicate": "duplicate",
    "paperful-linked": "linked",
    "paperful:frontier-briefing": "briefing",
}


@dataclass(frozen=True)
class NoteHit:
    note_key: str
    parent_key: str
    title: str
    note_type: str
    model: str
    verb: str
    tags: tuple[str, ...]
    standalone: bool


def tag_types(cfg: Config) -> dict[str, str]:
    mapping = dict(FIXED_TAGS)
    mapping[(cfg.summarize_tag or "paperful-summary").strip().lower()] = "summary"
    mapping[(cfg.synthesize_tag or "paperful-report").strip().lower()] = "review"
    prefix = (cfg.snowball_tag_prefix or "paperful-snowball").strip().lower()
    if prefix:
        mapping[prefix] = "snowball"
    return mapping


def _tags_of(data: dict[str, Any]) -> tuple[str, ...]:
    out: list[str] = []
    for row in data.get("tags") or []:
        if isinstance(row, dict) and row.get("tag"):
            out.append(str(row["tag"]))
        elif isinstance(row, str) and row.strip():
            out.append(row)
    return tuple(out)


def identify(
    html: str,
    tags: tuple[str, ...],
    cfg: Config,
) -> tuple[str, str, str] | None:
    """Return (type, model, verb) when this is a Paperful note."""
    meta = parse(html) or {}
    kind = str(meta.get("type") or "").strip().lower()
    if kind in NOTE_TYPES:
        return kind, str(meta.get("model") or ""), str(meta.get("verb") or "")
    known = tag_types(cfg)
    snowball = (cfg.snowball_tag_prefix or "paperful-snowball").strip().lower()
    for tag in tags:
        low = tag.strip().lower()
        if low in known:
            return known[low], str(meta.get("model") or ""), str(meta.get("verb") or "")
        if snowball and (low == snowball or low.startswith(snowball + ":")):
            return "snowball", "", ""
    return None


def collect(
    backend: Any,
    items: list[Item],
    cfg: Config,
    *,
    collections: list[Any] | None = None,
) -> list[NoteHit]:
    """Child notes from scoped parents, plus standalone collection notes."""
    hits: list[NoteHit] = []
    seen: set[str] = set()
    for item in items:
        try:
            kids = backend.children(item.key)
        except LibraryError:
            continue
        for ch in kids or []:
            data = ch.get("data") or {}
            if data.get("itemType") != "note":
                continue
            key = str(ch.get("key") or "")
            if not key or key in seen:
                continue
            tags = _tags_of(data)
            ident = identify(str(data.get("note") or ""), tags, cfg)
            if ident is None:
                continue
            kind, model, verb = ident
            seen.add(key)
            hits.append(
                NoteHit(
                    note_key=key,
                    parent_key=item.key,
                    title=item.title,
                    note_type=kind,
                    model=model,
                    verb=verb,
                    tags=tags,
                    standalone=False,
                )
            )
    for col in collections or []:
        col_key = str(getattr(col, "key", "") or "")
        path = str(getattr(col, "path", "") or col_key)
        if not col_key:
            continue
        finder = getattr(backend, "find_collection_note_keys", None)
        if not callable(finder):
            continue
        wanted = set(tag_types(cfg))
        keys: list[str] = []
        for tag in wanted:
            try:
                keys.extend(finder(col_key, tag))
            except (LibraryError, AttributeError):
                continue
        for key in keys:
            if not key or key in seen:
                continue
            raw = backend.raw_item(key) if hasattr(backend, "raw_item") else None
            data = (raw or {}).get("data") or raw or {}
            if data.get("itemType") != "note":
                continue
            tags = _tags_of(data)
            ident = identify(str(data.get("note") or ""), tags, cfg)
            if ident is None:
                continue
            kind, model, verb = ident
            seen.add(key)
            hits.append(
                NoteHit(
                    note_key=key,
                    parent_key="",
                    title=path,
                    note_type=kind,
                    model=model,
                    verb=verb,
                    tags=tags,
                    standalone=True,
                )
            )
    return hits


def select(
    hits: list[NoteHit],
    *,
    types: frozenset[str] | None,
    model: str,
    except_model: str,
    all_owned: bool,
) -> list[NoteHit]:
    want_model = model.strip()
    skip_model = except_model.strip()
    out: list[NoteHit] = []
    for hit in hits:
        if not all_owned:
            if types is not None and hit.note_type not in types:
                continue
            elif types is None and skip_model and hit.note_type not in LLM_TYPES:
                continue
        if want_model and hit.model != want_model:
            continue
        if skip_model and hit.model == skip_model:
            continue
        out.append(hit)
    return out


def apply_delete(backend: Any, hits: list[NoteHit]) -> tuple[int, list[str]]:
    ok = 0
    errors: list[str] = []
    for hit in hits:
        try:
            backend.trash_note(hit.note_key, parent_key=hit.parent_key)
            ok += 1
        except LibraryError as exc:
            errors.append(f"{hit.note_key}: {exc}")
        except Exception as exc:  # adapter bugs should not abort the batch
            errors.append(f"{hit.note_key}: {type(exc).__name__}: {exc}")
    return ok, errors
