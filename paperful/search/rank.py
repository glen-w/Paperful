"""Build a SearXNG query and rank/filter web hits for grey PDFs."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from ..greyid import registrable_host
from ..playbooks import (
    GreyPlaybook,
    apply_rewrite,
    host_matches,
    looks_like_pdf_url,
    rewrite_playbook_name,
)
from ..snowball.authors import host_of, is_blocked_host

_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


def parse_hosts(raw: str | list[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = [p.strip().lower() for p in raw.replace(";", ",").split(",")]
    else:
        parts = [str(p).strip().lower() for p in raw]
    out: list[str] = []
    for part in parts:
        host = part.removeprefix("www.")
        if host and host not in out:
            out.append(host)
    return out


def fanout_queries(terms: list[str], *, filetype: str = "pdf", hosts: list[str] | None = None) -> list[str]:
    """Primary query plus recall variants (quoted name, no site: filter)."""
    allow = list(hosts or [])
    primary = build_query(terms, filetype=filetype, hosts=allow or None)
    out: list[str] = []
    if primary:
        out.append(primary)
    bits = [str(t).strip() for t in terms if str(t).strip()]
    names = [b for b in bits if b[:1].isupper() and b.lower() not in {"or", "and"}]
    if len(names) >= 2:
        quoted = build_query([f'"{names[0]} {names[1]}"'], filetype=filetype, hosts=None)
        if quoted and quoted not in out:
            out.append(quoted)
    if allow:
        wide = build_query(terms, filetype=filetype, hosts=None)
        if wide and wide not in out:
            out.append(wide)
    none = (filetype or "pdf").strip().lower()
    if none in {"pdf", "true", "on", "1"}:
        landings = build_query(terms, filetype="none", hosts=None)
        if landings and landings not in out:
            out.append(landings)
    return out


def build_query(terms: list[str], *, filetype: str = "pdf", hosts: list[str] | None = None) -> str:
    bits = [str(t).strip() for t in terms if str(t).strip()]
    q = " ".join(bits).strip()
    kind = (filetype or "pdf").strip().lower()
    if kind in {"pdf", "true", "on", "1"}:
        if "filetype:" not in q.lower():
            q = f"{q} filetype:pdf".strip()
    if hosts:
        sites = " OR ".join(f"site:{h}" for h in hosts)
        q = f"{q} ({sites})".strip()
    return q


def year_from_text(*parts: str) -> int | None:
    for part in parts:
        match = _YEAR_RE.search(part or "")
        if match:
            year = int(match.group(1))
            if 1900 <= year <= 2100:
                return year
    return None


def doi_from_text(*parts: str) -> str:
    for part in parts:
        match = _DOI_RE.search(part or "")
        if match:
            return match.group(0).rstrip(").,;")
    return ""


def _author_token(query: str) -> str:
    words = [w.strip("\"'") for w in (query or "").split() if w.strip("\"'")]
    skip = {"or", "and", "the", "of", "filetype:pdf", "site:"}
    names = [w for w in words if w.lower() not in skip and w[:1].isupper() and len(w) > 2]
    return names[-1] if names else ""


def score_hit(
    url: str,
    *,
    title: str = "",
    query: str = "",
    playbooks: list[GreyPlaybook] | None = None,
) -> tuple[int, str, str]:
    """Return (score, playbook name, rewritten url). Negative score means drop."""
    host = host_of(url)
    if is_blocked_host(host) or not registrable_host(url):
        return -1, "", url
    books = list(playbooks or [])
    rewritten = apply_rewrite(url, books) or url
    playbook = rewrite_playbook_name(url, books) or ""
    if not playbook:
        for pb in books:
            if host_matches(host, pb.hosts):
                playbook = pb.name
                break
    score = 0
    if looks_like_pdf_url(rewritten) or looks_like_pdf_url(url):
        score += 40
    if rewritten != url and looks_like_pdf_url(rewritten):
        score += 20
    if playbook:
        score += 25
    token = _author_token(query)
    if token and token.lower() in (url + " " + title).lower():
        score += 10
    path = (urlparse(url).path or "").lower()
    if "/publications/" in path or "/documents/" in path or "/resources/" in path:
        score += 5
    return score, playbook, rewritten


def host_allowed(url: str, allow: list[str]) -> bool:
    if not allow:
        return True
    host = (host_of(url) or "").lower()
    return any(host == a or host.endswith("." + a) or a in host for a in allow)
