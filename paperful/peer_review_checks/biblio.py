"""Bibliography and in-text citation checkers."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx

from ..config import Config
from ..critique import Finding, make_finding
from ..critique_extract import ExtractedDoc, loc_of_span
from ..identity import LibraryFingerprint
from ..refs_gap import aggregate_citations
from ..resolve import DOI_RE, normalize_doi
from ..snowball.bibliography import parse_bibliography_entries
from ..zot import Item
from ._common import _AUTHOR_YEAR, _NUM_CITE, _split_body_biblio


def _bibliography_and_cites(
    cfg: Config,
    doc: ExtractedDoc,
    item: Item | None,
    scope_items: list[Item],
    offline: bool,
    client: httpx.Client | None,
    on_status: Callable[[str], None] | None = None,
) -> list[Finding]:
    out: list[Finding] = []
    body, biblio = _split_body_biblio(doc.text)
    entries = parse_bibliography_entries(doc.text)
    dois: list[str] = []
    for entry in entries:
        doi = normalize_doi(entry.get("doi")) or ""
        if doi:
            dois.append(doi)
    for match in DOI_RE.finditer(biblio or doc.text):
        doi = normalize_doi(match.group(1))
        if doi and doi not in dois:
            dois.append(doi)
            entries.append(
                {"doi": doi, "title": "", "year": None, "raw": match.group(0)}
            )

    in_text_nums = _in_text_numbers(body)
    biblio_nums = _biblio_numbers(biblio or doc.text)
    if in_text_nums or biblio_nums:
        missing = sorted(in_text_nums - biblio_nums)
        unused = sorted(biblio_nums - in_text_nums)
        if missing:
            out.append(
                make_finding(
                    code="cite_not_in_bibliography",
                    severity="warn",
                    detail=f"In-text numeric cites with no bibliography row: {', '.join(map(str, missing[:20]))}.",
                    quote=f"[{missing[0]}]" if missing else "",
                    loc=loc_of_span(doc, f"[{missing[0]}]") if missing else "",
                    source="rule",
                )
            )
        if unused:
            out.append(
                make_finding(
                    code="bibliography_not_cited",
                    severity="info",
                    detail=f"Bibliography numbers not cited in-text: {', '.join(map(str, unused[:20]))}.",
                    source="rule",
                )
            )
    else:
        out.extend(_author_year_hygiene(doc, body, biblio))

    years = [e.get("year") for e in entries if isinstance(e.get("year"), int)]
    item_year = getattr(item, "year", None) if item is not None else None
    if years and item_year:
        age_cut = cfg.critique_cite_age_years
        old = [y for y in years if item_year - int(y) >= age_cut]
        newest = max(years)
        if old:
            out.append(
                make_finding(
                    code="citation_age",
                    severity="info",
                    detail=(
                        f"{len(old)}/{len(years)} bibliography years are ≥{age_cut} years "
                        f"before the item year {item_year}."
                    ),
                    source="rule",
                )
            )
        if newest and item_year - int(newest) >= max(3, age_cut // 2):
            out.append(
                make_finding(
                    code="citation_newest_age",
                    severity="info",
                    detail=f"Newest bibliography year is {newest}; item year is {item_year}.",
                    source="rule",
                )
            )

    if scope_items:
        fp = LibraryFingerprint.from_items(scope_items)
        refs = aggregate_citations([("doc", entries)], fp)
        missing_lib = [r for r in refs if r.doi and not r.already_exists]
        if missing_lib:
            sample = ", ".join(r.doi for r in missing_lib[:8])
            out.append(
                make_finding(
                    code="cited_not_in_library",
                    severity="info",
                    detail=f"{len(missing_lib)} cited DOI(s) not in the scoped library. e.g. {sample}",
                    source="rule",
                )
            )

    if not offline and client is not None:
        out.extend(
            _cited_work_status(cfg, client, dois, entries, item, on_status=on_status)
        )
    elif dois:
        out.append(
            make_finding(
                code="doi_status_skipped_offline",
                severity="info",
                detail="Crossref/OpenAlex cite checks skipped (offline).",
                source="rule",
            )
        )
    return out


def _in_text_numbers(body: str) -> set[int]:
    found: set[int] = set()
    for m in _NUM_CITE.finditer(body or ""):
        for part in re.split(r"[,]", m.group(1)):
            part = part.strip()
            if not part:
                continue
            if "-" in part or "–" in part:
                a, b = re.split(r"[-–]", part, maxsplit=1)
                try:
                    lo, hi = int(a.strip()), int(b.strip())
                except ValueError:
                    continue
                found.update(range(lo, hi + 1))
            else:
                try:
                    found.add(int(part))
                except ValueError:
                    continue
    return found


def _author_year_hygiene(doc: ExtractedDoc, body: str, biblio: str) -> list[Finding]:
    cites = list(_AUTHOR_YEAR.finditer(body or ""))
    if not cites:
        return []
    hay = (biblio or "").lower()
    missing: list[str] = []
    for m in cites:
        surname = m.group(1).split()[0]
        year = m.group(2)
        if surname.lower() not in hay or year[:4] not in hay:
            missing.append(m.group(0))
    if not missing:
        return []
    sample = missing[0]
    return [
        make_finding(
            code="cite_not_in_bibliography",
            severity="warn",
            loc=loc_of_span(doc, sample),
            quote=sample,
            detail=f"Author-year cite(s) with no matching bibliography surname/year: {', '.join(missing[:8])}.",
            source="rule",
        )
    ]


def _biblio_numbers(biblio: str) -> set[int]:
    found: set[int] = set()
    for m in re.finditer(r"(?m)^\s*\[(\d+)\]", biblio or ""):
        found.add(int(m.group(1)))
    if not found:
        for m in re.finditer(r"(?m)^\s*(\d+)\.\s", biblio or ""):
            found.add(int(m.group(1)))
    return found


def _cited_work_status(
    cfg: Config,
    client: httpx.Client,
    dois: list[str],
    entries: list[dict[str, Any]],
    item: Item | None,
    on_status: Callable[[str], None] | None = None,
) -> list[Finding]:
    from ..screen import lookup_doi_status

    say = on_status or (lambda _msg: None)
    out: list[Finding] = []
    authors = (
        [s.lower() for s in (getattr(item, "creator_surnames", None) or [])]
        if item
        else []
    )
    self_hits = 0
    resolved = 0
    cap = min(len(dois), 80)
    if cap:
        extra = f" of {len(dois)}" if len(dois) > cap else ""
        say(f"Cited-work status: 0/{cap}{extra} DOI(s) at Crossref/OpenAlex")
    for i, doi in enumerate(dois[:80], start=1):
        if i == 1 or i % 10 == 0 or i == cap:
            say(f"Cited-work status: {i}/{cap} DOI(s)")
        codes = lookup_doi_status(client, cfg, doi, refresh=False)
        if "retracted" in codes:
            out.append(
                make_finding(
                    code="cited_retracted",
                    severity="major",
                    detail=f"Bibliography DOI {doi} has Crossref/OpenAlex status retracted.",
                    quote=doi,
                    source="crossref",
                )
            )
        elif "withdrawn" in codes:
            out.append(
                make_finding(
                    code="cited_withdrawn",
                    severity="warn",
                    detail=f"Bibliography DOI {doi} has Crossref/OpenAlex status withdrawn.",
                    quote=doi,
                    source="crossref",
                )
            )
        elif "expression_of_concern" in codes:
            out.append(
                make_finding(
                    code="cited_expression_of_concern",
                    severity="warn",
                    detail=(
                        f"Bibliography DOI {doi} has Crossref/OpenAlex status "
                        "expression_of_concern."
                    ),
                    quote=doi,
                    source="crossref",
                )
            )
        year, surnames, unresolved = _crossref_work(client, cfg, doi)
        if unresolved:
            out.append(
                make_finding(
                    code="unresolved_doi",
                    severity="warn",
                    detail=f"DOI did not resolve at Crossref: {doi}",
                    quote=doi,
                    source="crossref",
                )
            )
            continue
        resolved += 1
        if authors and surnames and any(a in surnames for a in authors):
            self_hits += 1
        if year and item is not None and item.year:
            # fill missing bibliography years for age (already handled if parsed)
            pass
    if resolved and authors:
        rate = self_hits / max(1, resolved)
        out.append(
            make_finding(
                code="self_citation",
                severity="info",
                detail=f"Author-surname overlap on {self_hits}/{resolved} resolved cited works ({rate:.0%}).",
                source="openalex",
            )
        )
    return out


def _crossref_work(
    client: httpx.Client, cfg: Config, doi: str
) -> tuple[int | None, set[str], bool]:
    cleaned = normalize_doi(doi) or doi
    try:
        params = {"mailto": cfg.email} if cfg.email else None
        resp = client.get(
            "https://api.crossref.org/works/" + quote(cleaned, safe="/()"),
            params=params,
            timeout=20,
        )
    except httpx.HTTPError:
        return None, set(), False
    if resp.status_code == 404:
        return None, set(), True
    if resp.status_code != 200:
        return None, set(), False
    try:
        msg = resp.json().get("message") or {}
    except ValueError:
        return None, set(), False
    year = None
    for key in ("published-print", "published-online", "issued"):
        parts = ((msg.get(key) or {}).get("date-parts") or [[]])[0]
        if parts:
            try:
                year = int(parts[0])
            except (TypeError, ValueError):
                year = None
            if year:
                break
    surnames: set[str] = set()
    for author in msg.get("author") or []:
        if isinstance(author, dict) and author.get("family"):
            surnames.add(str(author["family"]).lower())
    return year, surnames, False
