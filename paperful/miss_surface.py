"""Frozen miss-surface enum for operator-facing honesty (dry-run, gaps, handoff).

Rich detail stays on ``attempts[]``; this module projects a single code plus a
plain string. OA discovery sources stamp ``license`` / ``oa_status`` / ``version``
on candidates and ``record.json``; without those stamps when Unpaywall or
OpenAlex supplied them, do not claim ``import_ok``.
"""

from __future__ import annotations

import re
from typing import Any

from .runreport import item_miss_reason
from .store import (
    STATUS_ATTACHED,
    STATUS_NO_IDENTIFIER,
    STATUS_NOT_FOUND,
    STATUS_OK,
    STATUS_RETRYABLE,
)

MISS_SURFACE_CODES = frozenset(
    {
        "no_doi",
        "paywalled",
        "no_oa",
        "fetch_failed",
        "license_blocked",
        "import_ok",
        "snapshot",
    }
)

MISS_SURFACE_PLAIN: dict[str, str] = {
    "no_doi": "No DOI or identifier to search",
    "paywalled": "Paywalled or login required",
    "no_oa": "No open-access copy found",
    "fetch_failed": "Fetch failed or incomplete",
    "license_blocked": "Blocked by license policy",
    "import_ok": "PDF imported",
    "snapshot": "HTML page snapshot, not a publisher PDF",
}

_OA_DISCOVERY = frozenset(
    {
        "unpaywall",
        "openalex",
        "semanticscholar",
        "core",
        "openaire",
        "europepmc",
    }
)
_OA_STAMP_SOURCES = frozenset({"unpaywall", "openalex"})
_OA_NOT_FOUND_HINTS = (
    "no oa location",
    "oa landing, no pdf",
    "no pdf_url",
)
_PAYWALL_REASONS = frozenset(
    {"paywall", "login", "blocked", "cloudflare", "captcha"}
)
_ATTEMPT_OA_SOURCE = re.compile(
    r"^(unpaywall|openalex|semanticscholar|core|openaire|europepmc):"
)


def miss_surface_plain(code: str | None) -> str:
    if not code:
        return ""
    return MISS_SURFACE_PLAIN.get(code, code)


def oa_stamp_subset(
    stamp: dict[str, str] | None, fields: tuple[str, ...]
) -> dict[str, str]:
    if not stamp:
        return {}
    out: dict[str, str] = {}
    for key in fields:
        val = str(stamp.get(key) or "").strip()
        if val:
            out[key] = val
    return out


def license_blocked_by_policy(
    stamp: dict[str, str] | None, blocked_patterns: tuple[str, ...]
) -> bool:
    if not blocked_patterns or not stamp:
        return False
    lic = str(stamp.get("license") or "").lower()
    if not lic:
        return False
    return any(pat.strip().lower() in lic for pat in blocked_patterns if pat.strip())


def _has_searchable_id(
    *,
    doi: str | None,
    arxiv_id: str | None,
    url: str | None,
) -> bool:
    if (doi or "").strip():
        return True
    if (arxiv_id or "").strip():
        return True
    return bool((url or "").strip())


def _oa_sources_exhausted(attempts: list[str]) -> bool:
    tried: list[str] = []
    for entry in attempts:
        m = _ATTEMPT_OA_SOURCE.match(entry)
        if not m:
            continue
        name = m.group(1)
        rest = entry[len(name) + 1 :]
        if rest.startswith("skipped"):
            continue
        tried.append(entry)
    if not tried:
        return False
    return all(":not_found" in e or ":error" in e for e in tried)


def _oa_not_found_notes(attempts: list[str]) -> bool:
    for entry in attempts:
        if not _ATTEMPT_OA_SOURCE.match(entry):
            continue
        low = entry.lower()
        if any(h in low for h in _OA_NOT_FOUND_HINTS):
            return True
    return False


def miss_detail_from_attempts(attempts: list[str] | None) -> str:
    """Short human detail from ``attempts[]`` (last meaningful line)."""
    if not attempts:
        return ""
    for entry in reversed(attempts):
        if ":license_blocked" in entry:
            return entry.partition(":")[2] or entry
        if "download-failed" in entry:
            return entry
        if entry.endswith(")") and "(" in entry:
            return entry
    return str(attempts[-1])


def import_ok_honest(
    *,
    source: str | None,
    oa_stamp: dict[str, str] | None,
    stamp_fields: tuple[str, ...],
    supplied_stamp: dict[str, str] | None = None,
) -> bool:
    """True when a saved PDF may be labelled ``import_ok`` on the surface."""
    src = (source or "").strip().lower()
    if src not in _OA_STAMP_SOURCES:
        return True
    supplied = supplied_stamp if supplied_stamp is not None else (oa_stamp or {})
    if not any(str(supplied.get(field) or "").strip() for field in stamp_fields):
        return True
    for field in stamp_fields:
        if str(supplied.get(field) or "").strip() and not str(
            (oa_stamp or {}).get(field) or ""
        ).strip():
            return False
    return True


