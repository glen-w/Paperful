"""OpenAIRE Graph: repository copies by DOI.

Catches green OA (HAL, Zenodo, institutional repositories) that a
publisher-centric location list can miss. No API key.
"""

from __future__ import annotations

from ..zot import Item
from .base import Candidate, Context, Outcome, http_json
from .landing import looks_like_pdf_url

NAME = "openaire"
_API = "https://api.openaire.eu/graph/v3/research-products"
_CLOSED = {"CLOSED", "RESTRICTED", "EMBARGOED", "EMBARGO"}
_REPO_HOSTS = (
    "zenodo.org",
    "hal.science",
    "hal.archives-ouvertes.fr",
    "osf.io",
    "arxiv.org",
)


def find(item: Item, ctx: Context) -> Candidate:
    if not item.doi:
        return Candidate.miss(NAME, Outcome.SKIPPED, "no DOI")
    data = http_json(ctx, _API, params={"pid": item.doi, "pageSize": "5"})
    if not data:
        return Candidate.miss(NAME, Outcome.NOT_FOUND)
    urls = _pdf_urls(data)
    if not urls:
        return Candidate.miss(NAME, Outcome.NOT_FOUND, "no repository PDF")
    return Candidate(url=urls[0], source=NAME, alternates=urls[1:], note="repository")


def _pdf_urls(payload: dict) -> list[str]:
    results = payload.get("results") or payload.get("result") or []
    if isinstance(results, dict):
        results = [results]
    pdfs: list[str] = []
    other: list[str] = []
    for product in results:
        if not isinstance(product, dict):
            continue
        for inst in product.get("instances") or []:
            if not isinstance(inst, dict):
                continue
            if _closed(inst):
                continue
            for url in _instance_urls(inst):
                if not _wanted(url):
                    continue
                bucket = pdfs if _direct_pdf(url) else other
                if url not in bucket and url not in pdfs:
                    bucket.append(url)
    return pdfs + other


def _closed(inst: dict) -> bool:
    access = inst.get("accessright") or inst.get("accessRight") or ""
    if isinstance(access, dict):
        code = str(access.get("code") or access.get("label") or "")
    else:
        code = str(access)
    return code.strip().upper() in _CLOSED


def _instance_urls(inst: dict) -> list[str]:
    raw = inst.get("urls") or inst.get("url") or []
    if isinstance(raw, str):
        raw = [raw]
    found: list[str] = []
    for entry in raw:
        if isinstance(entry, dict):
            url = str(entry.get("url") or entry.get("href") or "")
        else:
            url = str(entry or "")
        url = url.strip()
        if url.startswith(("http://", "https://")) and url not in found:
            found.append(url)
    return found


def _direct_pdf(url: str) -> bool:
    low = url.lower()
    return looks_like_pdf_url(url) or "pdf=render" in low or low.split("?")[0].endswith(".pdf")


def _wanted(url: str) -> bool:
    if _direct_pdf(url):
        return True
    low = url.lower()
    if any(host in low for host in _REPO_HOSTS):
        return True
    return any(token in low for token in ("/bitstream/", "/download", "pdf"))
