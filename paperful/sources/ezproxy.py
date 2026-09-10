"""Institutional EZProxy: fetch publisher PDFs through a campus proxy session.

Auth is cookie-based (log in via browser + export cookies). We never store Sciences Po
passwords. Configure `ezproxy_base` (e.g. https://scpo.idm.oclc.org/login?url=) and
`ezproxy_cookies` pointing at a Netscape cookies.txt that includes the proxy session.

Targets come from `routing.ezproxy_target`: a DOI (via doi.org) or a URL on a known
publisher host. YouTube, Zotero, FAO, and other non-publisher pages are skipped.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from ..routing import ezproxy_target
from ..zot import Item
from .base import Candidate, Context, Outcome
from .landing import extract_pdf_urls

NAME = "ezproxy"

_LOGIN_HINTS = (
    "central authentication service",
    "entrez votre identifiant",
    "shibboleth",
    "wayf",
    "select your institution",
)


def proxify(target: str, base: str) -> str:
    """Wrap a publisher/DOI URL in the EZProxy login redirector."""
    base = base.strip()
    if not base:
        return target
    if target.startswith(base) or "idm.oclc.org" in urlparse(target).netloc:
        return target
    if base.endswith("url="):
        return base + target
    if base.endswith("/"):
        return base + target
    return f"{base}{target}"


def looks_like_login(resp: httpx.Response) -> bool:
    url = str(resp.url).lower()
    if any(x in url for x in ("/cas/login", "federation.sciences-po.fr", "shibboleth")):
        return True
    body = resp.text[:4000].lower()
    if any(h in body for h in _LOGIN_HINTS):
        return True
    if (
        "idm.oclc.org" in url
        and "/login" in url
        and ("password" in body or "identifiant" in body)
    ):
        return True
    return False


def find(item: Item, ctx: Context) -> Candidate:
    cfg = ctx.config
    if not cfg.ezproxy_base:
        return Candidate.miss(NAME, Outcome.SKIPPED, "ezproxy_base not set")
    if not cfg.ezproxy_cookies or not cfg.ezproxy_cookies.is_file():
        return Candidate.miss(
            NAME, Outcome.SKIPPED, "no ezproxy cookie file - run: paperful ezproxy"
        )
    if not list(ctx.client.cookies.jar):
        return Candidate.miss(
            NAME, Outcome.SKIPPED, "ezproxy cookies not loaded into client"
        )

    target = ezproxy_target(item)
    if not target:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no DOI or proxied publisher URL")

    url = proxify(target, cfg.ezproxy_base)
    try:
        resp = ctx.client.get(url, timeout=45)
    except httpx.HTTPError as exc:
        return Candidate.miss(
            NAME, Outcome.ERROR, f"proxy request failed ({type(exc).__name__})"
        )

    if looks_like_login(resp):
        return Candidate.miss(
            NAME,
            Outcome.ERROR,
            "ezproxy session expired - re-login via paperful ezproxy",
        )
    if resp.status_code == 404:
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "publisher 404 via proxy")
    if resp.status_code >= 400:
        return Candidate.miss(NAME, Outcome.ERROR, f"HTTP {resp.status_code} via proxy")

    ctype = resp.headers.get("content-type", "").lower()
    if "application/pdf" in ctype or resp.content[:8].lstrip().startswith(b"%PDF"):
        return Candidate(
            url=str(resp.url),
            source=NAME,
            note="direct pdf via proxy",
            referer=str(resp.url),
        )

    pdfs = extract_pdf_urls(resp.text, str(resp.url))
    if not pdfs:
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "no PDF link on publisher page")
    # Keep PDF links on the proxy host when the landing page was rewritten.
    proxied = [_ensure_proxied(u, cfg.ezproxy_base, str(resp.url)) for u in pdfs]
    return Candidate(
        url=proxied[0],
        source=NAME,
        note=urlparse(str(resp.url)).netloc,
        referer=str(resp.url),
        alternates=proxied[1:5],
    )


def _ensure_proxied(pdf_url: str, ezproxy_base: str, landing_url: str) -> str:
    """If the landing page is on a rewritten proxy host, keep PDFs there; else wrap."""
    land_host = urlparse(landing_url).netloc
    pdf_host = urlparse(pdf_url).netloc
    if "idm.oclc.org" in land_host and "idm.oclc.org" not in pdf_host:
        # Host-rewritten session: mirror the landing host pattern when possible
        # www.sciencedirect.com -> www-sciencedirect-com.<proxy>
        proxy_root = (
            land_host.split(".", 1)[-1] if land_host.count(".") >= 2 else land_host
        )
        if pdf_host and proxy_root.endswith("idm.oclc.org"):
            rewritten = pdf_host.replace(".", "-") + "." + proxy_root
            p = urlparse(pdf_url)
            return p._replace(netloc=rewritten).geturl()
        return proxify(pdf_url, ezproxy_base)
    if "idm.oclc.org" in pdf_host:
        return pdf_url
    if "idm.oclc.org" in land_host:
        return proxify(pdf_url, ezproxy_base)
    return proxify(pdf_url, ezproxy_base)


def session_ok(ctx: Context) -> tuple[bool, str]:
    """Cheap check: hit the proxy login URL and see if we bounce to CAS."""
    if not ctx.config.ezproxy_base:
        return False, "ezproxy_base not set"
    if not ctx.config.ezproxy_cookies or not ctx.config.ezproxy_cookies.is_file():
        return False, f"cookie file missing ({ctx.config.ezproxy_cookies})"
    probe = proxify("https://doi.org/10.1038/nature", ctx.config.ezproxy_base)
    try:
        resp = ctx.client.get(probe, timeout=30)
    except httpx.HTTPError as exc:
        return False, f"request failed: {type(exc).__name__}"
    if looks_like_login(resp):
        return False, "session expired or not logged in (CAS/login page)"
    return True, f"ok ({resp.status_code} → {urlparse(str(resp.url)).netloc})"
