#!/usr/bin/env python3
"""Build state/glossary/ocean.json from STRONG (2022) and IDDRI (2018) PDFs.

Requires: pdftotext (poppler)

  python scripts/build_ocean_glossary.py \\
    --strong ~/Desktop/Diz-...-Glossary-Ocean-Governance-Terms.pdf \\
    --iddri ~/Desktop/201808-Study_HauteMer-long\\ and\\ winding\\ road.pdf
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCHEMA = "paperful.glossary.v1"

# IDDRI Study 08/2018 — abbreviations not in STRONG list (layout pages 6–7).
IDDRI_EXTRA: dict[str, str] = {
    "ABMTs": "Area-based management tools",
    "AIS": "Automatic Identification System",
    "AOSIS": "Alliance of Small Island States",
    "ASMA": "Antarctic Specially Managed Area",
    "ASPA": "Antarctic Specially Protected Area",
    "ATBA": "Area To Be Avoided",
    "ATS": "Antarctic Treaty System",
    "AU": "African Union",
    "CARICOM": "Caribbean Community",
    "CLCS": "Commission on the Limits of the Continental Shelf",
    "COFI": "FAO Committee on Fisheries",
    "DG MARE": "Directorate-General for Maritime Affairs and Fisheries of the European Commission",
    "DOALOS": "Division for Ocean Affairs and the Law of the Sea",
    "DOSI": "Deep-Ocean Stewardship Initiative",
    "EC": "European Commission",
    "ENB": "Earth Negotiations Bulletin",
    "EU": "European Union",
    "GEF": "Global Environment Facility",
    "GFCM": "General Fisheries Commission for the Mediterranean and Black Sea",
    "ICP": "United Nations Open-ended Informal Consultative Process on Oceans and the Law of the Sea",
    "ICPC": "International Cable Protection Committee",
    "ILBI": "International legally binding instrument",
    "IOTC": "Indian Ocean Tuna Commission",
    "IPRs": "Intellectual property rights",
    "ITLOS": "International Tribunal on the Law of the Sea",
    "LDCs": "Least Developed Countries",
    "LLDCs": "Landlocked Developing Countries",
    "LSMPA": "Large-Scale Marine Protected Area",
    "MAP": "Mediterranean Action Plan",
    "MGRs": "Marine genetic resources",
    "MoU": "Memorandum of Understanding",
    "MSR": "Marine scientific research",
    "NAFO": "North Atlantic Fisheries Organisation",
    "NAMMCO": "North Atlantic Marine Mammal Commission",
    "NEAFC": "North East Atlantic Fisheries Commission",
    "NDCs": "Nationally Determined Contributions",
    "NPFC": "North Pacific Fisheries Commission",
    "OSPAR": "Convention for the Protection of the Marine Environment of the North-East Atlantic (Oslo-Paris Convention)",
    "PrepCom": "Preparatory Committee",
    "PSIDS": "Pacific Small Island Developing States",
    "R&D": "Research and development",
    "RFB": "Regional fishery body",
    "SA": "Special Area",
    "SBSTTA": "Subsidiary Body on Scientific, Technical and Technological Advice",
    "SDGs": "Sustainable Development Goals",
    "SIDS": "Small Island Developing States",
    "SIOFA": "South Indian Ocean Fisheries Agreement",
    "SPAMI": "Specially Protected Area of Mediterranean Importance",
    "SPREP": "South Pacific Regional Environment Programme",
    "UN-OHRLLS": "United Nations Office of the High Representative for the Least Developed Countries",
    "UNEA": "United Nations Environment Assembly",
    "UNESCO-IOC": "Intergovernmental Oceanographic Commission",
    "VMS": "Vessel Monitoring System",
}

# Canonical fixes (STRONG typos / negotiation usage).
CANONICAL_OVERRIDES: dict[str, str] = {
    "IUCN": "International Union for Conservation of Nature",
    "COP": "Conference of the Parties",
    "FAO": "Food and Agriculture Organization of the United Nations",
}

# Alternate phrasings from IDDRI / common drafts (aliases only).
IDDRI_ALIASES: dict[str, list[str]] = {
    "ABMT": ["Area-based management tool", "area-based management tools"],
    "ABNJ": [
        "Areas beyond national jurisdiction",
        "marine areas beyond national jurisdiction",
    ],
    "ABS": ["Access and benefit sharing"],
    "APEI": ["Areas of Particular Environmental Interest"],
    "BBNJ": [
        "biodiversity beyond national jurisdiction",
        "marine biological diversity beyond areas of national jurisdiction",
        "marine biodiversity in areas beyond national jurisdiction",
        "Maritime Areas beyond national jurisdiction",
    ],
    "EBSA": ["Ecologically or Biologically Significant Marine Areas"],
    "EIA": ["Environmental impact assessment"],
    "IUU": ["Illegal, unreported and unregulated fishing"],
    "MSP": ["marine spatial planning"],
    "MGR": ["Marine genetic resources"],
    "PSSA": ["Particularly Sensitive Sea Area"],
    "PSMA": ["Port State Measures Agreement"],
    "UNEP": ["United Nations Environment Program"],
    "UNFSA": ["United Nations Fish Stocks Agreement"],
    "VME": ["Vulnerable marine ecosystem"],
}


def pdftotext_layout(pdf: Path, first: int, last: int) -> str:
    proc = subprocess.run(
        ["pdftotext", "-layout", "-f", str(first), "-l", str(last), str(pdf), "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pdftotext failed for {pdf}: {proc.stderr.strip()}")
    return proc.stdout


def parse_strong_acronyms(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    current_token: str | None = None
    buf: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or "Glossary of Ocean" in line or line == "List of Acronyms":
            continue
        if re.fullmatch(r"\d+", line):
            continue
        m = re.match(r"^([A-Z][A-Z0-9\-]{1,15}(?:\s[A-Z]+)?)\s{2,}(.+)$", line)
        if m:
            if current_token and buf:
                entries[current_token] = " ".join(buf).strip()
            current_token = m.group(1).strip()
            buf = [m.group(2).strip()]
            continue
        m2 = re.match(r"^([A-Z][A-Z0-9\-]{1,15}(?:\s[A-Z]+)?)\s+(.+)$", line)
        if m2:
            if current_token and buf:
                entries[current_token] = " ".join(buf).strip()
            current_token = m2.group(1).strip()
            buf = [m2.group(2).strip()]
            continue
        if current_token and raw.startswith(" "):
            buf.append(line)
    if current_token and buf:
        entries[current_token] = " ".join(buf).strip()
    return entries


def _dedupe_aliases(expansion: str, aliases: list[str]) -> list[str]:
    seen = {expansion.casefold()}
    out: list[str] = []
    for alias in aliases:
        key = alias.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(alias)
    return out


def build(strong_pdf: Path, iddri_pdf: Path) -> dict:
    strong_text = pdftotext_layout(strong_pdf, 6, 7)
    strong = parse_strong_acronyms(strong_text)
    for tok, canon in CANONICAL_OVERRIDES.items():
        if tok in strong:
            strong[tok] = canon

    by_token: dict[str, dict[str, object]] = {}
    for tok, exp in sorted(strong.items()):
        by_token[tok] = {"token": tok, "expansion": exp, "aliases": []}

    for tok, exp in IDDRI_EXTRA.items():
        if tok in by_token:
            if exp.casefold() != str(by_token[tok]["expansion"]).casefold():
                by_token[tok]["aliases"].append(exp)  # type: ignore[union-attr]
        elif tok.endswith("s") and tok[:-1] in by_token:
            base = tok[:-1]
            if exp.casefold() != str(by_token[base]["expansion"]).casefold():
                by_token[base]["aliases"].append(exp)  # type: ignore[union-attr]
        else:
            by_token[tok] = {"token": tok, "expansion": exp, "aliases": []}

    for tok, aliases in IDDRI_ALIASES.items():
        if tok not in by_token:
            continue
        by_token[tok]["aliases"].extend(aliases)  # type: ignore[union-attr]

    entries: list[dict[str, object]] = []
    for tok in sorted(by_token):
        row = by_token[tok]
        expansion = str(row["expansion"])
        aliases = _dedupe_aliases(expansion, list(row.get("aliases") or []))
        item: dict[str, object] = {"token": tok, "expansion": expansion}
        if aliases:
            item["aliases"] = aliases
        entries.append(item)

    return {"schema": SCHEMA, "scope": "ocean", "entries": entries}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strong", type=Path, required=True, help="STRONG 2022 glossary PDF")
    parser.add_argument("--iddri", type=Path, required=True, help="IDDRI 2018 study PDF")
    parser.add_argument(
        "-o",
        type=Path,
        default=Path("state/glossary/ocean.json"),
        help="Output JSON path (default: state/glossary/ocean.json)",
    )
    args = parser.parse_args()
    if not args.strong.is_file():
        print(f"not found: {args.strong}", file=sys.stderr)
        return 1
    if not args.iddri.is_file():
        print(f"not found: {args.iddri}", file=sys.stderr)
        return 1

    payload = build(args.strong, args.iddri)
    args.o.parent.mkdir(parents=True, exist_ok=True)
    args.o.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {args.o} ({len(payload['entries'])} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
