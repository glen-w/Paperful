"""Shared regexes and helpers for critique checkers."""

from __future__ import annotations

import re

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
_PASSIVE = re.compile(r"\b(was|were|is|are|be|been|being)\s+\w+(?:ed|en)\b", re.I)


def _quote(text: str, limit: int = 180) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())[:limit]


def _split_body_biblio(text: str) -> tuple[str, str]:
    from ..snowball.bibliography import _REF_HEADING

    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        if _REF_HEADING.match(line.strip()):
            return "\n".join(lines[:i]), "\n".join(lines[i:])
    # last 20% as a fallback bibliography window
    if len(text) > 2000:
        cut = int(len(text) * 0.75)
        return text[:cut], text[cut:]
    return text, ""
