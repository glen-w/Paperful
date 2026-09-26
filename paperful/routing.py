"""Per-item source lanes and block detection for circuit breakers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from .config import Config
from .playbooks import url_is_direct_skip
from .resolve import normalize_doi
from .zot import Item

if TYPE_CHECKING:
    from .sources.base import Outcome

# Sci-Hub largely stopped routine ingestion after ~2021 (India court pause +
# 2FA; their own "not in database" copy says post-2021 articles are mostly
# absent). Years through this value are still tried; later dated items skip.
SCIHUB_COVERAGE_THROUGH_YEAR = 2021

_ARXIV_TYPES = frozenset(
    {"preprint", "journalArticle", "conferencePaper", "report", "manuscript"}
)
# Item types htmlpdf can ever print (web/news, or DOI-less document/report).
_HTMLPDF_ITEM_TYPES = frozenset(
    {
        "webpage",
        "blogPost",
        "forumPost",
        "newspaperArticle",
        "magazineArticle",
        "document",
        "report",
    }
)
# Playwright vault lanes. `run` auto-appends `browser_agent` after the last of
# these, and only invokes the agent when one of them was tried and failed.
BROWSER_LANES = frozenset({"scholar", "ezproxy", "htmlpdf"})
_BIORXIV_DOI = re.compile(r"^10\.1101/", re.IGNORECASE)
_BIORXIV_URL = re.compile(
    r"(?:bio|med)rxiv\.org/content/(?:[^/\s]+/)*(10\.1101/\d+(?:\.\d+)*)(?:v\d+)?",
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


def prior_playwright_miss(attempts: list[str]) -> str | None:
    """Last Playwright vault miss, for comparison when ``browser_agent`` hits.

    Matches Scholar/EZProxy ``browser-failed`` and htmlpdf not-found/error.
    Skips do not count.
    """
    found: str | None = None
    for entry in attempts:
        name, sep, rest = entry.partition(":")
        if not sep or name not in BROWSER_LANES:
            continue
        if rest.startswith("skipped"):
            continue
        if rest.startswith(("browser-failed(", "not_found(", "error(", "captcha(")):
            found = entry
    return found


def browser_lane_failed(attempts: list[str]) -> bool:
    """True when a vault browser lane was tried and did not yield a PDF.

    ``skipped(not applicable)`` does not count: recover is a fallback after
    Scholar / EZProxy / htmlpdf actually fail, not a substitute for them.
    """
    for entry in attempts:
        name, sep, rest = entry.partition(":")
        if not sep or name not in BROWSER_LANES:
            continue
        if rest.startswith("skipped(not applicable)"):
            continue
        return True
    return False


def with_recover_lane(cfg: Config, sources: list[str]) -> list[str]:
    """Insert ``browser_agent`` after other browser lanes when recover can auto-fire.

    Stays out of ``DEFAULT_SOURCES``. Opt-in is ``[llm].enabled`` (and
    ``[browser_agent].during_run``, the extra, and Python 3.11+). Inserted
    after the last of scholar / ezproxy / htmlpdf so Sci-Hub stays last.
    """
    listed = list(sources)
    if "browser_agent" in listed:
        return listed
    if not cfg.llm_enabled or not cfg.browser_agent_during_run:
        return listed
    if not any(name in BROWSER_LANES for name in listed):
        return listed
    import sys

    if sys.version_info < (3, 11):
        return listed
    from .browser_agent import browser_agent_extra_available

    if not browser_agent_extra_available():
        return listed
    last = max(i for i, name in enumerate(listed) if name in BROWSER_LANES)
    listed.insert(last + 1, "browser_agent")
    return listed


def filter_sources_for_item_types(
    sources: list[str], item_types: frozenset[str] | None
) -> list[str]:
    """Drop sources that can never apply under a CLI ``-T`` / ``--item-type`` scope.

    Unlike per-item ``source_routing``, this trims the run-level source list so
    ``--try-all`` on a journal-only scope does not check ``htmlpdf`` on every item.
    """
    if not item_types:
        return list(sources)
    out: list[str] = []
    for name in sources:
        if name == "htmlpdf" and not (item_types & _HTMLPDF_ITEM_TYPES):
            continue
        out.append(name)
    return out


def filter_sources_for_year_scope(
    sources: list[str], year_from: int | None
) -> list[str]:
    """Drop Sci-Hub when the CLI ``--year-from`` floor is past its coverage.

    Sci-Hub largely stopped ingesting after ~2021; a run scoped entirely after
    that year would only burn serial delays on not-found pages. Per-item routing
    still skips post-cutoff years when the run is unscoped or mixed.
    """
    if year_from is None or year_from <= SCIHUB_COVERAGE_THROUGH_YEAR:
        return list(sources)
    return [name for name in sources if name != "scihub"]


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
        doi = item.doi or doi_from_biorxiv_url(item.url)
        return is_cshl_doi(doi)
    if name == "europepmc":
        return bool(item.doi)
    if name == "openaire":
        return bool(item.doi)
    if name == "semanticscholar":
        return bool(item.doi or item.arxiv_id)
    if name == "core":
        return bool(item.doi and cfg.core_api_key)
    if name == "scholar":
        return bool(item.doi or (item.title and len(item.title) >= 20))
    if name == "direct":
        from .sources.landing import grey_target

        target = grey_target(item, cfg.grey_playbooks)
        if not target:
            return False
        # grey_target may synthesize a PDF URL when the item URL is a skip-host.
        return not url_is_direct_skip(target)
    if name == "htmlpdf":
        url = (item.url or "").strip().lower()
        if not url.startswith(("http://", "https://")):
            return False
        if url_is_direct_skip(url):
            return False
        if item.item_type not in _HTMLPDF_ITEM_TYPES:
            return False
        if item.item_type in {"document", "report"}:
            return not item.doi
        return True
    if name == "ezproxy":
        if not cfg.ezproxy_base:
            return False
        cookie_path = cfg.ezproxy_cookie_path
        vault = cfg.state_dir / "sessions" / "cookies.txt"
        profile = cfg.state_dir / "sessions" / "meta.json"
        chromium = cfg.state_dir / "sessions" / "chromium"
        if (
            not cookie_path.is_file()
            and not vault.is_file()
            and not (profile.is_file() and chromium.is_dir())
        ):
            return False
        return bool(ezproxy_target(item))
    if name == "scihub":
        if not item.doi:
            return False
        # Undated items are still tried; dated ones past coverage are not.
        if item.year is not None and item.year > SCIHUB_COVERAGE_THROUGH_YEAR:
            return False
        return True
    if name == "browser_agent":
        url = (item.url or "").strip().lower()
        return bool(cfg.llm_enabled and (item.doi or url.startswith(("http://", "https://"))))
    return True


def is_cshl_doi(doi: str | None) -> bool:
    """True for Cold Spring Harbor DOIs (bioRxiv, medRxiv, and a few journals)."""
    return bool(doi and _BIORXIV_DOI.match(doi))


def doi_from_biorxiv_url(url: str | None) -> str | None:
    """Pull a 10.1101 DOI out of a bioRxiv or medRxiv content URL."""
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


def publisher_host(url: str) -> str | None:
    """Canonical publisher suffix (sciencedirect.com, …), if `url` is one.

    Hyphen-rewritten EZProxy hosts (www-sciencedirect-com.proxy.edu) map
    back to the same family so a 403 on the naked publisher is not retried
    on the rewritten URL.
    """
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return None
    if host.startswith("www."):
        host = host[4:]
    for suffix in _EZPROXY_PUBLISHER_HOSTS:
        if host == suffix or host.endswith("." + suffix):
            return suffix
        hyphen = suffix.replace(".", "-")
        if hyphen and hyphen in host:
            return suffix
    if "idm.oclc.org" in host:
        return "idm.oclc.org"
    return None


def is_publisher_url(url: str) -> bool:
    return publisher_host(url) is not None


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
