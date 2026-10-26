"""GROBID TEI cache and markdown projection for section extract / RAG."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ..config import Config
from ..grobid_client import GrobidClient, GrobidError, grobid_client_from_config
from ..rag.extract import file_sha256, needs_ocr
from ..store import load_json, write_json
from .headings import canonical_for_heading

TEI_SCHEMA = "paperful.grobid.tei.v1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
TEI_META_KEYS = frozenset(
    {
        "schema",
        "sha256",
        "item_key",
        "grobid_version",
        "consolidate_header",
        "consolidate_citations",
    }
)


def grobid_dir(cfg: Config) -> Path:
    return cfg.state_dir / "grobid"


def tei_paths(cfg: Config, sha256: str) -> tuple[Path, Path]:
    folder = grobid_dir(cfg)
    return folder / f"{sha256}.tei.xml", folder / f"{sha256}.json"


def load_cached_tei(
    cfg: Config,
    sha256: str,
    *,
    grobid_version: str | None = None,
    consolidate_header: int,
    consolidate_citations: int,
) -> str | None:
    xml_path, meta_path = tei_paths(cfg, sha256)
    meta = load_json(meta_path)
    if (
        not xml_path.is_file()
        or not meta
        or meta.get("schema") != TEI_SCHEMA
        or meta.get("sha256") != sha256
        or int(meta.get("consolidate_header") or 0) != int(consolidate_header)
        or int(meta.get("consolidate_citations") or 0) != int(consolidate_citations)
    ):
        return None
    if grobid_version is not None and str(meta.get("grobid_version") or "") != str(
        grobid_version
    ):
        return None
    try:
        return xml_path.read_text(encoding="utf-8")
    except OSError:
        return None


def save_cached_tei(
    cfg: Config,
    sha256: str,
    tei: str,
    *,
    grobid_version: str,
    consolidate_header: int,
    consolidate_citations: int,
    item_key: str = "",
) -> None:
    xml_path, meta_path = tei_paths(cfg, sha256)
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text(tei, encoding="utf-8")
    write_json(
        meta_path,
        {
            "schema": TEI_SCHEMA,
            "sha256": sha256,
            "item_key": item_key,
            "grobid_version": grobid_version,
            "consolidate_header": int(consolidate_header),
            "consolidate_citations": int(consolidate_citations),
        },
    )


def process_pdf(
    cfg: Config,
    pdf: Path,
    *,
    client: GrobidClient | None = None,
    item_key: str = "",
    force: bool = False,
) -> str:
    """Return TEI XML for ``pdf``, using the on-disk cache when the hash matches."""
    sha = file_sha256(pdf)
    owns = False
    header = (
        client.consolidate_header if client is not None else cfg.grobid_consolidate_header
    )
    citations = (
        client.consolidate_citations
        if client is not None
        else cfg.grobid_consolidate_citations
    )
    version: str | None = None
    if client is not None:
        try:
            version = client.version() or None
        except GrobidError:
            version = None
    if not force:
        cached = load_cached_tei(
            cfg,
            sha,
            grobid_version=version,
            consolidate_header=header,
            consolidate_citations=citations,
        )
        if cached:
            return cached
    try:
        if client is None:
            client = grobid_client_from_config(cfg)
            owns = True
            header = client.consolidate_header
            citations = client.consolidate_citations
            try:
                version = client.version() or None
            except GrobidError:
                version = None
            if not force:
                cached = load_cached_tei(
                    cfg,
                    sha,
                    grobid_version=version,
                    consolidate_header=header,
                    consolidate_citations=citations,
                )
                if cached:
                    return cached
        tei = client.process_fulltext(pdf)
        save_cached_tei(
            cfg,
            sha,
            tei,
            grobid_version=version or "",
            consolidate_header=header,
            consolidate_citations=citations,
            item_key=item_key,
        )
        return tei
    finally:
        if owns:
            client.close()


def _q(tag: str) -> str:
    return f"{{{TEI_NS}}}{tag}"


def _find(el: ET.Element, tag: str) -> ET.Element | None:
    hit = el.find(_q(tag))
    if hit is not None:
        return hit
    return el.find(tag)


def _findall(el: ET.Element, tag: str) -> list[ET.Element]:
    found = list(el.findall(_q(tag)))
    if found:
        return found
    return list(el.findall(tag))


def _iter(el: ET.Element, tag: str) -> list[ET.Element]:
    found = list(el.iter(_q(tag)))
    if found:
        return found
    return list(el.iter(tag))


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return " ".join("".join(el.itertext()).split())


def _head(div: ET.Element) -> str:
    head = _find(div, "head")
    if head is None:
        return ""
    return _text(head)


def _paragraphs(div: ET.Element) -> str:
    parts: list[str] = []
    for child in list(div):
        local = child.tag.rsplit("}", 1)[-1] if isinstance(child.tag, str) else ""
        if local == "head":
            continue
        if local == "div":
            continue
        blob = _text(child)
        if blob:
            parts.append(blob)
    return "\n\n".join(parts)


def _div_type(div: ET.Element) -> str:
    return (div.get("type") or "").replace("-", "_").strip().lower()


def parse_tei_tree(tei: str) -> ET.Element:
    try:
        root = ET.fromstring(tei)
    except ET.ParseError as exc:
        raise GrobidError(f"invalid TEI: {exc}") from exc
    return root


def tei_section_rows(tei: str, cfg: Config | None = None) -> list[dict[str, Any]]:
    """Ordered heading map from TEI body/front divs."""
    root = parse_tei_tree(tei)
    rows: list[dict[str, Any]] = []
    n = 0
    for div in _iter(root, "div"):
        head = _head(div)
        dtype = _div_type(div)
        if not head and not dtype:
            continue
        n += 1
        label = head or dtype.replace("_", " ").title()
        canon = canonical_for_heading(head or dtype, cfg) or canonical_for_heading(
            dtype.replace("_", " "), cfg
        )
        attr_n = _find(div, "head")
        numbered = ""
        if attr_n is not None:
            numbered = str(attr_n.get("n") or "").strip()
        row: dict[str, Any] = {"heading": label, "canonical": canon}
        if numbered:
            row["n"] = numbered
        else:
            row["n"] = str(n)
        rows.append(row)
    return rows


def tei_to_markdown_pages(tei: str) -> list[str]:
    """Lossy markdown body (one page) so the IMRaD splitter sees ``#`` headings."""
    root = parse_tei_tree(tei)
    blocks: list[str] = []
    seen_abstract = False
    for ab in _iter(root, "abstract"):
        body = _text(ab)
        if body:
            blocks.append(f"# Abstract\n\n{body}")
            seen_abstract = True
            break
    for div in _iter(root, "div"):
        head = _head(div)
        dtype = _div_type(div)
        if dtype == "abstract" and seen_abstract:
            continue
        title = head or (dtype.replace("_", " ").title() if dtype else "")
        paras = _paragraphs(div)
        if not title and not paras:
            continue
        if title:
            blocks.append(f"# {title}\n\n{paras}".rstrip())
        elif paras:
            blocks.append(paras)
    text = "\n\n".join(blocks).strip()
    return [text] if text else []


def pdf_is_scan(pdf: Path) -> bool:
    """True when the text layer is too thin for GROBID (OCR first)."""
    from ..rag.extract import LightParser, ParseError

    try:
        pages = LightParser().pages(pdf)
    except ParseError:
        return True
    return needs_ocr(pages) is not None
