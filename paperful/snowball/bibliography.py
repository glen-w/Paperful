"""Recover outgoing references when OpenAlex (and peers) list none."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from ..pdfid import text_from_pdf
from ..resolve import extract_doi, normalize_doi, title_similarity
from .fill import FillPaused, s2_api_key, s2_paper
from .openalex import OpenAlexClient, short_id

PdfFetcher = Callable[[str], str]
S2Getter = Callable[[str], dict[str, Any] | None]

TITLE_MIN = 0.92
TITLE_LEAD = 0.05
_REF_HEADING = re.compile(r"(?im)^(?:\d+\.?\s*)?references?\s*$")
_ENTRY_SPLIT = re.compile(r"(?:^|\n)\s*\[(\d+)\]\s+")
_YEAR_TITLE = re.compile(
    r"\((\d{4})\)\s*\.\s*(.+?)(?:\.\s+[A-Z]|\.\s*$|\n|$)",
    re.DOTALL,
)


def recover_referenced_works(
    client: OpenAlexClient,
    work: dict[str, Any],
    *,
    s2_getter: S2Getter | None = None,
    pdf_fetcher: PdfFetcher | None = None,
    cache_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """OpenAlex works this seed cites when ``referenced_works`` is empty.

    Tries Semantic Scholar, then Europe PMC, then an open PDF bibliography.
    A pause does not abort the hop. Each returned work carries ``_recovery``.
    """
    if referenced_work_ids(work):
        return []
    doi = normalize_doi(str(work.get("doi") or "")) or ""
    getter = s2_getter if s2_getter is not None else getattr(client, "s2_getter", None)
    fetcher = pdf_fetcher if pdf_fetcher is not None else getattr(client, "pdf_fetcher", None)
    cache = cache_dir if cache_dir is not None else getattr(client, "s2_cache_dir", None)

    if getter is None and cache is not None:
        key = s2_api_key()
        getter = lambda d, _cache=cache, _key=key: s2_paper(d, cache_dir=_cache, api_key=_key)

    if doi and getter is not None:
        try:
            payload = getter(doi)
        except FillPaused:
            payload = None
        except Exception:
            payload = None
        works = _works_from_s2(client, payload)
        if works:
            label = doi or short_id(str(work.get("id") or "")) or "seed"
            client.note(f"recovered {len(works)} refs via Semantic Scholar · {label}")
            return works

    epmc_getter = getattr(client, "epmc_getter", None)
    if doi and epmc_getter is not None:
        try:
            epmc = epmc_getter(doi)
        except FillPaused:
            epmc = None
        except Exception:
            epmc = None
        epmc_dois = [
            str(ref.get("doi") or "")
            for ref in ((epmc or {}).get("references") or [])
            if isinstance(ref, dict) and ref.get("doi")
        ]
        works = _resolve_dois(client, epmc_dois, source="europepmc")
        if works:
            label = doi or short_id(str(work.get("id") or "")) or "seed"
            client.note(f"recovered {len(works)} refs via Europe PMC · {label}")
            return works

    text, pdf_path = _pdf_bibliography_text(work, fetcher)
    if not text:
        label = doi or short_id(str(work.get("id") or "")) or "seed"
        client.note(f"no remote refs and no open PDF bibliography · {label}")
        return []
    works = _works_from_pdf_text(client, text)
    if works:
        label = doi or short_id(str(work.get("id") or "")) or "seed"
        client.note(f"recovered {len(works)} refs from open PDF · {label}")
    else:
        label = doi or short_id(str(work.get("id") or "")) or "seed"
        client.note(f"open PDF bibliography yielded no OpenAlex matches · {label}")
    return works


def referenced_work_ids(work: dict[str, Any]) -> list[str]:
    raw = work.get("referenced_works") or []
    return [short_id(str(item)) for item in raw if short_id(str(item))]


def parse_bibliography_entries(text: str) -> list[dict[str, Any]]:
    """Split a references section into DOI / title / year entries."""
    body = _references_section(dehyphenate(text))
    if not body:
        return []
    parts = _ENTRY_SPLIT.split(body)
    # parts: preamble, n1, entry1, n2, entry2, ...
    entries: list[dict[str, Any]] = []
    if len(parts) >= 3:
        for i in range(1, len(parts), 2):
            if i + 1 >= len(parts):
                break
            entries.append(_parse_entry(parts[i + 1]))
    else:
        # Unnumbered block: try whole section as one blob, or line-based.
        chunk = body.strip()
        if chunk:
            entries.append(_parse_entry(chunk))
    return [item for item in entries if item.get("doi") or item.get("title")]


def dehyphenate(text: str) -> str:
    """Join words split across lines with a trailing hyphen."""
    return re.sub(r"-\n\s*", "", text or "")


def _references_section(text: str) -> str:
    matches = list(_REF_HEADING.finditer(text or ""))
    if not matches:
        return ""
    start = matches[-1].end()
    return (text or "")[start:].strip()


def _parse_entry(raw: str) -> dict[str, Any]:
    text = " ".join((raw or "").split())
    doi = extract_doi(text) or ""
    if doi:
        doi = normalize_doi(doi) or doi.lower()
    year: int | None = None
    title = ""
    match = _YEAR_TITLE.search(text)
    if match:
        try:
            year = int(match.group(1))
        except ValueError:
            year = None
        title = match.group(2).strip().rstrip(".")
        # Drop trailing venue crumbs left in the title span.
        title = re.split(r"\.\s+(?:Journal|Marine|Frontiers|NPJ|Pacific|UNESCO|United)\b", title, maxsplit=1)[0]
        title = title.strip().rstrip(".")
    return {"doi": doi, "title": title, "year": year, "raw": text}


def _works_from_s2(client: OpenAlexClient, payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    dois: list[str] = []
    seen: set[str] = set()
    for ref in payload.get("references") or []:
        if not isinstance(ref, dict):
            continue
        raw = str((ref.get("externalIds") or {}).get("DOI") or "")
        doi = normalize_doi(raw) or ""
        if not doi or doi in seen:
            continue
        seen.add(doi)
        dois.append(doi)
    return _resolve_dois(client, dois, source="semanticscholar")


def _works_from_pdf_text(client: OpenAlexClient, text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in parse_bibliography_entries(text):
        work = None
        doi = entry.get("doi") or ""
        if doi:
            try:
                work = client.work_by_doi(doi)
            except Exception:
                work = None
        if work is None and entry.get("title"):
            work = _match_title(client, str(entry["title"]), entry.get("year"))
        if not work:
            continue
        oa = short_id(str(work.get("id") or ""))
        if not oa or oa in seen:
            continue
        seen.add(oa)
        tagged = dict(work)
        tagged["_recovery"] = "pdf"
        out.append(tagged)
    return out


def _resolve_dois(client: OpenAlexClient, dois: list[str], *, source: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doi in dois:
        try:
            work = client.work_by_doi(doi)
        except Exception:
            work = None
        if not work:
            continue
        oa = short_id(str(work.get("id") or ""))
        if not oa or oa in seen:
            continue
        seen.add(oa)
        tagged = dict(work)
        tagged["_recovery"] = source
        out.append(tagged)
    return out


def _match_title(client: OpenAlexClient, title: str, year: int | None) -> dict[str, Any] | None:
    query = (title or "").strip()
    if len(query) < 8:
        return None
    try:
        hits = client.search(query, limit=5, year_from=year, year_to=year)
    except Exception:
        return None
    scored: list[tuple[float, dict[str, Any]]] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        score = title_similarity(query, str(hit.get("display_name") or ""))
        hit_year = hit.get("publication_year")
        if year is not None and hit_year is not None and int(hit_year) != int(year):
            continue
        if score < TITLE_MIN:
            continue
        scored.append((score, hit))
    if not scored:
        return None
    scored.sort(key=lambda pair: (-pair[0], short_id(str(pair[1].get("id") or ""))))
    best_score, best = scored[0]
    if len(scored) > 1 and best_score - scored[1][0] < TITLE_LEAD:
        return None
    return best


def _pdf_bibliography_text(work: dict[str, Any], fetcher: PdfFetcher | None) -> tuple[str, str]:
    url = open_pdf_url(work)
    if not url:
        return "", ""
    if fetcher is not None:
        return fetcher(url) or "", ""
    return _download_pdf_text(url)


def open_pdf_url(work: dict[str, Any]) -> str:
    oa = work.get("open_access") if isinstance(work.get("open_access"), dict) else {}
    for key in ("oa_url",):
        url = str(oa.get(key) or "").strip()
        if _looks_like_pdf_url(url):
            return url
    loc = work.get("primary_location") if isinstance(work.get("primary_location"), dict) else {}
    for key in ("pdf_url",):
        url = str(loc.get(key) or "").strip()
        if _looks_like_pdf_url(url):
            return url
    # Bronze OA sometimes only has oa_url that is the PDF itself.
    url = str(oa.get("oa_url") or "").strip()
    if url.startswith("http"):
        return url
    return ""


def _looks_like_pdf_url(url: str) -> bool:
    if not url.startswith("http"):
        return False
    path = urlparse(url).path.lower()
    return path.endswith(".pdf") or "/pdf" in path


def pdf_payload_for_row(row: Any) -> dict[str, Any] | None:
    """Bibliography payload for one candidate, keeping a downloaded open PDF."""
    biblio = getattr(row, "biblio", None) or {}
    work = {
        "doi": (getattr(row, "ids", None) or {}).get("doi") or "",
        "open_access": {"oa_url": biblio.get("oa_url") or ""},
        "primary_location": {"pdf_url": biblio.get("pdf_url") or ""},
    }
    text, path = _pdf_bibliography_text(work, None)
    if not text:
        return None
    payload: dict[str, Any] = {
        "references": [
            {"doi": entry.get("doi") or "", "title": entry.get("title") or "", "year": entry.get("year")}
            for entry in parse_bibliography_entries(text)
        ]
    }
    if path:
        payload["cached_pdf"] = path
    return payload


def pdf_payload(doi: str, *, cache_dir: Path | None = None) -> dict[str, Any] | None:
    """Open-PDF bibliography as a fill payload. Saves the PDF when one is downloaded."""
    work = {"doi": doi, "open_access": {}, "primary_location": {}}
    text, path = _pdf_bibliography_text(work, None)
    if not text:
        return None
    refs = [
        {"doi": entry.get("doi") or "", "title": entry.get("title") or "", "year": entry.get("year")}
        for entry in parse_bibliography_entries(text)
    ]
    payload: dict[str, Any] = {"references": refs}
    if path:
        payload["cached_pdf"] = path
    if cache_dir is not None and path:
        cache_dir.mkdir(parents=True, exist_ok=True)
        dest = cache_dir / f"{doi.replace('/', '_')}.pdf"
        dest.write_bytes(Path(path).read_bytes())
        payload["cached_pdf"] = str(dest)
    return payload


def _download_pdf_text(url: str) -> tuple[str, str]:
    try:
        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            resp = client.get(url, headers={"User-Agent": "paperful-snowball/0.1"})
            resp.raise_for_status()
            data = resp.content
    except (httpx.HTTPError, OSError, ValueError):
        return "", ""
    if not data or data[:4] != b"%PDF":
        return "", ""
    path = Path(tempfile.mkdtemp(prefix="paperful-bib-")) / "paper.pdf"
    path.write_bytes(data)
    return text_from_pdf(path, max_pages=None), str(path)
