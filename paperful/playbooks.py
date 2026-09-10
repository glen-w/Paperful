"""Declarative grey-literature PDF playbooks (rewrite / scrape / synthesize)."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

# Hosts where the item URL is not a PDF landing; synthesize playbooks may still apply.
DIRECT_SKIP_HOSTS = (
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

_UN_LANG = frozenset({"en", "fr", "es", "ar", "ru", "zh", "de"})
_BUILTIN_PACK = Path(__file__).resolve().parent / "data" / "grey_playbooks_ocean.toml"
_KINDS = frozenset({"rewrite", "scrape", "synthesize"})


@dataclass(frozen=True)
class GreyPlaybook:
    name: str
    kind: str
    hosts: tuple[str, ...] = ()
    url_re: str = ""
    pdf_template: str = ""
    href_re: str = ""
    match_re: str = ""
    parser: str = ""

    def compiled_url(self) -> re.Pattern[str] | None:
        return re.compile(self.url_re) if self.url_re else None

    def compiled_href(self) -> re.Pattern[str] | None:
        return re.compile(self.href_re) if self.href_re else None

    def compiled_match(self) -> re.Pattern[str] | None:
        return re.compile(self.match_re) if self.match_re else None


def url_is_direct_skip(url: str) -> bool:
    low = (url or "").lower()
    return any(h in low for h in DIRECT_SKIP_HOSTS)


def host_matches(host: str, patterns: tuple[str, ...] | list[str]) -> bool:
    host = (host or "").lower()
    if not host:
        return False
    for raw in patterns:
        p = (raw or "").lower().lstrip(".")
        if not p:
            continue
        if host == p or host.endswith("." + p) or p in host:
            return True
    return False


def playbook_from_dict(raw: dict[str, Any]) -> GreyPlaybook | None:
    name = str(raw.get("name") or "").strip()
    kind = str(raw.get("kind") or "").strip().lower()
    if not name or kind not in _KINDS:
        return None
    hosts_raw = raw.get("hosts") or []
    if isinstance(hosts_raw, str):
        hosts = (hosts_raw,)
    else:
        hosts = tuple(str(h).strip() for h in hosts_raw if str(h).strip())
    return GreyPlaybook(
        name=name,
        kind=kind,
        hosts=hosts,
        url_re=str(raw.get("url_re") or ""),
        pdf_template=str(raw.get("pdf_template") or ""),
        href_re=str(raw.get("href_re") or ""),
        match_re=str(raw.get("match_re") or ""),
        parser=str(raw.get("parser") or "").strip().lower(),
    )


def playbooks_from_toml_raw(raw: dict[str, Any]) -> list[GreyPlaybook]:
    rows = raw.get("grey_playbooks") or []
    out: list[GreyPlaybook] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pb = playbook_from_dict(row)
        if pb:
            out.append(pb)
    return out


@lru_cache(maxsize=1)
def load_builtin_pack() -> tuple[GreyPlaybook, ...]:
    if not _BUILTIN_PACK.is_file():
        return ()
    with _BUILTIN_PACK.open("rb") as fh:
        raw = tomllib.load(fh)
    return tuple(playbooks_from_toml_raw(raw))


def load_pack_file(path: Path) -> list[GreyPlaybook]:
    """Load `[[grey_playbooks]]` rows from a single TOML pack file."""
    if not path.is_file():
        return []
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    return playbooks_from_toml_raw(raw)


def load_pack_dir(directory: Path) -> list[GreyPlaybook]:
    """Load every `*.toml` pack in *directory* (sorted by name). Missing dir → []."""
    if not directory.is_dir():
        return []
    out: list[GreyPlaybook] = []
    for path in sorted(directory.glob("*.toml")):
        out.extend(load_pack_file(path))
    return out


def merge_playbooks(
    builtin: bool,
    user: list[GreyPlaybook] | tuple[GreyPlaybook, ...] = (),
    *,
    extra: list[GreyPlaybook] | tuple[GreyPlaybook, ...] = (),
) -> list[GreyPlaybook]:
    """Builtin pack, then *extra* (dir packs), then *user*; later same `name` replaces."""
    by_name: dict[str, GreyPlaybook] = {}
    order: list[str] = []

    def _layer(books: list[GreyPlaybook] | tuple[GreyPlaybook, ...]) -> None:
        for pb in books:
            if pb.name not in by_name:
                order.append(pb.name)
            by_name[pb.name] = pb

    if builtin:
        _layer(load_builtin_pack())
    _layer(extra)
    _layer(user)
    return [by_name[n] for n in order if n in by_name]


def default_playbooks() -> list[GreyPlaybook]:
    return merge_playbooks(True, ())


def _format_template(template: str, m: re.Match[str]) -> str:
    """Expand {name}, {1}… and {0} (first capture, else full match)."""
    out = template
    for k, v in m.groupdict().items():
        if k is not None:
            out = out.replace("{" + k + "}", v or "")
    last = m.lastindex or 0
    for i in range(last, 0, -1):
        out = out.replace("{" + str(i) + "}", m.group(i) or "")
    zero = (m.group(1) if last >= 1 else m.group(0)) or ""
    out = out.replace("{0}", zero)
    return out


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


def _symbol_from_undocs_url(url: str, symbol_re: re.Pattern[str] | None) -> str | None:
    p = urlparse(url)
    host = (p.netloc or "").lower()
    qs = parse_qs(p.query, keep_blank_values=False)
    qs_l = {k.lower(): v for k, v in qs.items()}
    if (
        "undocs.org" in host
        or host.endswith("docs.un.org")
        or "documents.un.org" in host
    ):
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
        if not candidate:
            return None
        if symbol_re:
            m = symbol_re.search(candidate.replace("%2F", "/").replace("%2f", "/"))
            return m.group(1).strip().replace(" ", "") if m else None
        return candidate
    if "daccess-ods.un.org" in host:
        if "ds" in qs_l and qs_l["ds"]:
            return unquote(qs_l["ds"][0]).strip()
    blob = unquote(p.path) + " " + p.query
    if symbol_re:
        m = symbol_re.search(blob.replace("%2F", "/").replace("%2f", "/"))
        return m.group(1).strip().replace(" ", "") if m else None
    return None


def _undocs_symbol_re(playbooks: list[GreyPlaybook]) -> re.Pattern[str] | None:
    for pb in playbooks:
        if pb.kind == "synthesize" and "undocs" in pb.name and pb.match_re:
            return pb.compiled_match()
    for pb in playbooks:
        if pb.kind == "synthesize" and pb.match_re:
            return pb.compiled_match()
    return None


def apply_rewrite(url: str, playbooks: list[GreyPlaybook] | None = None) -> str | None:
    """Zero-fetch URL → PDF from rewrite playbooks (and registered parsers)."""
    books = playbooks if playbooks is not None else default_playbooks()
    host = (urlparse(url).netloc or "").lower()
    symbol_re = _undocs_symbol_re(books)
    for pb in books:
        if pb.kind != "rewrite":
            continue
        if pb.hosts and not host_matches(host, pb.hosts):
            continue
        if pb.parser == "undocs":
            if (
                looks_like_pdf_url(url)
                and "undocs.org" in host
                and "symbol=" in url.lower()
            ):
                return url
            symbol = _symbol_from_undocs_url(url, symbol_re)
            if symbol:
                return f"https://undocs.org/pdf?symbol={symbol}"
            continue
        cre = pb.compiled_url()
        if not cre or not pb.pdf_template:
            continue
        m = cre.search(url)
        if m:
            return _format_template(pb.pdf_template, m)
    return None


def apply_synthesize(
    text: str, playbooks: list[GreyPlaybook] | None = None
) -> str | None:
    """Extra/title (or free text) → PDF URL from synthesize playbooks."""
    if not text:
        return None
    books = playbooks if playbooks is not None else default_playbooks()
    blob = text.replace("%2F", "/").replace("%2f", "/")
    for pb in books:
        if pb.kind != "synthesize" or not pb.pdf_template:
            continue
        cre = pb.compiled_match()
        if not cre:
            continue
        m = cre.search(blob)
        if m:
            return _format_template(pb.pdf_template, m)
    return None


def scrape_playbooks_for_host(
    host: str, playbooks: list[GreyPlaybook] | None = None
) -> list[GreyPlaybook]:
    books = playbooks if playbooks is not None else default_playbooks()
    return [
        pb
        for pb in books
        if pb.kind == "scrape" and pb.hosts and host_matches(host, pb.hosts)
    ]


def href_matches_scrape(href: str, text: str, playbooks: list[GreyPlaybook]) -> bool:
    blob = f"{href} {text}"
    for pb in playbooks:
        cre = pb.compiled_href()
        if cre and cre.search(blob):
            return True
    return False
