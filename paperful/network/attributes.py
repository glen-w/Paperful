"""OpenAlex-seeded node attributes plus an editable CSV overlay."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

ATTRIBUTE_FIELDS = (
    "id",
    "display_name",
    "orcid",
    "openalex",
    "country",
    "region",
    "discipline",
    "sector",
    "career_stage",
)

# Compact UN M49-style region for country codes we see in ocean-governance work.
_REGION = {
    "US": "Northern America",
    "CA": "Northern America",
    "MX": "Latin America",
    "GT": "Latin America",
    "CR": "Latin America",
    "PA": "Latin America",
    "CO": "Latin America",
    "VE": "Latin America",
    "EC": "Latin America",
    "PE": "Latin America",
    "BR": "Latin America",
    "CL": "Latin America",
    "AR": "Latin America",
    "UY": "Latin America",
    "CU": "Latin America",
    "JM": "Latin America",
    "TT": "Latin America",
    "GB": "Europe",
    "IE": "Europe",
    "FR": "Europe",
    "DE": "Europe",
    "NL": "Europe",
    "BE": "Europe",
    "LU": "Europe",
    "CH": "Europe",
    "AT": "Europe",
    "IT": "Europe",
    "ES": "Europe",
    "PT": "Europe",
    "NO": "Europe",
    "SE": "Europe",
    "DK": "Europe",
    "FI": "Europe",
    "IS": "Europe",
    "PL": "Europe",
    "CZ": "Europe",
    "GR": "Europe",
    "TR": "Europe",
    "RU": "Europe",
    "UA": "Europe",
    "EE": "Europe",
    "LV": "Europe",
    "LT": "Europe",
    "RO": "Europe",
    "BG": "Europe",
    "HR": "Europe",
    "SI": "Europe",
    "SK": "Europe",
    "HU": "Europe",
    "RS": "Europe",
    "CN": "Asia",
    "JP": "Asia",
    "KR": "Asia",
    "TW": "Asia",
    "IN": "Asia",
    "PK": "Asia",
    "BD": "Asia",
    "LK": "Asia",
    "NP": "Asia",
    "SG": "Asia",
    "MY": "Asia",
    "ID": "Asia",
    "TH": "Asia",
    "VN": "Asia",
    "PH": "Asia",
    "KH": "Asia",
    "MM": "Asia",
    "SA": "Asia",
    "AE": "Asia",
    "IL": "Asia",
    "IR": "Asia",
    "IQ": "Asia",
    "JO": "Asia",
    "LB": "Asia",
    "QA": "Asia",
    "KW": "Asia",
    "AU": "Oceania",
    "NZ": "Oceania",
    "FJ": "Oceania",
    "PG": "Oceania",
    "WS": "Oceania",
    "TO": "Oceania",
    "SB": "Oceania",
    "VU": "Oceania",
    "KI": "Oceania",
    "MH": "Oceania",
    "FM": "Oceania",
    "PW": "Oceania",
    "NR": "Oceania",
    "TV": "Oceania",
    "CK": "Oceania",
    "ZA": "Africa",
    "NA": "Africa",
    "BW": "Africa",
    "ZW": "Africa",
    "MZ": "Africa",
    "AO": "Africa",
    "KE": "Africa",
    "TZ": "Africa",
    "UG": "Africa",
    "ET": "Africa",
    "NG": "Africa",
    "GH": "Africa",
    "SN": "Africa",
    "CI": "Africa",
    "CM": "Africa",
    "EG": "Africa",
    "MA": "Africa",
    "TN": "Africa",
    "DZ": "Africa",
    "MU": "Africa",
    "SC": "Africa",
    "MG": "Africa",
}


def region_for_country(country: str) -> str:
    code = (country or "").strip().upper()
    if not code:
        return ""
    return _REGION.get(code, "unknown")


def career_stage(first_year: int | None, last_year: int | None) -> str:
    if first_year is None or last_year is None:
        return ""
    span = max(0, last_year - first_year)
    if span < 5:
        return "early"
    if span < 15:
        return "mid"
    return "senior"


def seed_attributes(graph: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for node in graph.get("nodes") or []:
        country = str(node.get("country") or "")
        first = node.get("first_year")
        last = node.get("last_year")
        rows.append(
            {
                "id": str(node.get("id") or ""),
                "display_name": str(node.get("display_name") or ""),
                "orcid": str(node.get("orcid") or ""),
                "openalex": str(node.get("openalex") or ""),
                "country": country,
                "region": region_for_country(country),
                "discipline": str(node.get("discipline") or ""),
                "sector": str(node.get("sector") or ""),
                "career_stage": career_stage(
                    int(first) if first is not None else None,
                    int(last) if last is not None else None,
                ),
            }
        )
    return rows


def apply_attributes(graph: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, Any]:
    """Copy overlay fields onto graph nodes (id match)."""
    by_id = {str(row.get("id") or ""): row for row in rows if row.get("id")}
    nodes = []
    for node in graph.get("nodes") or []:
        updated = dict(node)
        overlay = by_id.get(str(node.get("id") or ""))
        if overlay:
            for field in ("region", "discipline", "sector", "career_stage", "country"):
                value = str(overlay.get(field) or "").strip()
                if value:
                    updated[field] = value
        nodes.append(updated)
    out = dict(graph)
    out["nodes"] = nodes
    return out


def merge_attributes(
    seeded: list[dict[str, str]], overlay: list[dict[str, str]]
) -> list[dict[str, str]]:
    by_id = {row["id"]: dict(row) for row in seeded if row.get("id")}
    for row in overlay:
        key = str(row.get("id") or "")
        if not key:
            continue
        current = by_id.get(key) or {field: "" for field in ATTRIBUTE_FIELDS}
        current["id"] = key
        for field in ATTRIBUTE_FIELDS:
            if field == "id":
                continue
            value = str(row.get(field) or "").strip()
            if value:
                current[field] = value
        by_id[key] = current
    return list(by_id.values())


def write_attributes_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ATTRIBUTE_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: str(row.get(field) or "") for field in ATTRIBUTE_FIELDS})
    return path


def read_attributes_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            {field: str(row.get(field) or "") for field in ATTRIBUTE_FIELDS}
            for row in reader
        ]
