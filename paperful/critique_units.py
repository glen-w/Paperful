"""Heading units for critique lanes. Shared by MARG, claims, and verify."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import Config
from .critique_extract import ExtractedDoc
from .sections.headings import canonical_for_heading

_HEADING_LINE = re.compile(r"^(?:#{1,6}\s+)?([A-Z][A-Za-z][A-Za-z0-9 ,:/-]{2,80})$")

SOURCE_FAMILIES = frozenset(
    {"abstract", "results", "conclusion", "introduction"}
)
SUPPORT_FAMILIES = frozenset(
    {"methodology", "results", "limitations", "discussion"}
)
LIGHT_FAMILIES = frozenset(
    {"related_work", "acknowledgements", "references", "appendix"}
)


@dataclass
class Unit:
    heading: str
    loc: str
    text: str


def looks_heading(text: str) -> bool:
    line = (text or "").strip()
    if not line or "\n" in line:
        return False
    if line.startswith("#"):
        return True
    if len(line.split()) > 12:
        return False
    return bool(_HEADING_LINE.match(line))


def units_from_markdown(pages: list[str]) -> list[Unit]:
    heading = ""
    n = 0
    units: list[Unit] = []
    for page in pages:
        for block in re.split(r"\n\s*\n", page or ""):
            block = block.strip()
            if not block:
                continue
            if block.startswith("#"):
                first, _, rest = block.partition("\n")
                heading = first.lstrip("#").strip()
                block = rest.strip()
                if not block:
                    continue
            n += 1
            units.append(Unit(heading=heading, loc=f"paragraph {n}", text=block))
    return units


def units_from_doc(doc: ExtractedDoc) -> list[Unit]:
    heading = ""
    units: list[Unit] = []
    kind = doc.loc_kind or "paragraph"
    if doc.paragraphs:
        rows = list(doc.paragraphs)
    elif doc.pages:
        rows = list(doc.pages)
        kind = "page"
    else:
        rows = [p for p in re.split(r"\n\s*\n", doc.text or "") if p.strip()]
        kind = "paragraph"
    for i, raw in enumerate(rows, 1):
        text = (raw or "").strip()
        if not text:
            continue
        if looks_heading(text) and len(text) < 120:
            heading = text.lstrip("#").strip()
            continue
        units.append(Unit(heading=heading, loc=f"{kind} {i}", text=text))
    if not units and (doc.text or "").strip():
        units.append(Unit(heading="", loc="document", text=doc.text.strip()))
    return units


def family_of(unit: Unit, cfg: Config | None = None) -> str:
    """Canonical section family, or empty when the heading is unknown."""
    return canonical_for_heading(unit.heading or "", cfg) or ""


def units_for_families(
    units: Iterable[Unit], families: Iterable[str], cfg: Config | None = None
) -> list[Unit]:
    wanted = {str(f) for f in families}
    return [u for u in units if family_of(u, cfg) in wanted]


def paper_units(
    cfg: Config,
    doc: ExtractedDoc,
    *,
    use_grobid: bool,
    pdf_path: Path | None,
    item_key: str = "",
) -> tuple[list[Unit], dict[str, Any]]:
    """Heading units from GROBID markdown when requested, else the extract."""
    parser = "extract"
    skip = ""
    units: list[Unit] = []
    if use_grobid and pdf_path is not None and pdf_path.suffix.lower() == ".pdf":
        from .critique_marg import grobid_markdown

        pages, skip = grobid_markdown(cfg, pdf_path, item_key=item_key)
        if pages:
            units = units_from_markdown(pages)
            parser = "grobid"
        else:
            skip = skip or "grobid_failed"
    if not units:
        units = units_from_doc(doc)
        parser = "extract"
    meta: dict[str, Any] = {"parser": parser}
    if skip and parser == "extract":
        meta["grobid_skipped"] = skip
    return units, meta