def project_miss_surface(
    *,
    doi: str | None = None,
    arxiv_id: str | None = None,
    url: str | None = None,
    has_pdf: bool = False,
    status: str = "",
    reason: str = "",
    attempts: list[str] | None = None,
    source: str | None = None,
    oa_stamp: dict[str, str] | None = None,
    stamp_fields: tuple[str, ...] = ("license", "oa_status", "version"),
    license_block_patterns: tuple[str, ...] = (),
) -> str:
    attempts = list(attempts or [])
    st = (status or "").strip().lower()
    if any(":license_blocked" in a for a in attempts) or reason == "license_blocked":
        return "license_blocked"
    if license_blocked_by_policy(oa_stamp, license_block_patterns) and st in {
        STATUS_OK,
        STATUS_ATTACHED,
        "",
    }:
        return "license_blocked"

    saved = has_pdf or st in {STATUS_OK, STATUS_ATTACHED}
    if saved and (source or "").strip().lower() == "htmlpdf":
        return "snapshot"
    if saved:
        if import_ok_honest(
            source=source,
            oa_stamp=oa_stamp,
            stamp_fields=stamp_fields,
        ):
            return "import_ok"
        return "fetch_failed"

    if st == STATUS_NO_IDENTIFIER or not _has_searchable_id(
        doi=doi, arxiv_id=arxiv_id, url=url
    ):
        return "no_doi"

    inner = item_miss_reason({"status": status, "attempts": attempts})
    if inner in _PAYWALL_REASONS:
        return "paywalled"
    if inner == "session_expired" and any(
        "ezproxy" in a or "campus" in a.lower() for a in attempts
    ):
        return "paywalled"

    if _oa_not_found_notes(attempts) or (
        st == STATUS_NOT_FOUND and _oa_sources_exhausted(attempts)
    ):
        return "no_oa"

    if st in {STATUS_RETRYABLE, "error", "captcha"} or inner in {
        "download_failed",
        "error",
        "paused",
        "step_budget",
    }:
        return "fetch_failed"

    if st == STATUS_NOT_FOUND:
        if any("ezproxy" in a for a in attempts):
            return "paywalled"
        if _oa_sources_exhausted(attempts):
            return "no_oa"
        return "no_oa"

    if not status and not attempts and not has_pdf:
        if not _has_searchable_id(doi=doi, arxiv_id=arxiv_id, url=url):
            return "no_doi"
        return ""

    if not _has_searchable_id(doi=doi, arxiv_id=arxiv_id, url=url):
        return "no_doi"
    return "fetch_failed"


def row_from_item(
    *,
    doi: str | None = None,
    arxiv_id: str | None = None,
    url: str | None = None,
    has_pdf: bool = False,
    status: str = "",
    reason: str = "",
    attempts: list[str] | None = None,
    source: str | None = None,
    oa_stamp: dict[str, str] | None = None,
    stamp_fields: tuple[str, ...] = ("license", "oa_status", "version"),
    license_block_patterns: tuple[str, ...] = (),
) -> dict[str, Any]:
    code = project_miss_surface(
        doi=doi,
        arxiv_id=arxiv_id,
        url=url,
        has_pdf=has_pdf,
        status=status,
        reason=reason,
        attempts=attempts,
        source=source,
        oa_stamp=oa_stamp,
        stamp_fields=stamp_fields,
        license_block_patterns=license_block_patterns,
    )
    stamp = oa_stamp_subset(oa_stamp, stamp_fields)
    return {
        "miss_surface": code or None,
        "miss_plain": miss_surface_plain(code) if code else "",
        "miss_detail": miss_detail_from_attempts(attempts),
        **{k: stamp.get(k, "") for k in ("oa_status", "license", "version")},
    }


def honesty_row_for_item(
    cfg: Any,
    item: Any,
    rec: Any | None = None,
) -> dict[str, Any]:
    """Project miss surface for a library item and optional manifest record."""
    stamp = oa_stamp_from_record(rec) if rec is not None else {}
    return row_from_item(
        doi=getattr(item, "doi", None),
        arxiv_id=getattr(item, "arxiv_id", None),
        url=(getattr(item, "url", None) or "") or (getattr(rec, "url", None) if rec else None),
        has_pdf=bool(getattr(item, "has_pdf", False)),
        status=str(getattr(rec, "status", "") or "") if rec else "",
        reason=str(getattr(rec, "reason", "") or "") if rec else "",
        attempts=list(getattr(rec, "attempts", None) or []) if rec else [],
        source=getattr(rec, "source", None) if rec else None,
        oa_stamp=stamp,
        stamp_fields=tuple(getattr(cfg, "oa_honesty_stamp_fields", ()) or ()),
        license_block_patterns=tuple(
            getattr(cfg, "oa_honesty_license_block", ()) or ()
        ),
    )


def oa_stamp_from_record(rec: Any) -> dict[str, str]:
    """Build stamp dict from a manifest ``Record`` or similar object."""
    out: dict[str, str] = {}
    for key in ("oa_license", "oa_status", "oa_version"):
        val = str(getattr(rec, key, "") or "").strip()
        if not val:
            continue
        out_key = "license" if key == "oa_license" else key.replace("oa_", "")
        out[out_key] = val
    return out
