"""ORCID public API: a person's own works (DOI list)."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import httpx

from ..resolve import normalize_doi
from .openalex import normalize_orcid

Getter = Callable[[str], dict[str, Any] | list[Any]]

_ORCID_RE = re.compile(
    r"^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$",
    re.IGNORECASE,
)


class OrcidError(RuntimeError):
    pass


def orcid_dois(orcid: str, *, getter: Getter | None = None) -> list[str]:
    """Return unique DOIs from the ORCID public works endpoint."""
    cleaned = normalize_orcid(orcid)
    if not cleaned or not _ORCID_RE.match(cleaned):
        raise OrcidError(f"Invalid ORCID iD: {orcid!r}")
    if getter is not None:
        payload = getter(cleaned)
    else:
        payload = _http_works(cleaned)
    return _dois_from_payload(payload)


def _http_works(orcid: str) -> dict[str, Any]:
    url = f"https://pub.orcid.org/v3.0/{orcid}/works"
    headers = {
        "Accept": "application/json",
        "User-Agent": "paperful-snowball/0.1",
    }
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
        if resp.status_code == 404:
            raise OrcidError(f"ORCID not found: {orcid}")
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise OrcidError("ORCID response was not an object")
        return data


def _dois_from_payload(payload: dict[str, Any] | list[Any]) -> list[str]:
    groups: list[Any]
    if isinstance(payload, list):
        groups = payload
    else:
        groups = list(payload.get("group") or [])
    seen: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        for summary in group.get("work-summary") or []:
            if not isinstance(summary, dict):
                continue
            for ext in (summary.get("external-ids") or {}).get("external-id") or []:
                if not isinstance(ext, dict):
                    continue
                if str(ext.get("external-id-type") or "").lower() != "doi":
                    continue
                value = ext.get("external-id-normalized") or ext.get("external-id-value") or ""
                if isinstance(value, dict):
                    value = value.get("value") or ""
                doi = normalize_doi(str(value))
                if doi and doi not in seen:
                    seen.append(doi)
    return seen
