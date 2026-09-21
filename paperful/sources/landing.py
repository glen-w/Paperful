"""Turn OA landing pages into PDF URLs (DSpace REST, OAI-PMH, HTML meta/links).

Grey-lit host rewrites and scrape hints come from config playbooks
(`paperful.playbooks`); PMC/arXiv/HAL stay as domain-agnostic core rewrites.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from ..playbooks import (
    GreyPlaybook,
    apply_rewrite,
    apply_synthesize,
    rewrite_playbook_name,
    synthesize_playbook_name,
    default_playbooks,
    href_matches_scrape,
    looks_like_pdf_url,
    scrape_playbooks_for_host,
    url_is_direct_skip,
)
from ..resolve import title_similarity
from .base import Context, http_json

_PDF_HREF_RE = re.compile(
    r"pdfft|/pdf(?:\?|$)|citation_pdf_url|download=true|viewcontent\.cgi|\.pdf(?:\?|$)|/download/|/bitstream/",
    re.I,
)
_PDF_TEXT_RE = re.compile(
    r"\b(?:pdf|download\s+pdf|view\s+pdf|full\s+text(?:\s+pdf)?|full\s+report|"
    r"télécharger|telecharger|lire\s+le\s+pdf|download\s+(?:the\s+)?(?:report|publication|document))\b",
    re.I,
)
_HANDLE_RE = re.compile(
    r"(?:/handle/|hdl\.handle\.net/)(\d+(?:\.\d+)*/[^\s/?#]+)", re.I
)
_PMC_RE = re.compile(
    r"(?:ncbi\.nlm\.nih\.gov/pmc/articles|europepmc\.org/(?:articles|article/pmc))/(PMC\d+)",
    re.I,
)
_ARXIV_ABS_RE = re.compile(
    r"arxiv\.org/abs/([0-9]+\.[0-9]+|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})", re.I
)
_HAL_RE = re.compile(
    r"https?://(?:hal\.science|hal\.archives-ouvertes\.fr)/(hal-\d+(?:v\d+)?)", re.I
)
_DC_PATH_RE = re.compile(r"^/([^/]+)/(\d+)/?$")
_SKIP_OAI_HOSTS = ("doi.org", "hdl.handle.net", "scholar.google", "zotero.org")
_DEMOTE_HOST_FRAGMENTS = (
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "mailto:",
    "javascript:",
    "doubleclick",
    "googletagmanager",
)
_TITLE_MIN = 0.55
_MAX_LANDINGS = 3
_TIMEOUT = 20.0


def _books(
    playbooks: list[GreyPlaybook] | None,
) -> list[GreyPlaybook]:
    return playbooks if playbooks is not None else default_playbooks()


def rewrite_known_pdf_url(
    url: str, playbooks: list[GreyPlaybook] | None = None
) -> str | None:
    """Map well-known landing URLs to a direct PDF without fetching."""
    m = _PMC_RE.search(url)
    if m:
        pmcid = m.group(1)
        if "europepmc" in url.lower():
            return f"https://europepmc.org/articles/{pmcid}?pdf=render"
        return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
    m = _ARXIV_ABS_RE.search(url)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}"
    m = _HAL_RE.match(url.split("?")[0])
    if m:
        return f"https://hal.science/{m.group(1)}/document"
    return apply_rewrite(url, _books(playbooks))


def extract_un_symbol(
    text: str, playbooks: list[GreyPlaybook] | None = None
) -> str | None:
    """First synthesize match from free text (Extra, title, URL path) — pack-defined."""
    if not text:
        return None
    books = _books(playbooks)
    blob = text.replace("%2F", "/").replace("%2f", "/")
    for pb in books:
        if pb.kind != "synthesize":
            continue
        cre = pb.compiled_match()
        if not cre:
            continue
        m = cre.search(blob)
        if m:
            if m.lastindex and m.lastindex >= 1:
                return (m.group(1) or "").strip().replace(" ", "")
            return (m.group(0) or "").strip().replace(" ", "")
    return None


def undocs_pdf_url(symbol: str) -> str:
    return f"https://undocs.org/pdf?symbol={symbol}"


def grey_playbook_name(
    item: object, playbooks: list[GreyPlaybook] | None = None
) -> str:
    """Playbook that rewrote or synthesized this item, or ``""`` for a plain URL."""
    books = _books(playbooks)
    url = (getattr(item, "url", None) or "").strip()
    blob = f"{getattr(item, 'extra', '') or ''}\n{getattr(item, 'title', '') or ''}"
    if url.lower().startswith(("http://", "https://")):
        name = rewrite_playbook_name(url, books)
        if name:
            return name
        if url_is_direct_skip(url):
            return synthesize_playbook_name(blob, books) or ""
        return ""
    return synthesize_playbook_name(blob, books) or ""


def grey_target(
    item: object, playbooks: list[GreyPlaybook] | None = None
) -> str | None:
    """URL for the direct/grey lane: rewritten item URL or synthesize from Extra/title."""
    books = _books(playbooks)
    url = (getattr(item, "url", None) or "").strip()
    blob = f"{getattr(item, 'extra', '') or ''}\n{getattr(item, 'title', '') or ''}"
    if url.lower().startswith(("http://", "https://")):
        rewritten = rewrite_known_pdf_url(url, books)
        if rewritten:
            return rewritten
        # Skip-hosts (YouTube, Scholar, …): still allow Extra/title synthesize playbooks
        if url_is_direct_skip(url):
            synth = apply_synthesize(blob, books)
            if synth:
                return synth
        return url
    return apply_synthesize(blob, books)


def extract_pdf_urls(
    html: str,
    base_url: str,
    playbooks: list[GreyPlaybook] | None = None,
) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    primary: list[str] = []
    secondary: list[str] = []
    base_host = (urlparse(base_url).hostname or "").lower()
    scrape_pbs = scrape_playbooks_for_host(base_host, _books(playbooks))

    def add(u: str | None, *, prefer: bool = False) -> None:
        if not u:
            return
        abs_url = urljoin(base_url, u.strip())
        low = abs_url.lower()
        if any(x in low for x in _DEMOTE_HOST_FRAGMENTS):
            return
        if not abs_url.startswith(("http://", "https://")):
            return
        bucket = primary if prefer else secondary
        if abs_url not in primary and abs_url not in secondary:
            bucket.append(abs_url)

    for meta in soup.find_all("meta"):
        name = str(meta.get("name") or meta.get("property") or "").lower()
        content = meta.get("content")
        if name in {"citation_pdf_url", "bepress_citation_pdf_url"}:
            add(content, prefer=True)
        elif (
            name in {"og:url", "dc.identifier", "dc.identifier.url"}
            and content
            and looks_like_pdf_url(content)
        ):
            add(content, prefer=True)

    for link in soup.find_all("link", attrs={"type": "application/pdf"}):
        add(link.get("href"), prefer=True)

    for tag in soup.find_all(True):
        for attr in ("data-pdf-url", "data-download-url", "data-file-url"):
            if tag.has_attr(attr):
                add(tag.get(attr), prefer=True)

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True)
        aria = (a.get("aria-label") or a.get("title") or "").strip()
        combined = f"{text} {aria}".strip()
        href_hit = bool(_PDF_HREF_RE.search(href)) or looks_like_pdf_url(href)
        text_hit = bool(_PDF_TEXT_RE.search(combined))
        scrape_hit = bool(scrape_pbs) and href_matches_scrape(
            href, combined, scrape_pbs
        )
        if href_hit or text_hit or scrape_hit:
            prefer = href_hit or looks_like_pdf_url(href) or scrape_hit
            abs_u = urljoin(base_url, href.strip())
            host = (urlparse(abs_u).hostname or "").lower()
            if (
                base_host
                and host
                and (
                    host == base_host
                    or host.endswith("." + base_host)
                    or base_host.endswith("." + host)
                )
            ):
                prefer = True
            add(href, prefer=prefer)

    m = re.search(r"/pii/([A-Z0-9]+)", base_url, re.I) or re.search(
        r"/pii/([A-Z0-9]+)", html, re.I
    )
    if m:
        pii = m.group(1)
        parsed = urlparse(base_url)
        add(
            f"{parsed.scheme}://{parsed.netloc}/science/article/pii/{pii}/pdfft?isDTMRedir=true&download=true",
            prefer=True,
        )

    ordered = primary + [u for u in secondary if u not in primary]
    return ordered


def resolve_landings(
    ctx: Context, landings: list[str], title: str | None = None
) -> list[str]:
    """Follow OA landing URLs and return PDF URLs, skipping stale title mismatches."""
    pdfs: list[str] = []
    seen_land: list[str] = []
    for landing in landings:
        if not landing or landing in seen_land:
            continue
        seen_land.append(landing)
        for url in _resolve_one(ctx, landing, title):
            if url not in pdfs:
                pdfs.append(url)
        if pdfs or len(seen_land) >= _MAX_LANDINGS:
            break
    return pdfs


def _resolve_one(ctx: Context, url: str, title: str | None) -> list[str]:
    rewritten = rewrite_known_pdf_url(url, ctx.config.grey_playbooks)
    if rewritten:
        return [rewritten]
    if looks_like_pdf_url(url):
        return [url]
    pdfs = _dspace_pdfs(ctx, url, title)
    if pdfs:
        return pdfs
    pdfs = _digital_commons_pdfs(ctx, url, title)
    if pdfs:
        return pdfs
    return _html_pdfs(ctx, url)


def _title_ok(expected: str | None, got: str | None) -> bool:
    if not expected or not got:
        return True
    return title_similarity(expected, got) >= _TITLE_MIN


def _origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _abs(origin: str, href: str | None) -> str | None:
    if not href:
        return None
    return urljoin(origin + "/", href)


def _dspace_pdfs(ctx: Context, url: str, title: str | None) -> list[str]:
    handle = _HANDLE_RE.search(url)
    origin = _origin(url)
    handle_id = handle.group(1) if handle else None
    if "hdl.handle.net" in urlparse(url).netloc.lower():
        try:
            resp = ctx.client.get(url, timeout=_TIMEOUT)
        except httpx.HTTPError:
            return []
        origin = _origin(str(resp.url))
        found = _HANDLE_RE.search(str(resp.url))
        handle_id = found.group(1) if found else handle_id
    if not handle_id:
        return []
    item = http_json(
        ctx, f"{origin}/server/api/pid/find", params={"id": handle_id}, timeout=_TIMEOUT
    )
    if not item:
        return []
    if not _title_ok(title, item.get("name")):
        return []
    bundles_href = _abs(
        origin, ((item.get("_links") or {}).get("bundles") or {}).get("href")
    )
    if not bundles_href:
        return []
    bundles_data = http_json(ctx, bundles_href, timeout=_TIMEOUT) or {}
    bundles = ((bundles_data.get("_embedded") or {}).get("bundles")) or []
    original = [b for b in bundles if (b.get("name") or "").upper() == "ORIGINAL"]
    pdfs: list[str] = []
    for bundle in original or bundles:
        name = (bundle.get("name") or "").upper()
        if name in {"LICENSE", "THUMBNAIL"}:
            continue
        bits_href = _abs(
            origin, ((bundle.get("_links") or {}).get("bitstreams") or {}).get("href")
        )
        if not bits_href:
            continue
        bits_data = http_json(ctx, bits_href, timeout=_TIMEOUT) or {}
        for bit in ((bits_data.get("_embedded") or {}).get("bitstreams")) or []:
            bit_name = bit.get("name") or ""
            mime = (bit.get("mimeType") or "").lower()
            if mime != "application/pdf" and not bit_name.lower().endswith(".pdf"):
                continue
            content = _abs(
                origin, ((bit.get("_links") or {}).get("content") or {}).get("href")
            )
            if content and content not in pdfs:
                pdfs.append(content)
    return pdfs


def _digital_commons_pdfs(ctx: Context, url: str, title: str | None) -> list[str]:
    p = urlparse(url)
    if any(h in p.netloc.lower() for h in _SKIP_OAI_HOSTS):
        return []
    if "/handle/" in p.path:
        return []
    m = _DC_PATH_RE.match(p.path)
    if not m:
        return []
    context, rec_id = m.group(1), m.group(2)
    oai_id = f"oai:{p.netloc}:{context}-{rec_id}"
    try:
        resp = ctx.client.get(
            f"{p.scheme}://{p.netloc}/do/oai/",
            params={
                "verb": "GetRecord",
                "metadataPrefix": "oai_dc",
                "identifier": oai_id,
            },
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError:
        return []
    if resp.status_code >= 400:
        return []
    return _oai_pdfs(resp.text, title)


def _oai_pdfs(xml_text: str, title: str | None) -> list[str]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    titles: list[str] = []
    idents: list[str] = []
    for el in root.iter():
        name = el.tag.rsplit("}", 1)[-1]
        if name == "error":
            return []
        text = (el.text or "").strip()
        if not text:
            continue
        if name == "title":
            titles.append(text)
        elif name == "identifier":
            idents.append(text)
    if titles and not _title_ok(title, titles[0]):
        return []
    return [u for u in idents if looks_like_pdf_url(u)]


def _html_pdfs(ctx: Context, url: str) -> list[str]:
    try:
        resp = ctx.client.get(url, timeout=_TIMEOUT)
    except httpx.HTTPError:
        return []
    if resp.status_code >= 400:
        return []
    ctype = resp.headers.get("content-type", "").lower()
    if "application/pdf" in ctype or resp.content[:8].lstrip().startswith(b"%PDF"):
        return [str(resp.url)]
    if "html" not in ctype and "xml" not in ctype:
        return []
    return extract_pdf_urls(resp.text, str(resp.url), ctx.config.grey_playbooks)
