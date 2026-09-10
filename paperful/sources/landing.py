"""Turn OA landing pages into PDF URLs (DSpace REST, OAI-PMH, HTML meta/links)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

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
_FAO_RE = re.compile(r"https?://www\.fao\.org/3/([a-z0-9]+)/", re.I)
_DC_PATH_RE = re.compile(r"^/([^/]+)/(\d+)/?$")
_UN_LANG = frozenset({"en", "fr", "es", "ar", "ru", "zh", "de"})
# A/CONF.232/2023/4, A/AC.292/2024/1, A/79/123, S/2024/55, Add.1 suffixes
_UN_SYMBOL_RE = re.compile(
    r"\b("
    r"(?:A|S|E|ST|UNEP|ISA|SPLOS|ISBA)"
    r"(?:/[A-Z]{2,12}(?:\.\d+)?)*"
    r"(?:/\d{1,4})+"
    r"(?:/(?:Add|Rev|Corr)\.\d+|/?INF(?:\.\d+)?(?:/\d+)?)*"
    r")\b",
    re.I,
)
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


def looks_like_pdf_url(url: str) -> bool:
    low = url.lower()
    path = low.split("?")[0]
    if path.endswith(".pdf"):
        return True
    if "pdfdirect" in low or "viewcontent.cgi" in low or "/pdfft" in low:
        return True
    if path.endswith("/pdf") or "/pdf/" in low:
        return True
    if "undocs.org" in low and "pdf" in low and "symbol=" in low:
        return True
    return False


def rewrite_known_pdf_url(url: str) -> str | None:
    """Map a few well-known landing URLs to a direct PDF without fetching."""
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
    # FAO document pages: https://www.fao.org/3/ca1234en/ca1234en.pdf
    m = _FAO_RE.match(url.split("?")[0])
    if m:
        code = m.group(1)
        return f"https://www.fao.org/3/{code}/{code}.pdf"
    undocs = _undocs_pdf_url(url)
    if undocs:
        return undocs
    return None


def extract_un_symbol(text: str) -> str | None:
    """First UN document symbol in free text (Extra, title, URL path)."""
    if not text:
        return None
    m = _UN_SYMBOL_RE.search(text.replace("%2F", "/").replace("%2f", "/"))
    return m.group(1).strip().replace(" ", "") if m else None


def undocs_pdf_url(symbol: str) -> str:
    return f"https://undocs.org/pdf?symbol={symbol}"


def _symbol_from_url(url: str) -> str | None:
    p = urlparse(url)
    host = (p.netloc or "").lower()
    qs = parse_qs(p.query, keep_blank_values=False)
    qs_l = {k.lower(): v for k, v in qs.items()}
    if "undocs.org" in host or host.endswith("docs.un.org") or "documents.un.org" in host:
        for key in ("symbol", "ds"):
            if key in qs_l and qs_l[key]:
                return unquote(qs_l[key][0]).strip()
        path = unquote(p.path).strip("/")
        parts = [x for x in path.split("/") if x]
        if parts and parts[0].lower() in _UN_LANG:
            parts = parts[1:]
        if parts and parts[0].lower() == "pdf":
            return None
        candidate = "/".join(parts)
        return extract_un_symbol(candidate) if candidate else None
    if "daccess-ods.un.org" in host:
        if "ds" in qs_l and qs_l["ds"]:
            return unquote(qs_l["ds"][0]).strip()
    return extract_un_symbol(unquote(p.path) + " " + p.query)


def _undocs_pdf_url(url: str) -> str | None:
    host = (urlparse(url).netloc or "").lower()
    if not any(
        h in host
        for h in ("undocs.org", "documents.un.org", "docs.un.org", "daccess-ods.un.org")
    ):
        return None
    if looks_like_pdf_url(url) and "undocs.org" in host and "symbol=" in url.lower():
        return url
    symbol = _symbol_from_url(url)
    if not symbol:
        return None
    return undocs_pdf_url(symbol)


def grey_target(item: object) -> str | None:
    """URL for the direct/grey lane: item URL (rewritten) or undocs URL from a symbol."""
    url = (getattr(item, "url", None) or "").strip()
    if url.lower().startswith(("http://", "https://")):
        rewritten = rewrite_known_pdf_url(url)
        return rewritten or url
    blob = f"{getattr(item, 'extra', '') or ''}\n{getattr(item, 'title', '') or ''}"
    symbol = extract_un_symbol(blob)
    if symbol:
        return undocs_pdf_url(symbol)
    return None


def extract_pdf_urls(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    primary: list[str] = []
    secondary: list[str] = []
    base_host = (urlparse(base_url).hostname or "").lower()

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
        if href_hit or text_hit:
            prefer = href_hit or looks_like_pdf_url(href)
            # Same-host links win over off-site trackers
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

    # IRENA / OECD / ISA / UN: prefer explicit .pdf hrefs already collected; add download path hints
    if "irena.org" in base_host:
        for a in soup.find_all("a", href=True):
            if ".pdf" in a["href"].lower():
                add(a["href"], prefer=True)
    if "oecd" in base_host:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/download/" in href.lower() or href.lower().endswith(".pdf"):
                add(href, prefer=True)
    if "isa.org.jm" in base_host or (
        base_host.endswith("un.org") and "undocs" not in base_host
    ):
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(" ", strip=True).lower()
            if (
                ".pdf" in href.lower()
                or "/bitstream/" in href.lower()
                or "download" in text
            ):
                add(href, prefer=True)

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
    rewritten = rewrite_known_pdf_url(url)
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
    return extract_pdf_urls(resp.text, str(resp.url))
