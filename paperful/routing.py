"""Per-item source lanes and block detection for circuit breakers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from .config import Config
from .resolve import normalize_doi
from .zot import Item

if TYPE_CHECKING:
    from .sources.base import Outcome

_ARXIV_TYPES = frozenset(
    {"preprint", "journalArticle", "conferencePaper", "report", "manuscript"}
)
_DIRECT_SKIP_HOSTS = (
    "doi.org",
    "scholar.google",
    "zotero.org",
    "twitter.com",
    "x.com",
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "facebook.com",
    "consensus.app",
    "semanticscholar.org",
    "researchgate.net",
)
_BIORXIV_DOI = re.compile(r"^10\.1101/", re.IGNORECASE)
_BIORXIV_URL = re.compile(
    r"(?:bio|med)rxiv\.org/content/(?:[^/\s]+/)*(10\.1101/[0-9./]+?)(?:v\d+)?(?:[./?]|$)",
    re.IGNORECASE,
)
_BLOCK_NOTE_HINTS = ("blocked", "captcha", "429", "rate limit", "sorry")


def is_block_failure(outcome: Outcome, note: str = "") -> bool:
    # Compare by value so this module never imports sources at runtime
    # (sources.ezproxy imports ezproxy_target from here).
    if outcome == "captcha":
        return True
    if outcome == "error":
        low = note.lower()
        return any(h in low for h in _BLOCK_NOTE_HINTS)
    return False


def sources_for_item(item: Item, cfg: Config, sources: list[str]) -> list[str]:
    """Return configured sources that look applicable to this item's metadata."""
    return [name for name in sources if source_applicable(item, cfg, name)]


def source_applicable(item: Item, cfg: Config, name: str) -> bool:
    if name == "unpaywall":
        return bool(item.doi and cfg.email)
    if name == "openalex":
        return bool(item.doi)
    if name == "arxiv":
        if item.arxiv_id:
            return True
        if item.doi and item.doi.startswith("10.48550/arxiv."):
            return True
        return item.item_type in _ARXIV_TYPES and len(item.title) >= 20
    if name == "biorxiv":
        doi = item.doi or _doi_from_biorxiv_url(item.url)
        return bool(doi and _BIORXIV_DOI.match(doi))
    if name == "europepmc":
        return bool(item.doi)
    if name == "semanticscholar":
        return bool(item.doi or item.arxiv_id)
    if name == "core":
        return bool(item.doi and cfg.core_api_key)
    if name == "scholar":
        return bool(item.doi or (item.title and len(item.title) >= 20))
    if name == "direct":
        from .sources.landing import grey_target

        target = grey_target(item)
        if not target:
            return False
        url = (item.url or "").strip().lower()
        check = url if url.startswith(("http://", "https://")) else target.lower()
        return not any(h in check for h in _DIRECT_SKIP_HOSTS)
    if name == "htmlpdf":
        url = (item.url or "").strip().lower()
        if not url.startswith(("http://", "https://")):
            return False
        if any(h in url for h in _DIRECT_SKIP_HOSTS):
            return False
        if item.item_type in {
            "webpage",
            "blogPost",
            "forumPost",
            "newspaperArticle",
            "magazineArticle",
        }:
            return True
        return item.item_type in {"document", "report"} and not item.doi
    if name == "ezproxy":
        if not cfg.ezproxy_base:
            return False
        cookie_path = cfg.ezproxy_cookies or (cfg.state_dir / "ezproxy-cookies.txt")
        vault = cfg.state_dir / "sessions" / "cookies.txt"
        if not cookie_path.is_file() and not vault.is_file():
            return False
        return bool(ezproxy_target(item))
    if name == "scihub":
        return bool(item.doi)
    return True


def _doi_from_biorxiv_url(url: str | None) -> str | None:
    if not url:
        return None
    m = _BIORXIV_URL.search(url)
    return normalize_doi(m.group(1)) if m else None


# Host suffixes campus EZProxy typically has database stanzas for. URL-only items
# on anything else (YouTube, Zotero, FAO, NGO pages, …) cannot yield a subscription PDF.
_EZPROXY_PUBLISHER_HOSTS = frozenset(
    {
        "doi.org",
        "dx.doi.org",
        "sciencedirect.com",
        "elsevier.com",
        "springer.com",
        "springeropen.com",
        "springernature.com",
        "nature.com",
        "wiley.com",
        "wiley-vch.de",
        "jstor.org",
        "tandfonline.com",
        "taylorandfrancis.com",
        "sagepub.com",
        "academic.oup.com",
        "oup.com",
        "cambridge.org",
        "ieee.org",
        "acm.org",
        "science.org",
        "sciencemag.org",
        "cell.com",
        "thelancet.com",
        "nejm.org",
        "bmj.com",
        "pnas.org",
        "annualreviews.org",
        "iop.org",
        "aps.org",
        "rsc.org",
        "acs.org",
        "aip.org",
        "frontiersin.org",
        "mdpi.com",
        "plos.org",
        "hindawi.com",
        "degruyter.com",
        "brill.com",
        "emerald.com",
        "emeraldinsight.com",
        "karger.com",
        "thieme-connect.com",
        "liebertpub.com",
        "informs.org",
        "siam.org",
        "royalsocietypublishing.org",
        "biomedcentral.com",
        "ssrn.com",
        "ingentaconnect.com",
        "proquest.com",
        "ebscohost.com",
        "oecd-ilibrary.org",
        "un-ilibrary.org",
        "muse.jhu.edu",
        "heinonline.org",
        "westlaw.com",
        "lexis.com",
        "lexisnexis.com",
        "cairn.info",
        "erudit.org",
        "openedition.org",
        "persee.fr",
        "dalloz.fr",
        "jamanetwork.com",
        "worldscientific.com",
        "iospress.com",
        "direct.mit.edu",
        "journals.uchicago.edu",
        "cochranelibrary.com",
        "ovid.com",
        "bioone.org",
    }
)


def ezproxy_target(item: Item) -> str | None:
    """DOI resolver URL, or a URL on a host libraries actually proxy."""
    if item.doi:
        return f"https://doi.org/{item.doi}"
    url = (item.url or "").strip()
    if not url.startswith(("http://", "https://")):
        return None
    host = _hostname(url)
    if not host or not _host_matches(host, _EZPROXY_PUBLISHER_HOSTS):
        return None
    if _host_matches(host, ("doi.org", "dx.doi.org")):
        doi = normalize_doi(urlparse(url).path)
        return f"https://doi.org/{doi}" if doi else None
    return url


def _hostname(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        return host[4:]
    return host


def _host_matches(host: str, suffixes: frozenset[str] | tuple[str, ...]) -> bool:
    return any(host == s or host.endswith("." + s) for s in suffixes)
