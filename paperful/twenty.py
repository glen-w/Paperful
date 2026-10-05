"""Read-only Twenty CRM author lookup. Opt-in; never writes to the CRM or sends mail."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

import httpx

from .config import Config
from .snowball.authors import (
    PackAuthor,
    classify_listing_url,
    host_of,
    load_pack_file,
    name_fingerprint,
    pack_path,
    pack_slug,
    write_pack,
    AuthorPack,
)
from .zot import Item

CONTACT_SCHEMA = "paperful.author_contact.v1"
_PERSONAL = (
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
    "live.com",
    "me.com",
)
Getter = Callable[[str, dict[str, str], dict[str, str]], Any]


def twenty_api_key() -> str:
    return (os.environ.get("TWENTY_API_KEY") or "").strip()


def twenty_base_url(cfg: Config) -> str:
    raw = (cfg.twenty_base_url or os.environ.get("TWENTY_BASE_URL") or "").strip()
    return raw.rstrip("/")


def twenty_ready(cfg: Config) -> bool:
    return bool(cfg.twenty_enabled and twenty_api_key() and twenty_base_url(cfg))


@dataclass
class PersonHit:
    twenty_id: str
    first_name: str = ""
    last_name: str = ""
    display_name: str = ""
    emails: list[str] = field(default_factory=list)
    website: str = ""
    company: str = ""

    def identity_name(self) -> str:
        return self.display_name or " ".join(
            p for p in (self.first_name, self.last_name) if p
        ).strip()


@dataclass
class LookupRow:
    query_name: str
    fingerprint: str
    status: str  # match | miss | ambiguous
    hit: PersonHit | None = None
    listing_url: str = ""
    emails: list[str] = field(default_factory=list)
    note: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {twenty_api_key()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _default_get(url: str, headers: dict[str, str], params: dict[str, str]) -> Any:
    with httpx.Client(timeout=20) as client:
        resp = client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in (
            "primaryEmail",
            "primaryLinkUrl",
            "url",
            "firstName",
            "lastName",
            "name",
        ):
            if value.get(key):
                return str(value.get(key) or "").strip()
    return str(value).strip()


def _emails_from(raw: Any) -> list[str]:
    out: list[str] = []
    if raw is None:
        return out
    if isinstance(raw, str) and "@" in raw:
        return [raw.strip()]
    if isinstance(raw, list):
        for item in raw:
            out.extend(_emails_from(item))
        return out
    if isinstance(raw, dict):
        primary = _text(raw.get("primaryEmail"))
        if primary:
            out.append(primary)
        extra = raw.get("additionalEmails") or raw.get("additional") or []
        out.extend(_emails_from(extra))
        if raw.get("email"):
            out.append(_text(raw.get("email")))
    return _dedupe_emails(out)[:8]


def _dedupe_emails(emails: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for email in emails:
        low = email.strip().lower()
        if not low or "@" not in low or low in seen:
            continue
        seen.add(low)
        out.append(email.strip())
    return out


def work_emails(emails: list[str]) -> list[str]:
    cleaned = _dedupe_emails(emails)
    work = [
        e
        for e in cleaned
        if e.rsplit("@", 1)[-1].lower() not in _PERSONAL
    ]
    return work or cleaned


def _website_from(row: dict[str, Any]) -> str:
    for key in (
        "homepage",
        "facultyPage",
        "website",
        "websiteUrl",
        "url",
        "linkedinLink",
        "xLink",
        "websiteLink",
    ):
        text = _text(row.get(key))
        if text.lower().startswith("http"):
            return text
    company = row.get("company")
    if isinstance(company, dict):
        domain = _text(
            company.get("domainName")
            or (company.get("domainName") or {})
        )
        if isinstance(company.get("domainName"), dict):
            domain = _text(company["domainName"].get("primaryLinkUrl")) or _text(
                company["domainName"].get("url")
            )
        if domain and not domain.lower().startswith("http"):
            domain = f"https://{domain}"
        listing = classify_listing_url(domain)
        if listing:
            return listing
    return ""


def parse_person(row: dict[str, Any]) -> PersonHit | None:
    if not isinstance(row, dict):
        return None
    name = row.get("name") if isinstance(row.get("name"), dict) else {}
    first = _text(name.get("firstName") if name else row.get("firstName"))
    last = _text(name.get("lastName") if name else row.get("lastName"))
    display = _text(row.get("displayName")) or " ".join(p for p in (first, last) if p)
    pid = str(row.get("id") or "").strip()
    if not pid and not last:
        return None
    emails = _dedupe_emails(_emails_from(row.get("emails")) + _emails_from(row.get("email")))
    company = ""
    raw_co = row.get("company")
    if isinstance(raw_co, dict):
        company = _text(raw_co.get("name"))
    return PersonHit(
        twenty_id=pid,
        first_name=first,
        last_name=last,
        display_name=display,
        emails=emails,
        website=_website_from(row),
        company=company,
    )


def _people_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    people = data.get("people")
    if isinstance(people, list):
        return [p for p in people if isinstance(p, dict)]
    if isinstance(people, dict) and isinstance(people.get("edges"), list):
        rows = []
        for edge in people["edges"]:
            node = edge.get("node") if isinstance(edge, dict) else None
            if isinstance(node, dict):
                rows.append(node)
        return rows
    return []


def search_people(
    cfg: Config,
    *,
    last_name: str,
    first_name: str = "",
    getter: Getter | None = None,
) -> list[PersonHit]:
    last = (last_name or "").strip()
    if not last:
        return []
    base = twenty_base_url(cfg)
    url = urljoin(base + "/", "rest/people")
    filt = 'name.lastName[ilike]:"%s"' % last.replace('"', "")
    get = getter or _default_get
    payload = get(url, _headers(), {"filter": filt, "limit": "20"})
    hits = [p for p in (parse_person(row) for row in _people_list(payload)) if p]
    first = (first_name or "").strip()
    if first:
        tight = [h for h in hits if names_match(h, last, first)]
        if tight:
            return tight
    return hits


def names_match(hit: PersonHit, last: str, first: str = "") -> bool:
    hit_last = re.sub(r"[^a-z0-9]+", "", (hit.last_name or "").lower())
    want_last = re.sub(r"[^a-z0-9]+", "", (last or "").lower())
    if not hit_last or hit_last != want_last:
        return False
    want_first = re.sub(r"[^a-z0-9]+", "", (first or "").lower())
    if not want_first:
        return True
    hit_first = re.sub(r"[^a-z0-9]+", "", (hit.first_name or "").lower())
    if not hit_first:
        return False
    if hit_first == want_first:
        return True
    if len(want_first) == 1:
        return hit_first.startswith(want_first)
    if len(hit_first) == 1:
        return want_first.startswith(hit_first)
    return hit_first.startswith(want_first) or want_first.startswith(hit_first)


def unique_match(hits: list[PersonHit], last: str, first: str = "") -> PersonHit | None:
    matched = [h for h in hits if names_match(h, last, first)]
    if len(matched) != 1:
        return None
    return matched[0]


def split_display_name(name: str) -> tuple[str, str]:
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[-1], parts[0]


def authors_from_items(items: list[Item]) -> list[PackAuthor]:
    """Unique creators across items (every surname, not only first author)."""
    seen: set[str] = set()
    out: list[PackAuthor] = []
    for item in items:
        surnames = [s for s in (item.creator_surnames or []) if s]
        if not surnames and item.first_author:
            surnames = [item.first_author.strip()]
        for i, raw in enumerate(surnames):
            display = raw.strip()
            if not display:
                continue
            # Prefer a fuller first-author display when Zotero stored "First Last".
            if (
                i == 0
                and item.first_author
                and " " in item.first_author.strip()
                and item.first_author.strip().casefold().endswith(display.casefold())
            ):
                display = item.first_author.strip()
            fp = name_fingerprint(display)
            if not fp or fp in seen:
                continue
            seen.add(fp)
            out.append(PackAuthor(name=display, fingerprint=fp))
    return out


def contact_path(cfg: Config, fingerprint: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", (fingerprint or "unknown").lower()).strip("-")
    return cfg.state_dir / "author-contacts" / f"{slug or 'unknown'}.json"


def write_contact(cfg: Config, author: PackAuthor, hit: PersonHit) -> Path:
    path = contact_path(cfg, author.fingerprint or hit.last_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    listing = classify_listing_url(hit.website)
    body = {
        "schema": CONTACT_SCHEMA,
        "fingerprint": author.fingerprint,
        "name": author.name or hit.identity_name(),
        "twenty_id": hit.twenty_id,
        "website": listing or hit.website,
        "emails": work_emails(hit.emails),
        "matched_at": _now(),
    }
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return path


def merge_listing_into_pack(
    pack: AuthorPack, author: PackAuthor, listing: str, *, source: str = "twenty"
) -> None:
    fp = author.fingerprint or name_fingerprint(author.name)
    for row in pack.authors:
        same = (row.fingerprint and row.fingerprint == fp) or (
            row.name and author.name and row.name.casefold() == author.name.casefold()
        )
        if same:
            if not row.listing_url:
                row.listing_url = listing
                row.base_host = host_of(listing)
                row.source = source
            return
    pack.authors.append(
        PackAuthor(
            name=author.name,
            fingerprint=fp,
            listing_url=listing,
            base_host=host_of(listing),
            source=source,
        )
    )


def lookup_authors(
    cfg: Config,
    authors: list[PackAuthor],
    *,
    getter: Getter | None = None,
    collection: str = "",
    apply: bool = False,
) -> list[LookupRow]:
    rows: list[LookupRow] = []
    pack: AuthorPack | None = None
    wrote_listing = False
    slug = pack_slug(collection)
    if apply:
        dest = pack_path(cfg, slug, promoted=False)
        pack = load_pack_file(dest) or AuthorPack(
            name=slug, collection=collection, status="proposed"
        )
    for author in authors:
        last, first = split_display_name(author.name)
        if not last and author.fingerprint:
            last = author.fingerprint.split("|", 1)[0]
        try:
            hits = search_people(cfg, last_name=last, first_name=first, getter=getter)
        except httpx.HTTPError as exc:
            rows.append(
                LookupRow(
                    query_name=author.name or last,
                    fingerprint=author.fingerprint,
                    status="miss",
                    note=f"http error: {exc}",
                )
            )
            continue
        hit = unique_match(hits, last, first)
        if hit is None:
            status = "ambiguous" if len(hits) > 1 else "miss"
            rows.append(
                LookupRow(
                    query_name=author.name or last,
                    fingerprint=author.fingerprint,
                    status=status,
                    note=f"{len(hits)} people" if hits else "no people",
                )
            )
            continue
        listing = classify_listing_url(hit.website)
        emails = work_emails(hit.emails)
        row = LookupRow(
            query_name=author.name or last,
            fingerprint=author.fingerprint,
            status="match",
            hit=hit,
            listing_url=listing,
            emails=emails,
        )
        rows.append(row)
        if apply:
            write_contact(cfg, author, hit)
            if listing and pack is not None:
                merge_listing_into_pack(pack, author, listing)
                wrote_listing = True
    if apply and pack is not None and wrote_listing:
        write_pack(pack_path(cfg, slug, promoted=False), pack)
    return rows
