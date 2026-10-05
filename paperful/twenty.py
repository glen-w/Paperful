"""Twenty CRM author lookup and sync. Opt-in; never sends mail.

``lookup`` does not write the CRM. ``sync --apply`` and ``--twenty-writeback`` do.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

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
    keywords: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

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
        keywords=_text(row.get("keywords")),
        raw=row,
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


def _retry_delay(headers: Any, attempt: int, base: float) -> float:
    raw = ""
    if headers is not None:
        try:
            raw = str(headers.get("Retry-After") or headers.get("retry-after") or "")
        except AttributeError:
            raw = ""
    try:
        parsed = float(raw)
        if parsed >= 0:
            return min(parsed, 60.0)
    except (TypeError, ValueError):
        pass
    return min(base * (2**attempt), 30.0)


def _default_send(
    method: str,
    url: str,
    headers: dict[str, str],
    params: dict[str, str],
    body: dict[str, Any] | None,
) -> Any:
    with httpx.Client(timeout=30) as client:
        resp = client.request(
            method, url, headers=headers, params=params or None, json=body
        )
    if resp.status_code == 429 or resp.status_code >= 500:
        raise httpx.HTTPStatusError(
            f"HTTP {resp.status_code}", request=resp.request, response=resp
        )
    resp.raise_for_status()
    if not resp.content:
        return {}
    try:
        return resp.json()
    except json.JSONDecodeError:
        return {}


Sender = Callable[[str, str, dict[str, str], dict[str, str], dict[str, Any] | None], Any]


def twenty_request(
    cfg: Config,
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    sender: Sender | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> Any:
    """GET/POST/PATCH Twenty REST. Retries 429 and 5xx using Retry-After."""
    url = urljoin(twenty_base_url(cfg) + "/", path.lstrip("/"))
    headers = _headers()
    retries = max(0, int(getattr(cfg, "twenty_retry_max", 8) or 0))
    base = float(getattr(cfg, "twenty_retry_base_seconds", 1.0) or 1.0)
    sleep = sleeper or time.sleep
    call = sender or _default_send
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return call(method, url, headers, params or {}, body)
        except httpx.HTTPStatusError as exc:
            last = exc
            code = exc.response.status_code if exc.response is not None else 0
            if code != 429 and code < 500:
                raise
            if attempt >= retries:
                raise
            headers_map = exc.response.headers if exc.response is not None else {}
            sleep(_retry_delay(headers_map, attempt, base))
        except httpx.HTTPError as exc:
            last = exc
            if attempt >= retries:
                raise
            sleep(min(base * (2**attempt), 30.0))
    if last is not None:
        raise last
    return {}


def _record(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict):
        if data.get("id"):
            return data
        for value in data.values():
            if isinstance(value, dict) and value.get("id"):
                return value
        return data
    if payload.get("id"):
        return payload
    return {}


def _record_id(payload: Any) -> str:
    return str(_record(payload).get("id") or "").strip()


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
    try:
        if getter is None:
            payload = twenty_request(
                cfg, "GET", "rest/people", params={"filter": filt, "limit": "20"}
            )
        else:
            payload = get(url, _headers(), {"filter": filt, "limit": "20"})
    except httpx.HTTPError:
        raise
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
    return parts[-1], " ".join(parts[:-1])


def authors_from_items(items: list[Item]) -> list[PackAuthor]:
    """Unique person creators. Prefer given name + surname over surname-only."""
    seen: set[str] = set()
    out: list[PackAuthor] = []
    for item in items:
        people = list(getattr(item, "creator_people", None) or [])
        if people:
            for person in people:
                display = (person.display or "").strip()
                if not display:
                    display = " ".join(
                        part for part in (person.first, person.last) if part
                    ).strip()
                fp = name_fingerprint(display)
                if not fp or fp in seen:
                    continue
                seen.add(fp)
                out.append(PackAuthor(name=display, fingerprint=fp))
            continue
        surnames = [s for s in (item.creator_surnames or []) if s]
        if not surnames and item.first_author:
            surnames = [item.first_author.strip()]
        for i, raw in enumerate(surnames):
            display = raw.strip()
            if not display:
                continue
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


def load_contact(cfg: Config, fingerprint: str) -> dict[str, Any] | None:
    path = contact_path(cfg, fingerprint)
    if not path.is_file():
        return None
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


def write_contact(
    cfg: Config,
    author: PackAuthor,
    hit: PersonHit,
    *,
    note_id: str = "",
    collections: list[str] | None = None,
) -> Path:
    path = contact_path(cfg, author.fingerprint or hit.last_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    prior = load_contact(cfg, author.fingerprint or hit.last_name) or {}
    listing = classify_listing_url(hit.website)
    kept_note = note_id or str(prior.get("note_id") or "")
    kept_collections = list(collections if collections is not None else prior.get("collections") or [])
    body = {
        "schema": CONTACT_SCHEMA,
        "fingerprint": author.fingerprint,
        "name": author.name or hit.identity_name(),
        "twenty_id": hit.twenty_id,
        "website": listing or hit.website,
        "emails": work_emails(hit.emails),
        "matched_at": _now(),
    }
    if kept_note:
        body["note_id"] = kept_note
    if kept_collections:
        body["collections"] = kept_collections
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


@dataclass
class SyncAction:
    name: str
    fingerprint: str
    action: str  # enrich | create | ambiguous | miss-http | skip-corporate | unchanged
    note: str = ""
    twenty_id: str = ""
    hit: PersonHit | None = None
    emails: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    author: PackAuthor | None = None
    note_id: str = ""


def _provenance_tokens(cfg: Config, collection: str) -> list[str]:
    keyword = (getattr(cfg, "twenty_provenance_keyword", "") or "paperful").strip() or "paperful"
    slug = pack_slug(collection) if collection else ""
    out = [keyword]
    if slug and slug.casefold() != keyword.casefold():
        out.append(slug)
    return out


def merge_keywords(existing: str, extra: list[str]) -> str:
    tokens = [part.strip() for part in re.split(r"[,;]", existing or "") if part.strip()]
    seen = {part.casefold() for part in tokens}
    for part in extra:
        text = (part or "").strip()
        if text and text.casefold() not in seen:
            tokens.append(text)
            seen.add(text.casefold())
    return ", ".join(tokens)


def _link_bucket(url: str) -> str:
    host = host_of(url)
    if host == "researchgate.net" or host.endswith(".researchgate.net"):
        return "researchGate"
    if "scholar.google" in host:
        return "googleScholar"
    path = (urlparse(url).path or "").lower()
    if any(tok in path for tok in ("/faculty", "/people", "/staff", "/~", "/profile")):
        return "facultyPage"
    return "homepage"


def _urls_on_link(raw: Any) -> list[str]:
    if isinstance(raw, str) and raw.lower().startswith("http"):
        return [raw.strip()]
    if not isinstance(raw, dict):
        return []
    urls: list[str] = []
    primary = _text(raw.get("primaryLinkUrl") or raw.get("url"))
    if primary.lower().startswith("http"):
        urls.append(primary)
    for row in raw.get("secondaryLinks") or []:
        if isinstance(row, dict):
            link = _text(row.get("url"))
        else:
            link = _text(row)
        if link.lower().startswith("http"):
            urls.append(link)
    return urls


def _link_patch(existing: Any, new_url: str) -> dict[str, Any] | None:
    urls = _urls_on_link(existing)
    known = {item.rstrip("/").lower() for item in urls}
    if new_url.rstrip("/").lower() in known:
        return None
    raw = existing if isinstance(existing, dict) else {}
    if not urls:
        return {"primaryLinkUrl": new_url, "primaryLinkLabel": ""}
    secondary = []
    for row in raw.get("secondaryLinks") or []:
        if isinstance(row, dict) and row.get("url"):
            secondary.append({"url": str(row["url"]), "label": str(row.get("label") or "")})
        elif isinstance(row, str) and row.strip():
            secondary.append({"url": row.strip(), "label": ""})
    secondary.append({"url": new_url, "label": ""})
    return {
        "primaryLinkUrl": urls[0],
        "primaryLinkLabel": str(raw.get("primaryLinkLabel") or ""),
        "secondaryLinks": secondary,
    }


def _email_patch(hit: PersonHit, emails: list[str]) -> dict[str, Any] | None:
    raw = hit.raw.get("emails") if isinstance(hit.raw.get("emails"), dict) else {}
    primary = _text(raw.get("primaryEmail")) if raw else ""
    if not primary and hit.emails:
        primary = hit.emails[0]
    additional = [str(item) for item in (raw.get("additionalEmails") or []) if item]
    known = {item.strip().lower() for item in [primary, *additional, *hit.emails] if item}
    fresh = [item for item in work_emails(emails) if item.strip().lower() not in known]
    if not fresh:
        return None
    if not primary:
        return {"primaryEmail": fresh[0], "additionalEmails": additional + fresh[1:]}
    return {"primaryEmail": primary, "additionalEmails": additional + fresh}


def merge_person_patch(
    hit: PersonHit, *, emails: list[str], urls: list[str], keywords: list[str]
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    email_body = _email_patch(hit, emails)
    if email_body:
        patch["emails"] = email_body
    by_field: dict[str, list[str]] = {}
    for url in urls:
        text = (url or "").strip()
        if not text.lower().startswith("http"):
            continue
        by_field.setdefault(_link_bucket(text), []).append(text)
    for field_name, links in by_field.items():
        current = hit.raw.get(field_name)
        built = current
        changed = False
        for link in links:
            nxt = _link_patch(built, link)
            if nxt is None:
                continue
            built = nxt
            changed = True
        if changed and isinstance(built, dict):
            patch[field_name] = built
    merged = merge_keywords(hit.keywords or _text(hit.raw.get("keywords")), keywords)
    if merged and merged != (hit.keywords or _text(hit.raw.get("keywords"))):
        patch["keywords"] = merged
    return patch


def owned_emails(items: list[Item], author: PackAuthor) -> list[str]:
    """Emails that belong to this creator. A paper's single address stays on the first author."""
    from .reachout import extract_emails_from_text

    found: list[str] = []
    fp = author.fingerprint
    for item in items:
        chunks = [item.extra or "", item.abstract or ""]
        url = (item.url or "").strip()
        if url.lower().startswith("mailto:"):
            chunks.append(url[7:].split("?", 1)[0])
        emails = extract_emails_from_text("\n".join(chunks))
        if not emails:
            continue
        people = list(getattr(item, "creator_people", None) or [])
        if not people:
            surnames = [s for s in (item.creator_surnames or []) if s]
            if len(surnames) == 1 and len(emails) == 1 and name_fingerprint(surnames[0]) == fp:
                found.extend(emails)
            continue
        for index, person in enumerate(people):
            display = (person.display or "").strip() or " ".join(
                part for part in (person.first, person.last) if part
            )
            if name_fingerprint(display) != fp:
                continue
            first = (person.first or "").split()[0].lower()
            last = (person.last or "").lower()
            matched: list[str] = []
            for email in emails:
                local = email.split("@", 1)[0].lower()
                if first and len(first) > 1 and first in local:
                    matched.append(email)
                elif last and len(last) > 1 and last in local:
                    matched.append(email)
            if not matched and index == 0 and len(emails) == 1:
                matched = list(emails)
            found.extend(matched)
    return work_emails(found)


