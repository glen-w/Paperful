"""CLI scope, disk I/O, and per-item extract orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..config import Config
from ..grobid_client import GrobidClient, GrobidError
from ..llm import LLMClient
from ..rag.extract import TEXT_SCHEMA, LightParser, file_sha256, text_cache_path
from ..rag.ingest import select_entries
from ..rag.ledger import abstract_of, pick_pdf
from ..store import MirrorEntry, load_json, write_json
from .extract import extract_fields, merge_llm_fields, stamp_provenance
from .headings import DEFAULT_MVP_FIELDS
from .llm import fill_missing_llm

SCHEMA = "paperful.sections.v1"
SECTION_KEYS = frozenset(
    {
        "schema",
        "item_key",
        "title",
        "year",
        "source",
        "fields",
        "missing",
    }
)


@dataclass
class ItemSections:
    schema: str
    item_key: str
    title: str
    year: int | None
    source: str
    fields: dict[str, Any] = field(default_factory=dict)
    sections: list[dict[str, Any]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    engine: str = "rule"  # grobid | rule
    pdf_sha256: str = ""
    notes: list[str] = field(default_factory=list)


def sections_dir(cfg: Config) -> Path:
    return cfg.sections_dir


def item_path(cfg: Config, key: str) -> Path:
    return sections_dir(cfg) / f"{key}.json"


def load_pages(cfg: Config, entry: MirrorEntry) -> list[str]:
    key = entry.key
    stored = load_json(text_cache_path(cfg, key))
    if (
        stored
        and stored.get("schema") == TEXT_SCHEMA
        and isinstance(stored.get("pages"), list)
    ):
        return [str(p) for p in stored["pages"]]
    pdf = pick_pdf(entry)
    if pdf is None:
        return []
    try:
        return LightParser().pages(pdf.path)
    except Exception:
        return []


def extract_item(
    cfg: Config,
    entry: MirrorEntry,
    *,
    use_llm: bool = False,
    client: LLMClient | None = None,
    force: bool = False,
    use_grobid: bool = False,
    grobid: GrobidClient | None = None,
) -> ItemSections | None:
    pages = load_pages(cfg, entry)
    abstract = abstract_of(entry)
    mvp = cfg.extract_sections_fields or DEFAULT_MVP_FIELDS
    raw_map = cfg.extract_sections_raw_map
    max_chars = cfg.extract_sections_max_field_chars
    pdf = pick_pdf(entry)
    sha = ""
    if pdf is not None:
        try:
            sha = file_sha256(pdf.path)
        except OSError:
            sha = ""

    engine = "rule"
    notes: list[str] = []
    result = extract_fields(
        cfg,
        pages,
        record_abstract=abstract,
        mvp_fields=mvp,
        raw_map=raw_map,
        max_field_chars=max_chars,
    )

    if use_grobid and pdf is not None:
        from .grobid import (
            pdf_is_scan,
            process_pdf,
            tei_section_rows,
            tei_to_markdown_pages,
        )

        if pdf_is_scan(pdf.path):
            notes.append("scan — GROBID skipped; run paperful ocr first")
        else:
            try:
                tei = process_pdf(
                    cfg,
                    pdf.path,
                    client=grobid,
                    item_key=entry.key,
                    force=force,
                )
                md_pages = tei_to_markdown_pages(tei)
                if md_pages:
                    grobid_result = extract_fields(
                        cfg,
                        md_pages,
                        record_abstract=abstract,
                        mvp_fields=mvp,
                        raw_map=raw_map,
                        max_field_chars=max_chars,
                    )
                    stamp_provenance(grobid_result, "grobid")
                    merge_llm_fields(grobid_result, result.fields, mvp)
                    if raw_map:
                        tei_map = tei_section_rows(tei, cfg)
                        if tei_map:
                            grobid_result.sections = tei_map
                        elif not grobid_result.sections:
                            grobid_result.sections = result.sections
                    result = grobid_result
                    engine = "grobid"
                    pages = md_pages
            except GrobidError as exc:
                notes.append(f"GROBID failed ({exc}); used heading rules")

    if use_llm and result.missing:
        from .extract import split_sections

        bodies = [sl.body for sl in split_sections(pages, cfg)]
        llm_out = fill_missing_llm(
            cfg,
            pages=pages,
            record_abstract=abstract,
            section_bodies=bodies,
            missing=list(result.missing),
            client=client,
        )
        merge_llm_fields(result, llm_out, mvp)

    item = entry.item()
    payload = ItemSections(
        schema=SCHEMA,
        item_key=entry.key,
        title=item.title,
        year=item.year,
        source=result.source,
        fields=result.fields,
        sections=result.sections if raw_map else [],
        missing=result.missing,
        engine=engine,
        pdf_sha256=sha,
        notes=notes,
    )
    return payload


def write_item(cfg: Config, item: ItemSections) -> Path:
    path = item_path(cfg, item.item_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    body: dict[str, Any] = {
        "schema": item.schema,
        "item_key": item.item_key,
        "title": item.title,
        "year": item.year,
        "source": item.source,
        "fields": item.fields,
        "missing": item.missing,
        "engine": item.engine,
    }
    if item.pdf_sha256:
        body["pdf_sha256"] = item.pdf_sha256
    if item.sections:
        body["sections"] = item.sections
    if item.notes:
        body["notes"] = item.notes
    write_json(path, body)
    return path


def load_item(cfg: Config, key: str) -> ItemSections | None:
    data = load_json(item_path(cfg, key))
    if not data or data.get("schema") != SCHEMA:
        return None
    return ItemSections(
        schema=SCHEMA,
        item_key=str(data.get("item_key") or key),
        title=str(data.get("title") or ""),
        year=data.get("year"),
        source=str(data.get("source") or "none"),
        fields=dict(data.get("fields") or {}),
        sections=list(data.get("sections") or []),
        missing=list(data.get("missing") or []),
        engine=str(data.get("engine") or "rule"),
        pdf_sha256=str(data.get("pdf_sha256") or ""),
        notes=[str(n) for n in (data.get("notes") or []) if str(n).strip()],
    )


def extract_scope(
    cfg: Config,
    *,
    collections: list[str] | None = None,
    item_keys: list[str] | None = None,
    library: bool = False,
    year_from: int | None = None,
    year_to: int | None = None,
    item_types: frozenset[str] | None = None,
    use_llm: bool = False,
    client: LLMClient | None = None,
    limit: int | None = None,
    force: bool = False,
    skip_existing: bool = True,
    use_grobid: bool = False,
    grobid: GrobidClient | None = None,
) -> list[ItemSections]:
    col_arg: list[str] | None
    if library and not collections:
        col_arg = None
    else:
        col_arg = list(collections or [])
    keys = list(item_keys or [])
    entries = select_entries(
        cfg,
        collections=col_arg,
        item_keys=keys or None,
        year_from=year_from,
        year_to=year_to,
        item_types=item_types,
    )
    ordered = sorted(entries, key=lambda e: e.key)
    if limit is not None:
        ordered = ordered[: max(0, limit)]
    out: list[ItemSections] = []
    for entry in ordered:
        if skip_existing and not force and item_path(cfg, entry.key).is_file():
            loaded = load_item(cfg, entry.key)
            if loaded is not None:
                out.append(loaded)
                continue
        item = extract_item(
            cfg,
            entry,
            use_llm=use_llm,
            client=client,
            force=force,
            use_grobid=use_grobid,
            grobid=grobid,
        )
        if item is not None:
            out.append(item)
    return out


def item_to_dict(item: ItemSections) -> dict[str, Any]:
    d = asdict(item)
    if not item.sections:
        d.pop("sections", None)
    if not item.pdf_sha256:
        d.pop("pdf_sha256", None)
    if not item.notes:
        d.pop("notes", None)
    return d
