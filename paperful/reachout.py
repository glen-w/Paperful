"""Contact-only reachout: missing PDFs, emails, optional ResearchGate handoff.

Never fetches. Paperful does not send mail or click ResearchGate.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote

from .config import Config
from .snowball.authors import PackAuthor, name_fingerprint
from .zot import Item

NON_OA_SURFACES = frozenset({"paywalled", "no_oa", "license_blocked"})
_IMAGE_TLDS = frozenset({"png", "jpg", "jpeg", "gif", "webp", "svg", "pdf", "tif", "tiff"})
_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+\-])([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24})",
    re.I,
)
_CORRESPONDENCE = re.compile(
    r"correspond(?:ing|ence)|corresponding\s+author",
    re.I,
)
Getter = Callable[[str, dict[str, str], dict[str, str]], Any]


@dataclass
class ReachoutRow:
    key: str
    title: str
    year: str = ""
    author: str = ""
    email: str = ""
    email_source: str = ""
    doi: str = ""
    oa_status: str = ""
    miss_surface: str = ""
    request_url: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "title": self.title,
            "year": self.year,
            "author": self.author,
            "email": self.email,
            "email_source": self.email_source,
            "doi": self.doi,
            "oa_status": self.oa_status,
            "miss_surface": self.miss_surface,
            "request_url": self.request_url,
        }


def extract_emails_from_text(text: str) -> list[str]:
    """Addresses in free text. Prefer a correspondence line when one exists."""
    raw = (text or "").strip()
    if not raw:
        return []
    preferred: list[str] = []
    rest: list[str] = []
    for line in raw.replace("\r", "\n").split("\n"):
        found = _clean_emails(_EMAIL_RE.findall(line))
        if not found:
            continue
        if _CORRESPONDENCE.search(line):
            preferred.extend(found)
        else:
            rest.extend(found)
    return _dedupe(preferred + rest)


def emails_from_item(item: Item) -> list[str]:
    """Corresponding / metadata emails on the library item (no web scrape)."""
    chunks: list[str] = []
    url = (item.url or "").strip()
    if url.lower().startswith("mailto:"):
        chunks.append(unquote(url[7:].split("?", 1)[0]))
    extra = item.extra or ""
    abstract = item.abstract or ""
    chunks.append(extra)
    chunks.append(abstract)
    return extract_emails_from_text("\n".join(chunks))


def load_contact_emails(cfg: Config) -> dict[str, list[str]]:
    """fingerprint → emails from ``state/author-contacts/``."""
    folder = cfg.state_dir / "author-contacts"
    if not folder.is_dir():
        return {}
    out: dict[str, list[str]] = {}
    for path in folder.glob("*.json"):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(body, dict):
            continue
        fp = str(body.get("fingerprint") or "").strip()
        emails = body.get("emails")
        if not fp or not isinstance(emails, list):
            continue
        cleaned = _clean_emails([str(e) for e in emails if e])
        if cleaned:
            out[fp] = cleaned
    return out


def primary_author(item: Item) -> str:
    surnames = [s for s in (item.creator_surnames or []) if s]
    if item.first_author and " " in item.first_author.strip():
        return item.first_author.strip()
    if surnames:
        return surnames[0]
    return (item.first_author or "").strip()


def author_fingerprints(item: Item) -> list[str]:
    from .twenty import authors_from_items

    return [a.fingerprint for a in authors_from_items([item]) if a.fingerprint]


def _clean_emails(emails: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in emails:
        email = raw.strip().rstrip(".,;:)>]")
        if email.lower().startswith("mailto:"):
            email = unquote(email[7:].split("?", 1)[0]).strip()
        if "@" not in email:
            continue
        local, _, host = email.rpartition("@")
        tld = host.rsplit(".", 1)[-1].lower()
        if tld in _IMAGE_TLDS:
            continue
        if not local or "." not in host:
            continue
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(email)
    return out


def _dedupe(emails: list[str]) -> list[str]:
    return _clean_emails(emails)


def _email_from_cache(item: Item, cache: dict[str, list[str]]) -> str:
    for fp in author_fingerprints(item):
        hit = cache.get(fp) or []
        if hit:
            return hit[0]
    return ""


def _lookup_missing(
    cfg: Config,
    items: list[Item],
    cache: dict[str, list[str]],
    *,
    getter: Getter | None = None,
) -> dict[str, list[str]]:
    from .twenty import (
        search_people,
        split_display_name,
        unique_match,
        work_emails,
        write_contact,
    )

    for item in items:
        if _email_from_cache(item, cache):
            continue
        name = primary_author(item)
        if not name:
            continue
        last, first = split_display_name(name)
        if not last:
            continue
        hits = search_people(cfg, last_name=last, first_name=first, getter=getter)
        hit = unique_match(hits, last, first)
        if hit is None:
            continue
        emails = work_emails(hit.emails)
        if not emails:
            continue
        fp = name_fingerprint(name)
        if not fp:
            continue
        author = PackAuthor(name=name, fingerprint=fp)
        write_contact(cfg, author, hit)
        cache[fp] = emails
    return cache


def build_reachout_rows(
    cfg: Config,
    items: list[Item],
    *,
    non_oa_only: bool = False,
    lookup: bool = False,
    getter: Getter | None = None,
    re_request: bool = False,
    manifest: Any | None = None,
) -> list[ReachoutRow]:
    """One row per missing-PDF item. Metadata email beats Twenty."""
    from .handoff import list_missing_pdfs
    from .store import Manifest
    from .twenty import twenty_ready

    man = manifest if manifest is not None else Manifest(cfg.manifest_path)
    missing = list_missing_pdfs(items, man, cfg=cfg, re_request=re_request)
    by_key = {it.key: it for it in items}
    if non_oa_only:
        missing = [m for m in missing if m.miss_surface in NON_OA_SURFACES]
    cache = load_contact_emails(cfg) if cfg.twenty_enabled else {}
    need_lookup = [
        by_key[m.key]
        for m in missing
        if m.key in by_key
        and not emails_from_item(by_key[m.key])
        and not _email_from_cache(by_key[m.key], cache)
    ]
    if lookup and twenty_ready(cfg) and need_lookup:
        _lookup_missing(cfg, need_lookup, cache, getter=getter)
        cache = load_contact_emails(cfg) or cache

    rows: list[ReachoutRow] = []
    for miss in missing:
        item = by_key.get(miss.key)
        if item is None:
            continue
        meta = emails_from_item(item)
        email = meta[0] if meta else ""
        source = "metadata" if email else ""
        if not email:
            email = _email_from_cache(item, cache)
            if email:
                source = "twenty"
        rows.append(
            ReachoutRow(
                key=item.key,
                title=item.title,
                year=str(item.year) if item.year else "",
                author=primary_author(item),
                email=email,
                email_source=source,
                doi=item.doi or miss.doi or "",
                oa_status=miss.oa_status,
                miss_surface=miss.miss_surface,
                request_url=miss.request_url,
            )
        )
    return rows


def write_reachout_export(rows: list[ReachoutRow], path: Path) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "key",
        "title",
        "year",
        "author",
        "email",
        "email_source",
        "doi",
        "oa_status",
        "miss_surface",
        "request_url",
    ]
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        header = "| " + " | ".join(c.replace("_", " ").title() for c in cols) + " |"
        sep = "| " + " | ".join("---" for _ in cols) + " |"
        lines = ["# Reachout", "", header, sep]
        for row in rows:
            cells = [(row.as_dict().get(c) or "-").replace("|", "\\|") for c in cols]
            lines.append("| " + " | ".join(cells) + " |")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
    delimiter = "\t" if suffix in {".tsv", ".tab"} else ","
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=delimiter)
        writer.writerow(cols)
        for row in rows:
            d = row.as_dict()
            writer.writerow([d[c] for c in cols])
    return path