def _progress_path(cfg: Config, collection: str) -> Path:
    return cfg.state_dir / "twenty-sync" / f"{pack_slug(collection) or 'library'}.jsonl"


def _done_fingerprints(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    done: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            body = json.loads(line)
        except json.JSONDecodeError:
            continue
        if body.get("action") in {"create", "enrich", "unchanged"} and body.get("fingerprint"):
            done.add(str(body["fingerprint"]))
    return done


def _append_progress(path: Path, action: SyncAction) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "fingerprint": action.fingerprint,
        "name": action.name,
        "action": action.action,
        "twenty_id": action.twenty_id,
        "at": _now(),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def get_person(
    cfg: Config,
    twenty_id: str,
    *,
    sender: Sender | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> PersonHit | None:
    pid = (twenty_id or "").strip()
    if not pid:
        return None
    try:
        payload = twenty_request(
            cfg, "GET", f"rest/people/{pid}", sender=sender, sleeper=sleeper
        )
    except httpx.HTTPError:
        return None
    row = _record(payload)
    hit = parse_person(row)
    if hit is None and isinstance(payload, dict):
        hit = parse_person(payload)
    if hit is not None and not hit.twenty_id:
        hit.twenty_id = pid
    return hit


def _search(
    cfg: Config,
    author: PackAuthor,
    *,
    sender: Sender | None = None,
    sleeper: Callable[[float], None] | None = None,
    getter: Getter | None = None,
) -> list[PersonHit]:
    last, first = split_display_name(author.name)
    if not last and author.fingerprint:
        last = author.fingerprint.split("|", 1)[0]
    if getter is not None:
        return search_people(cfg, last_name=last, first_name=first, getter=getter)
    base = twenty_base_url(cfg)
    if not base:
        return []
    filt = 'name.lastName[ilike]:"%s"' % last.replace('"', "")
    payload = twenty_request(
        cfg,
        "GET",
        "rest/people",
        params={"filter": filt, "limit": "20"},
        sender=sender,
        sleeper=sleeper,
    )
    hits = [p for p in (parse_person(row) for row in _people_list(payload)) if p]
    if first:
        tight = [h for h in hits if names_match(h, last, first)]
        if tight:
            return tight
    return hits


def corporate_skips(items: list[Item]) -> list[SyncAction]:
    seen: set[str] = set()
    rows: list[SyncAction] = []
    for item in items:
        for name in item.corporate_creators or []:
            text = name.strip()
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            rows.append(
                SyncAction(name=text, fingerprint="", action="skip-corporate", note="org")
            )
    return rows


def plan_sync(
    cfg: Config,
    items: list[Item],
    *,
    collection: str = "",
    limit: int = 0,
    sender: Sender | None = None,
    sleeper: Callable[[float], None] | None = None,
    getter: Getter | None = None,
) -> list[SyncAction]:
    """Read Twenty and decide create/enrich. Does not write the CRM."""
    authors = authors_from_items(items)
    if limit and limit > 0:
        authors = authors[:limit]
    done = _done_fingerprints(_progress_path(cfg, collection))
    tokens = _provenance_tokens(cfg, collection)
    rows = corporate_skips(items)
    for author in authors:
        if author.fingerprint in done:
            rows.append(
                SyncAction(
                    name=author.name,
                    fingerprint=author.fingerprint,
                    action="unchanged",
                    note="already synced",
                    author=author,
                )
            )
            continue
        emails = owned_emails(items, author)
        prior = load_contact(cfg, author.fingerprint) or {}
        cached_url = classify_listing_url(str(prior.get("website") or ""))
        urls = [cached_url] if cached_url else []
        try:
            hit: PersonHit | None = None
            if prior.get("twenty_id"):
                hit = get_person(
                    cfg, str(prior["twenty_id"]), sender=sender, sleeper=sleeper
                )
            if hit is None:
                hits = _search(
                    cfg, author, sender=sender, sleeper=sleeper, getter=getter
                )
                hit = unique_match(hits, *split_display_name(author.name))
                if hit is None and len(hits) > 1:
                    rows.append(
                        SyncAction(
                            name=author.name,
                            fingerprint=author.fingerprint,
                            action="ambiguous",
                            note=f"{len(hits)} people",
                            author=author,
                            emails=emails,
                        )
                    )
                    continue
                if hit is None and hits:
                    one = unique_match(hits, split_display_name(author.name)[0], split_display_name(author.name)[1])
                    hit = one
            if hit is None:
                rows.append(
                    SyncAction(
                        name=author.name,
                        fingerprint=author.fingerprint,
                        action="create",
                        author=author,
                        emails=emails,
                        urls=urls,
                    )
                )
                continue
            patch = merge_person_patch(hit, emails=emails, urls=urls, keywords=tokens)
            note_id = str(prior.get("note_id") or "")
            action_name = "enrich" if patch or not note_id else "unchanged"
            rows.append(
                SyncAction(
                    name=author.name,
                    fingerprint=author.fingerprint,
                    action=action_name,
                    twenty_id=hit.twenty_id,
                    hit=hit,
                    emails=emails,
                    urls=urls,
                    author=author,
                    note_id=note_id,
                    note="" if patch else "fields already set",
                )
            )
        except httpx.HTTPError as exc:
            rows.append(
                SyncAction(
                    name=author.name,
                    fingerprint=author.fingerprint,
                    action="miss-http",
                    note=f"http error: {exc}",
                    author=author,
                )
            )
    return rows


def _create_body(author: PackAuthor, emails: list[str], urls: list[str], keywords: str) -> dict[str, Any]:
    last, first = split_display_name(author.name)
    body: dict[str, Any] = {
        "name": {"firstName": first, "lastName": last},
        "position": "last",
        "keywords": keywords,
    }
    if emails:
        body["emails"] = {"primaryEmail": emails[0], "additionalEmails": emails[1:]}
    if urls:
        homepage: dict[str, Any] | None = None
        for url in urls:
            homepage = _link_patch(homepage, url) or homepage
        if homepage:
            body["homepage"] = homepage
    return body


def upsert_paperful_note(
    cfg: Config,
    *,
    person_id: str,
    note_id: str,
    collection: str,
    action: str,
    source: str,
    sender: Sender | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> str:
    title = (getattr(cfg, "twenty_sync_note_title", "") or "Paperful").strip() or "Paperful"
    line = f"- {_now()} · {action} · {collection or '-'} · {source}"
    if note_id:
        try:
            existing = twenty_request(
                cfg, "GET", f"rest/notes/{note_id}", sender=sender, sleeper=sleeper
            )
            rec = _record(existing)
            markdown = ""
            body_v2 = rec.get("bodyV2")
            if isinstance(body_v2, dict):
                markdown = str(body_v2.get("markdown") or "")
            markdown = (markdown + "\n" + line).strip() + "\n"
            twenty_request(
                cfg,
                "PATCH",
                f"rest/notes/{note_id}",
                body={"title": title, "bodyV2": {"markdown": markdown}},
                sender=sender,
                sleeper=sleeper,
            )
            return note_id
        except httpx.HTTPError:
            note_id = ""
    created = twenty_request(
        cfg,
        "POST",
        "rest/notes",
        body={
            "title": title,
            "position": "last",
            "bodyV2": {"markdown": f"Paperful\n\n{line}\n"},
        },
        sender=sender,
        sleeper=sleeper,
    )
    new_id = _record_id(created)
    if new_id and person_id:
        try:
            twenty_request(
                cfg,
                "POST",
                "rest/noteTargets",
                body={"noteId": new_id, "personId": person_id},
                sender=sender,
                sleeper=sleeper,
            )
        except httpx.HTTPError:
            pass
    return new_id


def apply_sync_actions(
    cfg: Config,
    actions: list[SyncAction],
    *,
    collection: str = "",
    sender: Sender | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> list[SyncAction]:
    """Create or enrich planned rows. Ambiguous and HTTP misses are left alone."""
    tokens = _provenance_tokens(cfg, collection)
    keyword_text = merge_keywords("", tokens)
    progress = _progress_path(cfg, collection)
    for action in actions:
        if action.action not in {"create", "enrich"} or action.author is None:
            continue
        try:
            if action.action == "create":
                payload = twenty_request(
                    cfg,
                    "POST",
                    "rest/people",
                    body=_create_body(action.author, action.emails, action.urls, keyword_text),
                    sender=sender,
                    sleeper=sleeper,
                )
                hit = parse_person(_record(payload)) or PersonHit(
                    twenty_id=_record_id(payload),
                    display_name=action.name,
                    emails=list(action.emails),
                    website=(action.urls[0] if action.urls else ""),
                    keywords=keyword_text,
                )
                if not hit.twenty_id:
                    hit.twenty_id = _record_id(payload)
                action.hit = hit
                action.twenty_id = hit.twenty_id
            else:
                hit = action.hit or PersonHit(twenty_id=action.twenty_id)
                patch = merge_person_patch(
                    hit, emails=action.emails, urls=action.urls, keywords=tokens
                )
                if patch and hit.twenty_id:
                    twenty_request(
                        cfg,
                        "PATCH",
                        f"rest/people/{hit.twenty_id}",
                        body=patch,
                        sender=sender,
                        sleeper=sleeper,
                    )
                    if "keywords" in patch:
                        hit.keywords = str(patch["keywords"])
                action.twenty_id = hit.twenty_id
            action.note_id = upsert_paperful_note(
                cfg,
                person_id=action.twenty_id,
                note_id=action.note_id,
                collection=collection,
                action=action.action,
                source="twenty-sync",
                sender=sender,
                sleeper=sleeper,
            )
            write_contact(
                cfg,
                action.author,
                action.hit or PersonHit(twenty_id=action.twenty_id, display_name=action.name),
                note_id=action.note_id,
                collections=[collection] if collection else None,
            )
            action.note = action.note or "wrote"
            _append_progress(progress, action)
        except httpx.HTTPError as exc:
            action.action = "miss-http"
            action.note = f"http error: {exc}"
    return actions


def cache_listing_url(cfg: Config, author: PackAuthor) -> str:
    body = load_contact(cfg, author.fingerprint)
    if not body:
        return ""
    return classify_listing_url(str(body.get("website") or ""))


def listing_budget_left(cfg: Config) -> int:
    if not hasattr(cfg, "_twenty_listing_left"):
        cfg._twenty_listing_left = int(getattr(cfg, "twenty_fetch_listing_max", 20) or 0)
    return int(getattr(cfg, "_twenty_listing_left", 0) or 0)


def author_site_ready(item: Item, cfg: Config) -> bool:
    """True when a late author_site try might have a listing (pack, cache, or capped CRM)."""
    from .snowball.authors import matching_author

    hit = matching_author(item, cfg)
    if hit is not None and (hit.listing_url or hit.base_host):
        return True
    for author in authors_from_items([item]):
        if cache_listing_url(cfg, author):
            return True
    if not cfg.twenty_enabled or not twenty_ready(cfg):
        return False
    if getattr(item, "has_pdf", False):
        return False
    if not authors_from_items([item]):
        return False
    return listing_budget_left(cfg) > 0


def resolve_listing(
    item: Item,
    cfg: Config,
    *,
    live: bool = False,
    sender: Sender | None = None,
    sleeper: Callable[[float], None] | None = None,
    getter: Getter | None = None,
) -> PackAuthor | None:
    """Promoted pack, then contact cache, then one capped unique-match People website."""
    from .snowball.authors import matching_author

    hit = matching_author(item, cfg)
    if hit is not None and (hit.listing_url or hit.base_host):
        return hit
    for author in authors_from_items([item]):
        url = cache_listing_url(cfg, author)
        if url:
            return PackAuthor(
                name=author.name,
                fingerprint=author.fingerprint,
                listing_url=url,
                base_host=host_of(url),
                source="twenty",
            )
    if not live or getattr(item, "has_pdf", False) or not twenty_ready(cfg):
        return None
    authors = authors_from_items([item])
    if not authors or listing_budget_left(cfg) <= 0:
        return None
    cfg._twenty_listing_left = listing_budget_left(cfg) - 1
    author = authors[0]
    try:
        prior = load_contact(cfg, author.fingerprint) or {}
        person = None
        if prior.get("twenty_id"):
            person = get_person(
                cfg, str(prior["twenty_id"]), sender=sender, sleeper=sleeper
            )
        if person is None:
            hits = _search(cfg, author, sender=sender, sleeper=sleeper, getter=getter)
            last, first = split_display_name(author.name)
            person = unique_match(hits, last, first)
        if person is None:
            return None
        url = classify_listing_url(person.website)
        if not url:
            return None
        write_contact(cfg, author, person)
        return PackAuthor(
            name=author.name,
            fingerprint=author.fingerprint,
            listing_url=url,
            base_host=host_of(url),
            source="twenty",
        )
    except httpx.HTTPError:
        return None


def writeback_author_listing(
    cfg: Config,
    author: PackAuthor,
    url: str,
    *,
    collection: str = "",
    source: str = "searxng",
    sender: Sender | None = None,
    sleeper: Callable[[float], None] | None = None,
    getter: Getter | None = None,
) -> str:
    """Append a personal/faculty URL onto a unique Person. Never creates one."""
    if not getattr(cfg, "twenty_writeback_listings", False):
        return "off"
    listing = classify_listing_url(url)
    if not listing or not twenty_ready(cfg):
        return "skipped"
    try:
        prior = load_contact(cfg, author.fingerprint) or {}
        person = None
        if prior.get("twenty_id"):
            person = get_person(
                cfg, str(prior["twenty_id"]), sender=sender, sleeper=sleeper
            )
        if person is None:
            hits = _search(cfg, author, sender=sender, sleeper=sleeper, getter=getter)
            last, first = split_display_name(author.name)
            if len(hits) > 1 and unique_match(hits, last, first) is None:
                return "ambiguous"
            person = unique_match(hits, last, first)
        if person is None:
            return "miss"
        tokens = _provenance_tokens(cfg, collection)
        patch = merge_person_patch(person, emails=[], urls=[listing], keywords=tokens)
        if patch and person.twenty_id:
            twenty_request(
                cfg,
                "PATCH",
                f"rest/people/{person.twenty_id}",
                body=patch,
                sender=sender,
                sleeper=sleeper,
            )
        note_id = upsert_paperful_note(
            cfg,
            person_id=person.twenty_id,
            note_id=str(prior.get("note_id") or ""),
            collection=collection,
            action="enriched",
            source=source,
            sender=sender,
            sleeper=sleeper,
        )
        person.website = person.website or listing
        write_contact(
            cfg,
            author,
            person,
            note_id=note_id,
            collections=[collection] if collection else None,
        )
        return "enrich"
    except httpx.HTTPError:
        return "miss-http"


def writeback_item_listing(
    cfg: Config,
    item: Item,
    url: str,
    *,
    source: str = "author_site",
    sender: Sender | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> str:
    authors = authors_from_items([item])
    if not authors:
        return "skipped"
    collection = (item.collection_paths or [""])[0]
    return writeback_author_listing(
        cfg,
        authors[0],
        url,
        collection=collection,
        source=source,
        sender=sender,
        sleeper=sleeper,
    )


def listing_for_author(
    cfg: Config,
    author: PackAuthor,
    *,
    live: bool = True,
    sender: Sender | None = None,
    sleeper: Callable[[float], None] | None = None,
    getter: Getter | None = None,
) -> str:
    """Contact-cache listing, else one capped unique People website. Does not create."""
    cached = cache_listing_url(cfg, author)
    if cached:
        return cached
    if not live or not twenty_ready(cfg) or listing_budget_left(cfg) <= 0:
        return ""
    cfg._twenty_listing_left = listing_budget_left(cfg) - 1
    try:
        hits = _search(cfg, author, sender=sender, sleeper=sleeper, getter=getter)
        last, first = split_display_name(author.name)
        if len(hits) > 1 and unique_match(hits, last, first) is None:
            return ""
        person = unique_match(hits, last, first)
        if person is None:
            return ""
        url = classify_listing_url(person.website)
        if url:
            write_contact(cfg, author, person)
        return url
    except httpx.HTTPError:
        return ""


def author_site_lane_wanted(cfg: Config) -> bool:
    """Promoted pack, cached listing, or a ready Twenty workspace."""
    from .snowball.authors import classify_listing_url as _classify
    from .snowball.authors import load_promoted_packs

    for pack in load_promoted_packs(cfg):
        if any(row.listing_url or row.base_host for row in pack.authors):
            return True
    folder = cfg.state_dir / "author-contacts"
    if folder.is_dir():
        for path in folder.glob("*.json"):
            try:
                body = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(body, dict) and _classify(str(body.get("website") or "")):
                return True
    return bool(cfg.twenty_enabled and twenty_ready(cfg))
