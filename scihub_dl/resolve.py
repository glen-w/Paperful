"""Identifier extraction / normalisation and Crossref title lookup."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

import httpx

# Parentheses are legal inside DOIs (old Elsevier: 10.1016/0031-9384(69)90073-0); brackets/braces are not.
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>\[\]\{\}]+)", re.IGNORECASE)
ARXIV_NEW_RE = re.compile(r"(?<!\d)(\d{4}\.\d{4,5})(v\d+)?(?!\d)")
ARXIV_OLD_RE = re.compile(r"\b([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?\b")
_TRAILING_PUNCT_NO_PAREN = ".,;:>\"'"


def normalize_doi(raw: str | None) -> str | None:
    """Lower-case a DOI and strip resolver prefixes and trailing punctuation."""
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^doi:\s*", "", s, flags=re.IGNORECASE)
    m = DOI_RE.search(s)
    if not m:
        return None
    doi = m.group(1).rstrip(_TRAILING_PUNCT_NO_PAREN)
    # A trailing ')' belongs to the DOI only if it closes a '(' inside it: "(doi:10.1/x)" vs "10.1016/...(69)90073-0"
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1].rstrip(_TRAILING_PUNCT_NO_PAREN)
    # Common URL suffixes glued to DOIs in URL fields
    doi = re.sub(r"/(?:full|abstract|pdf|epdf|meta|summary)$", "", doi, flags=re.IGNORECASE)
    return doi.lower()


def extract_doi(text: str | None) -> str | None:
    """Find the first DOI in free text (Zotero `extra`, URL, ...)."""
    if not text:
        return None
    m = re.search(r"(?im)^\s*DOI:\s*(\S+)", text)
    if m:
        d = normalize_doi(m.group(1))
        if d:
            return d
    return normalize_doi(text)


def extract_arxiv_id(text: str | None) -> str | None:
    """Find an arXiv identifier in a URL or `extra` field."""
    if not text:
        return None
    if "arxiv" not in text.lower():
        return None
    m = re.search(r"(?im)^\s*arXiv:\s*(\S+)", text)
    if m:
        cand = m.group(1)
    else:
        cand = text
    m2 = ARXIV_NEW_RE.search(cand)
    if m2:
        return m2.group(1)
    m3 = ARXIV_OLD_RE.search(cand)
    if m3:
        return m3.group(1)
    return None


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    t = unicodedata.normalize("NFKD", title)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def title_similarity(a: str | None, b: str | None) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


@dataclass
class CrossrefMatch:
    doi: str
    score: float
    title: str
    year: int | None


def crossref_lookup(
    client: httpx.Client,
    title: str,
    author: str | None = None,
    year: int | None = None,
    email: str = "",
    min_score: float = 0.90,
) -> CrossrefMatch | None:
    """Find a DOI for a title via Crossref; accept only confident matches.

    Zotero titles often carry a glued-on subtitle ("Main title. Subtitle...") that Crossref
    does not index as part of the title, so a second query uses the leading segment only.
    """
    if not title or len(normalize_title(title)) < 12:
        return None
    variants = [title]
    short = short_title(title)
    if short and short != title:
        variants.append(short)
    for variant in variants:
        match = _crossref_query(client, variant, variants, author, year, email, min_score)
        if match:
            return match
    return None


def short_title(title: str) -> str | None:
    """Leading segment before '. ', ': ', ' | ' or ' - ' if it is still a meaningful title."""
    m = re.split(r"(?<=[a-z0-9\)])\.\s+|:\s+|\s+\|\s+|\s+[-–—]\s+", title, maxsplit=1)
    head = m[0].strip() if m else ""
    return head if len(head.split()) >= 4 else None


def _crossref_query(
    client: httpx.Client,
    query: str,
    accept_titles: list[str],
    author: str | None,
    year: int | None,
    email: str,
    min_score: float,
) -> CrossrefMatch | None:
    params: dict[str, Any] = {"query.bibliographic": query, "rows": 5, "select": "DOI,title,issued,author"}
    if author:
        params["query.author"] = author
    if email:
        params["mailto"] = email
    try:
        resp = client.get("https://api.crossref.org/works", params=params, timeout=30)
        resp.raise_for_status()
        items = resp.json().get("message", {}).get("items", [])
    except (httpx.HTTPError, ValueError):
        return None
    best: CrossrefMatch | None = None
    for it in items:
        titles = it.get("title") or []
        if not titles:
            continue
        score = max(title_similarity(mine, t) for t in titles for mine in accept_titles)
        cr_year = _issued_year(it)
        if year and cr_year and abs(cr_year - year) > 1:
            score -= 0.1
        if best is None or score > best.score:
            best = CrossrefMatch(doi=it["DOI"].lower(), score=score, title=titles[0], year=cr_year)
    if best and best.score >= min_score:
        return best
    return None


def _issued_year(work: dict[str, Any]) -> int | None:
    parts = (work.get("issued") or {}).get("date-parts") or []
    if parts and parts[0] and parts[0][0]:
        try:
            return int(parts[0][0])
        except (TypeError, ValueError):
            return None
    return None
