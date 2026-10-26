"""Deterministic checkers for ``paperful critique``."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from .config import Config
from .critique import Finding, make_finding
from .critique_extract import ExtractedDoc, loc_for, loc_of_span
from .critique_overlap import OverlapHit, overlap_findings
from .critique_stats import scan_stats
from .identity import LibraryFingerprint
from .refs_gap import aggregate_citations
from .resolve import DOI_RE, normalize_doi
from .snowball.bibliography import parse_bibliography_entries
from .zot import Item

_FIG_CAPTION = re.compile(
    r"(?im)^\s*(?:fig(?:ure)?|table|eq(?:uation)?)\s*\.?\s*(\d+[a-z]?)\b"
)
_FIG_MENTION = re.compile(
    r"\b(?:[Ff]ig(?:ure)?|[Tt]able|[Ee]q(?:uation)?)\s*\.?\s*(\d+[a-z]?)\b"
)
_NUM_CITE = re.compile(r"\[(\d+(?:\s*[-–,]\s*\d+)*)\]")
_AUTHOR_YEAR = re.compile(
    r"\(([A-Z][A-Za-z'-]+(?:\s+(?:and|&)\s+[A-Z][A-Za-z'-]+)?(?:\s+et\s+al\.?)?),\s*(\d{4}[a-z]?)\)"
)
_EXPANSION = re.compile(
    r"\b([A-Z][A-Za-z0-9][A-Za-z0-9 -]{2,80})\s+\(([A-Z]{2,12})\)"
    r"|\b([A-Z]{2,12})\s+\(([A-Z][A-Za-z0-9][A-Za-z0-9 -]{2,80})\)"
)
_ACRONYM = re.compile(r"\b[A-Z]{2,10}\b")
_SKIP_ACRONYM = frozenset(
    {
        "CI",
        "SD",
        "SE",
        "OR",
        "RR",
        "HR",
        "US",
        "UK",
        "EU",
        "UN",
        "WHO",
        "DOI",
        "URL",
        "PDF",
        "HTML",
        "HTTP",
        "JSON",
        "XML",
        "CSV",
        "ANOVA",
        "DNA",
        "RNA",
        "PCR",
        "HIV",
        "AI",
        "ML",
        "GPU",
        "CPU",
        "ID",
        "IQ",
        "OK",
        "TV",
        "AM",
        "PM",
        "KG",
        "KM",
        "MG",
        "ML",
        "MS",
        "HZ",
        "NM",
        "PH",
    }
)
_NUM = re.compile(r"(?<![A-Za-z0-9./-])(\d+\.\d+|\d{3,})(?![A-Za-z0-9./-])")
_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_MENTIONS = {
    "limitations": re.compile(r"\blimitations?\b", re.I),
    "data_availability": re.compile(
        r"\bdata availability\b|\bopen data\b|\bdata (?:are|is) available\b", re.I
    ),
    "funding": re.compile(r"\bfunding\b|\bthis work was supported\b|\bgrant\b", re.I),
    "ethics": re.compile(
        r"\bethics\b|\bIRB\b|\binstitutional review board\b|\binformed consent\b",
        re.I,
    ),
    "conflict": re.compile(r"\bconflict of interest\b|\bcompeting interests?\b", re.I),
}
_REPO_URL = re.compile(
    r"https?://(?:github\.com|gitlab\.com|zenodo\.org|osf\.io|huggingface\.co|"
    r"figshare\.com|dataverse\.[^\s/]+)/[^\s)>\]]+",
    re.I,
)
_URL = re.compile(r"https?://[^\s)>\]]+", re.I)
_PRISMA_HINT = re.compile(
    r"\bsystematic review\b|\bmeta-?analysis\b|\bPRISMA\b|\binclusion criteria\b",
    re.I,
)
_CONSORT_HINT = re.compile(
    r"\brandomi[sz]ed\b|\btrial\b|\bCONSORT\b|\bplacebo\b|\ballocat",
    re.I,
)
_PRISMA_WORD = re.compile(r"\bPRISMA\b")
_CONSORT_WORD = re.compile(r"\bCONSORT\b")
_HEDGE = re.compile(
    r"\b(?:may|might|could|seems?|appear(?:s|ed)?|possibly|perhaps|likely|suggests?)\b",
    re.I,
)
_SENTENCE = re.compile(r"[^.!?]+[.!?]")
_PASSIVE = re.compile(
    r"\b(was|were|is|are|be|been|being)\s+\w+(?:ed|en)\b", re.I
)


def run_checks(
    cfg: Config,
    doc: ExtractedDoc,
    *,
    item: Item | None,
    collections: list[str],
    library: bool,
    offline: bool,
    client: httpx.Client | None,
    backend: Any | None,
    scope_items: list[Item],
    force: bool,
    on_status: Callable[[str], None] | None = None,
) -> tuple[list[Finding], list[dict[str, Any]], list[str]]:
    findings: list[Finding] = []
    sections_used: list[str] = []
    say = on_status or (lambda _msg: None)

    say("Checkers: file health and structure")
    findings.extend(_file_health(doc))
    if doc.finding in {"no_file", "unsupported", "empty_extract", "needs_ocr"} and not doc.text.strip():
        return findings, [], sections_used

    findings.extend(_structure(cfg, doc, sections_used))
    say("Checkers: bibliography")
    findings.extend(
        _bibliography_and_cites(
            cfg, doc, item, scope_items, offline, client, on_status=on_status
        )
    )
    say("Checkers: floats, acronyms, stats, prose")
    findings.extend(_floats(doc))
    findings.extend(_acronyms(doc))
    findings.extend(_abstract_numbers(doc))
    findings.extend(_mentions_and_urls(doc))
    findings.extend(_checklists(doc, item))
    findings.extend(_stats(doc))
    findings.extend(_prose(doc))
    findings.extend(_style_metrics(doc))

    if item is not None:
        say("Checkers: identity and integrity")
        findings.extend(_identity(cfg, item, client, backend, offline))
        findings.extend(_integrity_item(cfg, item, client, backend, offline, doc))

    n_scope = len(scope_items)
    if n_scope:
        say(f"Library overlap vs {n_scope} scoped item(s)…")
    else:
        say("Library overlap (corpus on disk)…")
    overlap_rows: list[dict[str, Any]] = []
    findings.extend(_overlap(cfg, doc, item, scope_items, overlap_rows))
    return findings, overlap_rows, sections_used


def _quote(text: str, limit: int = 180) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())[:limit]


def _file_health(doc: ExtractedDoc) -> list[Finding]:
    out: list[Finding] = []
    if doc.finding == "no_file":
        out.append(
            make_finding(
                code="no_file",
                severity="major",
                detail="No file on disk to extract.",
                source="rule",
            )
        )
        return out
    if doc.finding == "unsupported":
        out.append(
            make_finding(
                code="unsupported_format",
                severity="major",
                detail=f"Unsupported format {doc.format!r}. Use pdf, txt, md, html, rtf, docx, odt, pptx.",
                source="rule",
            )
        )
        return out
    if doc.finding == "needs_ocr":
        out.append(
            make_finding(
                code="needs_ocr",
                severity="warn",
                detail="PDF text layer is too thin to check. Run paperful ocr or paste a text export.",
                source="rule",
            )
        )
    elif doc.finding == "empty_extract":
        detail = "Extracted too little text to check."
        if doc.error:
            detail = f"{detail} {doc.error}"
        out.append(
            make_finding(
                code="empty_extract",
                severity="warn",
                detail=detail,
                source="rule",
            )
        )
    if doc.format != "pdf":
        out.append(
            make_finding(
                code="skipped_not_pdf",
                severity="info",
                detail="PDF-only probes (short-PDF, page geometry) skipped.",
                source="rule",
            )
        )
    elif doc.pdf_pages == 1 and doc.pdf_words < 200:
        out.append(
            make_finding(
                code="short_pdf",
                severity="info",
                detail=f"One-page PDF ({doc.pdf_words} first-page words).",
                loc="p. 1",
                source="rule",
            )
        )
    return out


def _structure(cfg: Config, doc: ExtractedDoc, sections_used: list[str]) -> list[Finding]:
    from .sections.extract import split_sections

    pages = doc.pages or [doc.text]
    slices = split_sections(pages, cfg)
    have: set[str] = set()
    for sl in slices:
        label = sl.canonical or sl.heading or ""
        if label:
            sections_used.append(label)
        if sl.canonical:
            have.add(sl.canonical)
    out: list[Finding] = []
    for name in ("methodology", "results", "limitations", "related_work"):
        if name in have:
            continue
        out.append(
            make_finding(
                code="missing_section",
                severity="info",
                detail=f"No extractable {name.replace('_', ' ')} section.",
                source="rule",
                extra={"section": name},
            )
        )
    return out


def _identity(
    cfg: Config,
    item: Item,
    client: httpx.Client | None,
    backend: Any,
    offline: bool,
) -> list[Finding]:
    if offline or client is None:
        return [
            make_finding(
                code="identity_skipped_offline",
                severity="info",
                detail="Identity lint skipped (offline / no HTTP client).",
                source="rule",
            )
        ]
    from .lint import lint_item
    from .store import Manifest

    try:
        rows = lint_item(
            client,
            cfg,
            item,
            backend=backend,
            manifest=Manifest(cfg.manifest_path),
        )
    except Exception:
        return []
    out: list[Finding] = []
    for row in rows:
        sev = "warn" if row.code in {"pdf_doi_mismatch", "pdf_identity_mismatch"} else "info"
        out.append(
            make_finding(
                code=row.code,
                severity=sev,
                detail=row.detail,
                source="rule",
            )
        )
    return out


def _integrity_item(
    cfg: Config,
    item: Item,
    client: httpx.Client | None,
    backend: Any,
    offline: bool,
    doc: ExtractedDoc,
) -> list[Finding]:
    if offline or client is None:
        return []
    from .screen import FINGERPRINT_FAMILIES, load_fingerprints, scan_text_fingerprints, screen_item
    from .store import Manifest

    try:
        rows = screen_item(
            client,
            cfg,
            item,
            backend=backend,
            manifest=Manifest(cfg.manifest_path),
        )
    except Exception:
        rows = []
    out: list[Finding] = []
    for row in rows:
        out.append(
            make_finding(
                code=f"pps_{row.code}",
                severity="warn" if row.code in {"retracted", "withdrawn"} else "info",
                detail=row.detail,
                quote=" ".join(row.evidence[:2]),
                source="pps",
            )
        )
    if not rows and doc.text.strip():
        try:
            for family in FINGERPRINT_FAMILIES:
                fps = load_fingerprints(client, cfg, family, refresh=False)
                hits = scan_text_fingerprints(
                    doc.text, fps, family=family, tortured_min=cfg.screen_tortured_min
                )
                if hits:
                    out.append(
                        make_finding(
                            code=f"pps_{family}",
                            severity="info",
                            detail=f"{len(hits)} fingerprint hit(s) (flags to review).",
                            quote=hits[0],
                            source="pps",
                        )
                    )
        except Exception:
            pass
    return out


def _split_body_biblio(text: str) -> tuple[str, str]:
    from .snowball.bibliography import _REF_HEADING

    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        if _REF_HEADING.match(line.strip()):
            return "\n".join(lines[:i]), "\n".join(lines[i:])
    # last 20% as a fallback bibliography window
    if len(text) > 2000:
        cut = int(len(text) * 0.75)
        return text[:cut], text[cut:]
    return text, ""


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
            entries.append({"doi": doi, "title": "", "year": None, "raw": match.group(0)})

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
            _cited_work_status(
                cfg, client, dois, entries, item, on_status=on_status
            )
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
    from .screen import lookup_doi_status

    say = on_status or (lambda _msg: None)
    out: list[Finding] = []
    authors = [s.lower() for s in (getattr(item, "creator_surnames", None) or [])] if item else []
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


def _float_kind(word: str) -> str:
    w = (word or "").lower().rstrip(".")
    if w.startswith("fig"):
        return "fig"
    if w.startswith("tab"):
        return "tab"
    if w.startswith("eq"):
        return "eq"
    return w[:3]


def _floats(doc: ExtractedDoc) -> list[Finding]:
    captions: dict[str, str] = {}
    mentions: dict[str, str] = {}
    chunks = doc.pages or doc.paragraphs or [doc.text]
    for i, chunk in enumerate(chunks):
        loc = loc_for(doc, i)
        for m in _FIG_CAPTION.finditer(chunk):
            key = _float_kind(m.group(0).split()[0]) + m.group(1).lower()
            captions[key] = loc or chunk[:40]
        for m in _FIG_MENTION.finditer(chunk):
            key = _float_kind(m.group(0).split()[0]) + m.group(1).lower()
            line_start = chunk.rfind("\n", 0, m.start()) + 1
            prefix = chunk[line_start : m.start()]
            if not prefix.strip() and _FIG_CAPTION.match(chunk[line_start:]):
                continue
            mentions.setdefault(key, loc)
    out: list[Finding] = []
    for key, loc in captions.items():
        if key not in mentions:
            out.append(
                make_finding(
                    code="caption_not_referenced",
                    severity="info",
                    loc=loc,
                    detail=f"Caption {key} has no in-text mention.",
                    source="rule",
                )
            )
    for key, loc in mentions.items():
        if key not in captions:
            out.append(
                make_finding(
                    code="mention_without_caption",
                    severity="info",
                    loc=loc,
                    detail=f"In-text {key} has no matching caption line.",
                    source="rule",
                )
            )
    return out


def _acronyms(doc: ExtractedDoc) -> list[Finding]:
    body, _biblio = _split_body_biblio(doc.text)
    defined_at: dict[str, int] = {}
    for m in _EXPANSION.finditer(body):
        token = (m.group(2) or m.group(3) or "").upper()
        if token and token not in defined_at:
            defined_at[token] = m.start()
    seen: set[str] = set()
    out: list[Finding] = []
    for m in _ACRONYM.finditer(body):
        token = m.group(0)
        if token in _SKIP_ACRONYM or token in seen:
            continue
        first_def = defined_at.get(token)
        if first_def is not None and first_def <= m.start():
            continue
        line_start = body.rfind("\n", 0, m.start()) + 1
        line_end = body.find("\n", m.end())
        line = body[line_start : line_end if line_end != -1 else None]
        if line.strip() == token or (line.isupper() and len(line.split()) <= 8):
            continue
        seen.add(token)
        snippet = body[max(0, m.start() - 20) : m.end() + 40]
        out.append(
            make_finding(
                code="acronym_undefined",
                severity="info",
                loc=loc_of_span(doc, snippet),
                quote=snippet,
                detail=f"{token} appears before an expansion (Full Name ({token})).",
                source="rule",
            )
        )
        if len(out) >= 25:
            break
    return out


def _abstract_numbers(doc: ExtractedDoc) -> list[Finding]:
    pages = doc.pages or [doc.text]
    abstract = pages[0]
    if len(pages) > 1:
        body = "\n".join(pages[1:])
    else:
        body, _ = _split_body_biblio(doc.text)
        # drop first 800 chars as abstract-ish
        abstract = body[:1200]
        body = body[1200:]
    body_fold = re.sub(r"\s+", " ", body)
    out: list[Finding] = []
    seen: set[str] = set()
    for m in _NUM.finditer(abstract):
        token = m.group(1)
        if token in seen or _YEAR.match(token):
            continue
        seen.add(token)
        if token not in body_fold:
            out.append(
                make_finding(
                    code="abstract_number_missing",
                    severity="info",
                    loc=loc_of_span(doc, abstract[:80]),
                    quote=abstract[max(0, m.start() - 30) : m.end() + 30],
                    detail=f"Number {token} in the opening/abstract is not repeated in the body.",
                    source="rule",
                )
            )
        if len(out) >= 12:
            break
    return out


def _mentions_and_urls(doc: ExtractedDoc) -> list[Finding]:
    out: list[Finding] = []
    text = doc.text
    for code, rx in _MENTIONS.items():
        if not rx.search(text):
            out.append(
                make_finding(
                    code="missing_mention",
                    severity="info",
                    detail=f"No mention of {code.replace('_', ' ')}.",
                    source="rule",
                    extra={"mention": code},
                )
            )
    if not _REPO_URL.search(text):
        out.append(
            make_finding(
                code="missing_mention",
                severity="info",
                detail="No GitHub/Zenodo/OSF/Hugging Face data or code URL.",
                source="rule",
                extra={"mention": "code_or_data_url"},
            )
        )
    for m in _URL.finditer(text):
        url = m.group(0).rstrip(".,;:")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or "." not in parsed.netloc:
            out.append(
                make_finding(
                    code="malformed_url",
                    severity="warn",
                    loc=loc_of_span(doc, url),
                    quote=url,
                    detail="URL looks malformed.",
                    source="rule",
                )
            )
    return out


def _checklists(doc: ExtractedDoc, item: Item | None) -> list[Finding]:
    text = doc.text
    out: list[Finding] = []
    if _PRISMA_HINT.search(text) and not _PRISMA_WORD.search(text):
        out.append(
            make_finding(
                code="checklist_prisma",
                severity="info",
                detail="Text looks like a systematic review / meta-analysis but does not mention PRISMA.",
                source="rule",
            )
        )
    if _CONSORT_HINT.search(text) and not _CONSORT_WORD.search(text):
        out.append(
            make_finding(
                code="checklist_consort",
                severity="info",
                detail="Text looks like a trial but does not mention CONSORT.",
                source="rule",
            )
        )
    return out


def _stats(doc: ExtractedDoc) -> list[Finding]:
    out: list[Finding] = []
    for hit in scan_stats(doc.text):
        if hit.kind == "grim" and not hit.consistent:
            out.append(
                make_finding(
                    code="grim_impossible_mean",
                    severity="warn",
                    loc=loc_of_span(doc, hit.quote),
                    quote=hit.quote,
                    detail=hit.detail,
                    source="rule",
                )
            )
        elif hit.kind in {"t", "F", "chi2", "z"} and not hit.consistent:
            out.append(
                make_finding(
                    code="statcheck_p_mismatch",
                    severity="warn",
                    loc=loc_of_span(doc, hit.quote),
                    quote=hit.quote,
                    detail=hit.detail,
                    source="rule",
                )
            )
        elif hit.kind == "p_no_n":
            out.append(
                make_finding(
                    code="p_without_n",
                    severity="info",
                    loc=loc_of_span(doc, hit.quote),
                    quote=hit.quote,
                    detail=hit.detail,
                    source="rule",
                )
            )
    return out


def _fmt_metric(value: Any, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _style_metrics(doc: ExtractedDoc) -> list[Finding]:
    """Readability / lexical summaries plus suggested AI-prose tells."""
    from .critique_ai_tells import MAX_PHRASE_FINDINGS, MIN_AI_TELL_WORDS, compute_ai_tells
    from .critique_metrics import compute_style_metrics

    text = doc.text or ""
    metrics = compute_style_metrics(text)
    tells = compute_ai_tells(text, doc.paragraphs or None)
    out: list[Finding] = []
    read = metrics.get("readability") or {}
    if not read.get("insufficient"):
        out.append(
            make_finding(
                code="readability_summary",
                severity="info",
                loc="document",
                detail=(
                    f"Flesch {_fmt_metric(read.get('flesch_reading_ease'))}; "
                    f"Gunning Fog {_fmt_metric(read.get('gunning_fog'))}; "
                    f"ARI {_fmt_metric(read.get('ari'))}. "
                    "Academic FRE is often 0–30; that is expected, not a defect."
                ),
                source="readability",
            )
        )
    lex = metrics.get("lexical_diversity") or {}
    mtld = lex.get("mtld")
    mtld_bit = (
        f"MTLD {_fmt_metric(mtld, 1)}" if mtld is not None else "MTLD omitted (<50 tokens)"
    )
    if lex.get("token_count"):
        out.append(
            make_finding(
                code="lexical_diversity_summary",
                severity="info",
                loc="document",
                detail=(
                    f"TTR {_fmt_metric(lex.get('ttr'), 3)}; {mtld_bit}; "
                    f"hapax rate {_fmt_metric(lex.get('hapax_rate'), 3)} "
                    f"({lex.get('type_count')} types / {lex.get('token_count')} tokens)."
                ),
                source="lexical_diversity",
            )
        )
    if tells.get("abstain"):
        out.append(
            make_finding(
                code="ai_tells_abstain",
                severity="info",
                lane="suggested",
                loc="document",
                detail=(
                    f"Fewer than {MIN_AI_TELL_WORDS} words; "
                    "heuristic AI-prose signals skipped."
                ),
                source="ai_tells",
            )
        )
        return out
    cv = tells.get("burstiness_cv")
    out.append(
        make_finding(
            code="ai_tell_summary",
            severity="info",
            lane="suggested",
            loc="document",
            detail=(
                f"Burstiness CV {_fmt_metric(cv, 2)}; "
                f"{tells.get('tell_phrase_total', 0)} tell-phrase hits "
                f"({len(tells.get('tell_phrase_hits') or [])} distinctive). "
                "Not proof of AI authorship."
            ),
            source="ai_tells",
        )
    )
    for hit in (tells.get("tell_phrase_hits") or [])[:MAX_PHRASE_FINDINGS]:
        phrase = str(hit.get("phrase") or "")
        count = hit.get("count") or 0
        out.append(
            make_finding(
                code="ai_tell",
                severity="info",
                lane="suggested",
                loc="prose",
                quote=phrase,
                detail=(
                    f"Stock phrase {phrase!r} ×{count}. Associated with some "
                    "LLM-style prose; not proof of AI."
                ),
                source="ai_tells",
            )
        )
    for flag in tells.get("unicode_flags") or []:
        out.append(
            make_finding(
                code="ai_tell",
                severity="info",
                lane="suggested",
                loc="unicode",
                quote=str(flag),
                detail=f"Typography flag {flag}. Provenance hint, not authorship proof.",
                source="ai_tells",
            )
        )
    for flag in tells.get("discourse") or []:
        out.append(
            make_finding(
                code="ai_tell",
                severity="info",
                lane="suggested",
                loc="discourse",
                quote=str(flag),
                detail=f"Discourse scaffold {flag}. Not proof of AI authorship.",
                source="ai_tells",
            )
        )
    return out


def _prose(doc: ExtractedDoc) -> list[Finding]:
    sentences = [s.strip() for s in _SENTENCE.findall(doc.text) if s.strip()]
    if not sentences:
        return []
    long = [s for s in sentences if len(s.split()) >= 40]
    hedges = list(_HEDGE.finditer(doc.text))
    passive = list(_PASSIVE.finditer(doc.text))
    words = len(doc.text.split())
    out: list[Finding] = []
    if long:
        out.append(
            make_finding(
                code="long_sentence",
                severity="info",
                loc=loc_of_span(doc, long[0][:80]),
                quote=long[0],
                detail=f"{len(long)} sentence(s) with ≥40 words.",
                source="rule",
            )
        )
    if hedges:
        density = len(hedges) / max(1, words) * 1000
        if density >= 12:
            out.append(
                make_finding(
                    code="hedge_words",
                    severity="info",
                    loc=loc_of_span(doc, hedges[0].group(0)),
                    quote=hedges[0].group(0),
                    detail=f"{len(hedges)} hedge-word hits ({density:.1f} per 1000 words).",
                    source="rule",
                )
            )
    if passive:
        out.append(
            make_finding(
                code="passive_voice",
                severity="info",
                loc=loc_of_span(doc, passive[0].group(0)),
                quote=passive[0].group(0),
                detail=f"{len(passive)} passive-voice hotspot(s) (heuristic).",
                source="rule",
            )
        )
    return out


def _overlap(
    cfg: Config,
    doc: ExtractedDoc,
    item: Item | None,
    scope_items: list[Item],
    overlap_rows: list[dict[str, Any]],
) -> list[Finding]:
    exclude = item.key if item is not None else ""
    keys = [it.key for it in scope_items] if scope_items else None
    hits, skip = overlap_findings(cfg, doc, exclude_key=exclude, scope_keys=keys)
    if skip:
        return [
            make_finding(
                code=skip,
                severity="info",
                detail="No extracted library text on disk (state/rag/text/). Overlap checker skipped.",
                source="phrase",
            )
        ]
    for h in hits:
        overlap_rows.append(
            {
                "other_key": h.other_key,
                "ngram": h.ngram,
                "n_words": h.n_words,
                "source": h.source,
                "other_loc": h.other_loc,
            }
        )
    by_other: dict[str, list[OverlapHit]] = {}
    for h in hits:
        by_other.setdefault(h.other_key, []).append(h)
    out: list[Finding] = []
    for other, group in by_other.items():
        long = any(h.n_words >= 20 for h in group)
        sev = "warn" if long or len(group) >= 3 else "info"
        sample = group[0]
        out.append(
            make_finding(
                code="text_overlap",
                severity=sev,
                loc=loc_of_span(doc, sample.ngram),
                quote=sample.ngram,
                detail=(
                    f"{len(group)} distinctive span(s) also in library item {other} "
                    f"(flags to review)."
                ),
                source=sample.source,
                extra={"other_key": other},
            )
        )
    return out
