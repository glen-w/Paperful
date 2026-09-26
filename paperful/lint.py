"""Read-only library lint: identifiers vs APIs vs PDF text on disk."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import Config
from .library import LibraryBackend
from .pdfid import doi_from_pdf
from .resolve import IdentifierCache, prepare_identifiers, strip_title_markup
from .store import Manifest
from .zot import Item

_SCHOLARLY = frozenset(
    {
        "journalArticle",
        "conferencePaper",
        "preprint",
        "report",
        "thesis",
        "book",
        "bookSection",
        "manuscript",
    }
)

_FILENAME_EXT = re.compile(r"\.(pdf|docx?|txt|html?)$", re.I)
_PATHY = re.compile(r"[/\\]")


@dataclass
class Finding:
    itemKey: str
    code: str
    title: str
    detail: str
    library_doi: str | None = None
    doi: str | None = None
    pdf_doi: str | None = None


def resolve_pdf_path(cfg: Config, item: Item, manifest: Manifest | None) -> Path | None:
    if item.pdf_path:
        p = Path(item.pdf_path)
        if p.is_file():
            return p
    rec = manifest.get(item.key) if manifest else None
    if rec and rec.path:
        p = Path(rec.path)
        if p.is_file():
            return p
    return None


def title_is_all_caps(title: str) -> bool:
    letters = [c for c in title if c.isalpha()]
    if len(letters) < 12:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) >= 0.85


# Articles, coordinating conjunctions, and short prepositions stay lowercase
# in Title Case unless they are the first or last word (Chicago-ish).
_TITLE_SMALL = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "but",
        "by",
        "en",
        "for",
        "from",
        "if",
        "in",
        "nor",
        "of",
        "on",
        "or",
        "per",
        "the",
        "to",
        "via",
        "vs",
        "vs.",
        "v",
        "v.",
        "with",
    }
)
_LEAD_TRAIL = re.compile(r"^(\W*)(.*?)(\W*)$", re.UNICODE)


def title_to_title_case(title: str) -> str:
    """Recase an ALL CAPS (or mostly-caps) scholarly title.

    Deterministic: same words, Chicago-ish Title Case. Two-letter tokens that
    are not small words stay acronyms (UN, EU, UK). Filename-like titles should
    be skipped by the caller.
    """
    parts = (title or "").split()
    if not parts:
        return title or ""
    last = len(parts) - 1
    out: list[str] = []
    for i, part in enumerate(parts):
        force = i == 0 or i == last or (i > 0 and parts[i - 1].endswith(":"))
        out.append(_title_case_hyphenated(part, force=force))
    return " ".join(out)


def _title_case_hyphenated(token: str, *, force: bool) -> str:
    bits = token.split("-")
    if len(bits) == 1:
        return _title_case_piece(bits[0], force=force)
    n = len(bits)
    return "-".join(
        _title_case_piece(bit, force=j == 0 or j == n - 1)
        for j, bit in enumerate(bits)
    )


def _title_case_piece(piece: str, *, force: bool) -> str:
    m = _LEAD_TRAIL.match(piece)
    if not m:
        return piece
    lead, core, trail = m.group(1), m.group(2), m.group(3)
    if not core:
        return piece
    low = core.lower()
    if not force and low in _TITLE_SMALL:
        return f"{lead}{low}{trail}"
    if len(core) == 2 and core.isalpha() and low not in _TITLE_SMALL:
        return f"{lead}{core.upper()}{trail}"
    return f"{lead}{_cap_apostrophe(core)}{trail}"


def _cap_apostrophe(core: str) -> str:
    chunks = re.split(r"(['’])", core)
    out: list[str] = []
    for i, chunk in enumerate(chunks):
        if not chunk or chunk in {"'", "’"}:
            out.append(chunk)
            continue
        if i > 0 and chunks[i - 1] in {"'", "’"} and len(chunk) == 1:
            out.append(chunk.lower())
            continue
        out.append(chunk[0].upper() + chunk[1:].lower())
    return "".join(out)


def title_looks_like_filename(title: str) -> bool:
    t = (title or "").strip()
    if not t:
        return False
    if _FILENAME_EXT.search(t):
        return True
    if _PATHY.search(t):
        return True
    return False


def title_has_markup(title: str) -> bool:
    if not title:
        return False
    if re.search(r"<[^>]+>", title):
        return True
    cleaned = strip_title_markup(title)
    return bool(cleaned) and cleaned != title.strip()


_NUMBERED_CITE = re.compile(r"^(?:\[\d+\]|\d+[.)])\s+")
_DOI_IN_TITLE = re.compile(r"doi\.org/|\bDOI:\s*10\.|\bPMID\b", re.I)
_VANCOUVER_YEAR = re.compile(r"\b(?:19|20)\d{2};\d")
_ET_AL_YEAR = re.compile(r"\bet al\.?\b", re.I)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_YEAR_PAREN = re.compile(r"\((?:[^)]*,\s*)?(?:19|20)\d{2}\)")
_SURNAME_INITIAL = re.compile(r"^[A-Z][\w'’\-]+,\s+[A-Z]\.")
_AUTHOR_YEAR = re.compile(
    r"^(?:[A-Z][\w'’\-.]+(?:\s+[A-Z][\w'’\-.]*){0,6})\s+\((?:19|20)\d{2}\)"
)
_INITIALS_THEN_YEAR = re.compile(r"^[A-Z][\w'’\-]+\s+[A-Z]\.(?:[A-Z]\.)?,")


def usable_work_title(value: object) -> bool:
    """True when this string is a work title, not a blank or a bibliography entry.

    Reference lists often store the whole citation (``[1] Author: "Title"``,
    ``Surname, I. (2014). Title. Journal``) in the title field. Those are not
    titles. A structured article title is.
    """
    text = strip_title_markup(str(value or ""))
    if not text or not re.search(r"[A-Za-z]", text):
        return False
    if _NUMBERED_CITE.match(text):
        return False
    if _DOI_IN_TITLE.search(text):
        return False
    if _VANCOUVER_YEAR.search(text):
        return False
    if _ET_AL_YEAR.search(text) and _YEAR.search(text):
        return False
    if _SURNAME_INITIAL.match(text) and text.count(",") >= 2:
        return False
    if _AUTHOR_YEAR.match(text):
        return False
    if _INITIALS_THEN_YEAR.match(text) and _YEAR_PAREN.search(text):
        return False
    if text.count(",") >= 3 and _YEAR_PAREN.search(text):
        return False
    return True


def lint_item(
    client: httpx.Client,
    cfg: Config,
    item: Item,
    *,
    backend: LibraryBackend | None = None,
    manifest: Manifest | None = None,
    cache: IdentifierCache | None = None,
) -> list[Finding]:
    notes = prepare_identifiers(
        client,
        item,
        email=cfg.email,
        min_score=cfg.crossref_min_score,
        suspect_score=cfg.doi_suspect_score,
        verify=cfg.verify_doi,
        cache=cache,
    )
    findings: list[Finding] = []
    scholarly = item.item_type in _SCHOLARLY

    def add(code: str, detail: str, pdf_doi: str | None = None) -> None:
        findings.append(
            Finding(
                itemKey=item.key,
                code=code,
                title=item.title,
                detail=detail,
                library_doi=item.library_doi,
                doi=item.doi,
                pdf_doi=pdf_doi,
            )
        )

    if item.doi_verified == "swapped":
        add(
            "swappable_doi",
            next(
                (n for n in notes if n.startswith("swap:")),
                "library DOI disagrees with title match",
            ),
        )
    elif item.doi_verified == "suspect":
        add(
            "suspect_doi",
            next(
                (n for n in notes if n.startswith("verify:")),
                "library DOI title mismatch",
            ),
        )
    elif scholarly and item.doi_verified == "missing" and not item.doi:
        add("missing_doi", "no DOI after prepare")
    if not item.doi and not item.arxiv_id and not item.pmid and not item.url:
        add("no_identifier", "no DOI, arXiv id, PMID or URL")
    if item.pmid and not item.doi and "pubmed:no-doi" in notes:
        add("pmid_no_doi", f"PMID {item.pmid} did not convert")

    if scholarly and not usable_work_title(item.title):
        add("title_unusable", "title is blank or a citation string, not the work title")
    elif scholarly and item.title:
        if title_has_markup(item.title):
            add("title_html", "title contains HTML markup or entities")
        if title_is_all_caps(item.title):
            add("title_all_caps", "title is mostly ALL CAPS")
        if title_looks_like_filename(item.title):
            add("title_filename", "title looks like a filename or path")

    pdf_path = resolve_pdf_path(cfg, item, manifest)
    if pdf_path is None and item.has_pdf and backend is not None:
        dest = cfg.pdf_cache_dir / f"{item.key}.pdf"
        pdf_path = backend.export_pdf(item, dest)
        if pdf_path:
            item.pdf_path = str(pdf_path)
    if pdf_path and pdf_path.is_file():
        pdf_doi = doi_from_pdf(pdf_path)
        if pdf_doi:
            lib = (item.library_doi or "").lower()
            working = (item.doi or "").lower()
            if pdf_doi != lib and pdf_doi != working:
                add("pdf_doi_mismatch", f"PDF DOI {pdf_doi}", pdf_doi=pdf_doi)
    from .llm_pdf_match import pdf_identity_finding

    extra = pdf_identity_finding(cfg, item, manifest, backend)
    if extra:
        findings.append(extra)
    return findings


def lint_items(
    client: httpx.Client,
    cfg: Config,
    items: list[Item],
    *,
    backend: LibraryBackend | None = None,
    manifest: Manifest | None = None,
) -> list[Finding]:
    cache = IdentifierCache()
    out: list[Finding] = []
    for item in items:
        out.extend(
            lint_item(
                client, cfg, item, backend=backend, manifest=manifest, cache=cache
            )
        )
    return out
