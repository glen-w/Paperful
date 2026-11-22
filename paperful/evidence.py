"""``paperful.evidence.v1``: sourced comparison table over held PDFs.

No LLM. A cell is a quote that occurs in the PDF, or the literal ``check this``.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .fsio import atomic_write_text
from .grounding import pdf_pages_for
from .library import LibraryBackend
from .peer_review_claims import quote_in_text
from .peer_review_metrics import split_sentences
from .store import Manifest, write_json
from .zot import Item

SCHEMA = "paperful.evidence.v1"
CHECK_THIS = "check this"
HONESTY_BANNER = (
    "Each cell is a quote from a PDF you hold, or the literal check this. "
    "design is OpenAlex study_designs only when already on disk, else the "
    "Zotero item type. n / method / finding are never paraphrased. "
    "This is not a verdict and it does not invent statistics."
)
EVIDENCE_PACK_KEYS = frozenset(
    {
        "schema",
        "evidence_id",
        "created_at",
        "scope",
        "rows",
        "counts",
        "skips",
    }
)
CSV_FIELDS = (
    "key",
    "title",
    "year",
    "stem",
    "design",
    "n",
    "method",
    "finding",
    "loc",
)
_N_RE = re.compile(
    r"(?i)\b(?:n\s*[=≈]\s*|sample of\s+)(\d{1,7})\b"
    r"|\b(\d{1,7})\s+(?:participants|patients|respondents|subjects)\b"
)
FIELD_NAMES = ("methodology", "results", "conclusion")


@dataclass
class EvidenceRow:
    key: str
    title: str
    year: int | None
    stem: str
    design: str
    n: str
    method: str
    finding: str
    loc: str
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class EvidenceSkip:
    key: str
    reason: str
    title: str = ""


@dataclass
class EvidenceBatch:
    rows: list[EvidenceRow] = field(default_factory=list)
    skips: list[EvidenceSkip] = field(default_factory=list)

    @property
    def findings(self) -> int:
        return sum(1 for r in self.rows if r.finding != CHECK_THIS and not r.skipped)


def _joined(pages: list[str]) -> str:
    return "\n\n".join(pages)


def loc_for_quote(quote: str, pages: list[str]) -> str:
    if not (quote or "").strip():
        return ""
    for i, page in enumerate(pages, start=1):
        if quote_in_text(quote, page):
            return f"p. {i}"
    return ""


def quoted_span(
    source: str, pages: list[str], *, loc_hint: str = ""
) -> tuple[str, str]:
    """Return (cell, loc). Cell is a quote in ``pages`` or ``check this``."""
    text = re.sub(r"\s+", " ", (source or "").strip())
    if not text:
        return CHECK_THIS, ""
    joined = _joined(pages)
    for sent in split_sentences(text):
        clip = re.sub(r"\s+", " ", sent.strip())[:200]
        if quote_in_text(clip, joined):
            return clip, loc_for_quote(clip, pages) or loc_hint
    clip = text[:200]
    if quote_in_text(clip, joined):
        return clip, loc_for_quote(clip, pages) or loc_hint
    return CHECK_THIS, ""


def sample_size_cell(source: str, pages: list[str]) -> tuple[str, str]:
    text = source or ""
    joined = _joined(pages)
    for sent in split_sentences(text):
        if not _N_RE.search(sent):
            continue
        clip = re.sub(r"\s+", " ", sent.strip())[:200]
        if quote_in_text(clip, joined):
            return clip, loc_for_quote(clip, pages)
    match = _N_RE.search(text)
    if match:
        clip = match.group(0)
        if quote_in_text(clip, joined):
            return clip, loc_for_quote(clip, pages)
    return CHECK_THIS, ""


def _field_text(fields: dict[str, Any], name: str) -> tuple[str, str]:
    raw = fields.get(name)
    if not isinstance(raw, dict):
        return "", ""
    text = str(raw.get("text") or "").strip()
    pages = str(raw.get("pages") or "").strip()
    return text, pages


def _design_of(item: Item) -> str:
    extra = item.extra or ""
    for line in extra.splitlines():
        if line.lower().startswith("study_design"):
            value = line.split(":", 1)[-1].strip()
            if value:
                return value
    kind = (item.item_type or "").strip()
    return kind or "unspecified"


def _stem_of(item: Item) -> str:
    path = (item.pdf_path or "").strip()
    if path:
        parent = Path(path).parent.name
        if parent:
            return parent
    return item.key


def _extract_fields(cfg: Config, item: Item, pages: list[str]) -> dict[str, Any]:
    from .sections.command import item_path
    from .sections.extract import extract_fields
    from .store import load_json

    stored = load_json(item_path(cfg, item.key))
    if isinstance(stored, dict) and stored.get("schema") == "paperful.sections.v1":
        fields = stored.get("fields")
        if isinstance(fields, dict) and fields:
            return fields
    result = extract_fields(
        cfg,
        pages,
        record_abstract=item.abstract or "",
        mvp_fields=FIELD_NAMES,
        raw_map=False,
        max_field_chars=cfg.extract_sections_max_field_chars,
    )
    return result.fields


def collect_item(
    cfg: Config,
    item: Item,
    manifest: Manifest | None,
    backend: LibraryBackend | None,
) -> EvidenceRow | EvidenceSkip:
    if not item.has_pdf:
        return EvidenceSkip(key=item.key, title=item.title, reason="no PDF")
    pages = [p for p in pdf_pages_for(cfg, item, manifest, backend) if str(p).strip()]
    if not pages:
        return EvidenceSkip(key=item.key, title=item.title, reason="no PDF text")
    fields = _extract_fields(cfg, item, pages)
    methods, method_loc = _field_text(fields, "methodology")
    results, results_loc = _field_text(fields, "results")
    conclusion, conclusion_loc = _field_text(fields, "conclusion")
    method, m_loc = quoted_span(methods, pages, loc_hint=method_loc)
    finding, f_loc = quoted_span(results, pages, loc_hint=results_loc)
    if finding == CHECK_THIS:
        finding, f_loc = quoted_span(conclusion, pages, loc_hint=conclusion_loc)
    n_cell, n_loc = sample_size_cell(f"{methods}\n{results}", pages)
    loc = m_loc or f_loc or n_loc
    return EvidenceRow(
        key=item.key,
        title=item.title,
        year=item.year,
        stem=_stem_of(item),
        design=_design_of(item),
        n=n_cell,
        method=method,
        finding=finding,
        loc=loc,
    )


def collect_items(
    cfg: Config,
    items: list[Item],
    manifest: Manifest | None,
    backend: LibraryBackend | None,
) -> EvidenceBatch:
    batch = EvidenceBatch()
    for item in items:
        row = collect_item(cfg, item, manifest, backend)
        if isinstance(row, EvidenceSkip):
            batch.skips.append(row)
            continue
        batch.rows.append(row)
    return batch


def counts_of(batch: EvidenceBatch) -> dict[str, int]:
    return {
        "rows": len(batch.rows),
        "skips": len(batch.skips),
        "findings": batch.findings,
        "check_this": sum(
            1 for r in batch.rows if CHECK_THIS in (r.n, r.method, r.finding)
        ),
    }


def pack_payload(
    *,
    evidence_id: str,
    scope: str,
    batch: EvidenceBatch,
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "evidence_id": evidence_id,
        "created_at": created_at or datetime.now(tz=timezone.utc).isoformat(),
        "scope": scope,
        "rows": [_row_to_dict(r) for r in batch.rows],
        "counts": counts_of(batch),
        "skips": [
            {"key": s.key, "title": s.title, "reason": s.reason} for s in batch.skips
        ],
    }


def _row_to_dict(row: EvidenceRow) -> dict[str, Any]:
    return {
        "key": row.key,
        "title": row.title,
        "year": row.year,
        "stem": row.stem,
        "design": row.design,
        "n": row.n,
        "method": row.method,
        "finding": row.finding,
        "loc": row.loc,
    }


def render_markdown(pack: dict[str, Any]) -> str:
    counts = pack.get("counts") or {}
    lines = [
        f"# Evidence table — {pack.get('scope') or ''}",
        "",
        HONESTY_BANNER,
        "",
        (
            f"Rows {counts.get('rows', 0)}; "
            f"findings {counts.get('findings', 0)}; "
            f"skips {counts.get('skips', 0)}."
        ),
        "",
        "| key | year | design | n | method | finding | loc |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in pack.get("rows") or []:
        if not isinstance(row, dict):
            continue

        def cell(name: str, width: int = 40) -> str:
            raw = str(row.get(name) or "").replace("|", "/")
            if len(raw) > width:
                raw = raw[: width - 1] + "…"
            return raw or " "

        year = row.get("year")
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{row.get('key') or ''}`",
                    str(year) if year else "",
                    cell("design", 24),
                    cell("n", 24),
                    cell("method"),
                    cell("finding"),
                    cell("loc", 16),
                ]
            )
            + " |"
        )
    lines.append("")
    skips = [s for s in (pack.get("skips") or []) if isinstance(s, dict)]
    if skips:
        lines.extend(["## Skips", ""])
        for skip in skips:
            lines.append(f"- `{skip.get('key') or ''}`: {skip.get('reason') or ''}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_csv(path: Path, pack: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CSV_FIELDS), extrasaction="ignore")
        writer.writeheader()
        for row in pack.get("rows") or []:
            if not isinstance(row, dict):
                continue
            writer.writerow(
                {k: row.get(k) if row.get(k) is not None else "" for k in CSV_FIELDS}
            )


def write_pack(
    cfg: Config,
    payload: dict[str, Any],
    *,
    stamp: str | None = None,
) -> Path:
    stamp = stamp or datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = cfg.evidence_dir / stamp
    folder.mkdir(parents=True, exist_ok=True)
    payload.setdefault("schema", SCHEMA)
    write_json(folder / "pack.json", payload)
    atomic_write_text(folder / "pack.md", render_markdown(payload))
    write_csv(folder / "table.csv", payload)
    return folder
