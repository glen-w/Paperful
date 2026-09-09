"""Institutional EZProxy: fetch publisher PDFs through a campus proxy session.

Auth is cookie-based (log in via browser + export cookies). We never store Sciences Po
passwords. Configure `ezproxy_base` (e.g. https://scpo.idm.oclc.org/login?url=) and
`ezproxy_cookies` pointing at a Netscape cookies.txt that includes the proxy session.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from ..zot import Item
from .base import Candidate, Context, Outcome

NAME = "ezproxy"

_LOGIN_HINTS = (
    "central authentication service",
    "entrez votre identifiant",
    "shibboleth",
    "wayf",
    "select your institution",
)
_PDF_HREF_RE = re.compile(r"pdfft|/pdf(?:\?|$)|citation_pdf_url|download=true", re.I)


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
    if "idm.oclc.org" in url and "/login" in url and ("password" in body or "identifiant" in body):
        return True
    return False


def find(item: Item, ctx: Context) -> Candidate:
    cfg = ctx.config
    if not cfg.ezproxy_base:
        return Candidate.miss(NAME, Outcome.SKIPPED, "ezproxy_base not set")
    if not cfg.ezproxy_cookies or not cfg.ezproxy_cookies.is_file():
        return Candidate.miss(NAME, Outcome.SKIPPED, "no ezproxy cookie file - run: scihub-dl ezproxy")
    if not list(ctx.client.cookies.jar):
        return Candidate.miss(NAME, Outcome.SKIPPED, "ezproxy cookies not loaded into client")

    target = _target_url(item)
    if not target:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no DOI or publisher URL")

    url = proxify(target, cfg.ezproxy_base)
    try:
        resp = ctx.client.get(url, timeout=45)
    except httpx.HTTPError as exc:
        return Candidate.miss(NAME, Outcome.ERROR, f"proxy request failed ({type(exc).__name__})")

    if looks_like_login(resp):
        return Candidate.miss(NAME, Outcome.ERROR, "ezproxy session expired - re-login via scihub-dl ezproxy")
    if resp.status_code == 404:
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "publisher 404 via proxy")
    if resp.status_code >= 400:
        return Candidate.miss(NAME, Outcome.ERROR, f"HTTP {resp.status_code} via proxy")

    ctype = resp.headers.get("content-type", "").lower()
    if "application/pdf" in ctype or resp.content[:8].lstrip().startswith(b"%PDF"):
        return Candidate(url=str(resp.url), source=NAME, note="direct pdf via proxy", referer=str(resp.url))

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


def _target_url(item: Item) -> str | None:
    if item.doi:
        return f"https://doi.org/{item.doi}"
    url = (item.url or "").strip()
    if url.startswith("http") and "doi.org" not in url.lower() and "scholar.google" not in url.lower():
        return url
    return None


def extract_pdf_urls(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []

    def add(u: str | None) -> None:
        if not u:
            return
        abs_url = urljoin(base_url, u.strip())
        if abs_url not in found:
            found.append(abs_url)

    for meta in soup.find_all("meta", attrs={"name": re.compile(r"citation_pdf_url", re.I)}):
        add(meta.get("content"))
    for link in soup.find_all("link", attrs={"type": "application/pdf"}):
        add(link.get("href"))
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True).lower()
        if _PDF_HREF_RE.search(href) or text in {"pdf", "download pdf", "view pdf", "full text pdf"}:
            add(href)
    # ScienceDirect / Elsevier common pattern from PII in the landing URL
    m = re.search(r"/pii/([A-Z0-9]+)", base_url, re.I) or re.search(r"/pii/([A-Z0-9]+)", html, re.I)
    if m:
        pii = m.group(1)
        parsed = urlparse(base_url)
        add(f"{parsed.scheme}://{parsed.netloc}/science/article/pii/{pii}/pdfft?isDTMRedir=true&download=true")
    return found


def _ensure_proxied(pdf_url: str, ezproxy_base: str, landing_url: str) -> str:
    """If the landing page is on a rewritten proxy host, keep PDFs there; else wrap."""
    land_host = urlparse(landing_url).netloc
    pdf_host = urlparse(pdf_url).netloc
    if "idm.oclc.org" in land_host and "idm.oclc.org" not in pdf_host:
        # Host-rewritten session: mirror the landing host pattern when possible
        # www.sciencedirect.com -> www-sciencedirect-com.<proxy>
        proxy_root = land_host.split(".", 1)[-1] if land_host.count(".") >= 2 else land_host
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
