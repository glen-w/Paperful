"""Rank OA locations and build honesty stamps from Unpaywall / OpenAlex payloads."""

from __future__ import annotations

from typing import Any


def _norm_license(loc: dict[str, Any]) -> str:
    lic = loc.get("license")
    if lic is None:
        return ""
    return str(lic).strip()


def _location_rank(loc: dict[str, Any], *, work_oa_status: str = "") -> tuple[int, int, int]:
    host = str(loc.get("host_type") or "").lower()
    version = str(loc.get("version") or "").lower()
    license = _norm_license(loc).lower()
    has_pdf = bool(loc.get("url_for_pdf") or loc.get("pdf_url"))
    repo = 1 if host == "repository" else 0
    licensed = 1 if license and "cc-" in license else 0
    bronze = 1 if (work_oa_status == "bronze" or version == "submittedversion") else 0
    return (1 if has_pdf else 0, repo + licensed, -bronze)


def rank_unpaywall_locations(data: dict[str, Any]) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    keys: set[str] = set()

    def add(loc: dict[str, Any] | None) -> None:
        if not loc:
            return
        key = str(loc.get("url_for_pdf") or loc.get("url") or loc.get("url_for_landing_page"))
        if key in keys:
            return
        keys.add(key)
        seen.append(loc)

    add(data.get("best_oa_location"))
    for loc in data.get("oa_locations") or []:
        add(loc)
    oa_status = str(data.get("oa_status") or "")
    return sorted(
        seen,
        key=lambda loc: _location_rank(loc, work_oa_status=oa_status),
        reverse=True,
    )


def rank_openalex_locations(data: dict[str, Any]) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    keys: set[str] = set()

    def add(loc: dict[str, Any] | None) -> None:
        if not loc:
            return
        key = str(loc.get("pdf_url") or loc.get("landing_page_url") or "")
        if key in keys:
            return
        keys.add(key)
        seen.append(loc)

    add(data.get("best_oa_location"))
    for loc in data.get("locations") or []:
        add(loc)
    oa_status = str(data.get("open_access", {}).get("oa_status") or "")
    return sorted(
        seen,
        key=lambda loc: _location_rank(loc, work_oa_status=oa_status),
        reverse=True,
    )


def stamp_from_unpaywall(data: dict[str, Any], loc: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    lic = _norm_license(loc)
    if lic:
        out["license"] = lic
    oa_status = str(data.get("oa_status") or "").strip()
    if oa_status:
        out["oa_status"] = oa_status
    version = str(loc.get("version") or "").strip()
    if version:
        out["version"] = version
    return out


def stamp_from_openalex(data: dict[str, Any], loc: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    lic = _norm_license(loc)
    if lic:
        out["license"] = lic
    oa = data.get("open_access") or {}
    oa_status = str(oa.get("oa_status") or "").strip()
    if oa_status:
        out["oa_status"] = oa_status
    version = str(loc.get("version") or "").strip()
    if version:
        out["version"] = version
    return out


def apply_stamp_fields(
    stamp: dict[str, str], fields: tuple[str, ...]
) -> dict[str, str]:
    return {k: v for k, v in stamp.items() if k in fields and v}
