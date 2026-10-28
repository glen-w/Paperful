"""``paperful.rewrite.plan.v1``: consume a critique pack, write an edit plan."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .critique import critique_id, latest_pack_dir, load_pack
from .critique_extract import extract_path
from .rewrite_align import Alignment, align_finding
from .rewrite_areas import (
    COMMENT_ONLY_CODES,
    bucket_findings,
    parse_rewrite_areas_list,
    parse_rewrite_comments,
    parse_rewrite_outputs,
    rewrite_areas_for,
)
from .rewrite_docx import apply_tracked_docx, build_docx_from_paragraphs
from .rewrite_llm import budget_excerpt, proposed_from_area
from .rewrite_office import apply_odt, apply_pptx, build_odt_from_paragraphs
from .rewrite_openxml import audit_office_file
from .rewrite_pdf import build_pdf_from_paragraphs, pdf_structural_issues
from .rewrite_plan import RewriteEdit, RewritePlan, merge_edits
from .rewrite_render import apply_to_text, render_markdown
from .store import write_json

SCHEMA = "paperful.rewrite.pack.v1"
_VALE_SWAP = re.compile(
    r"(?:use|consider using|replace(?:ment)? with)\s+['\"]([^'\"]+)['\"]",
    re.I,
)


def rewrites_dir(cfg: Config) -> Path:
    return cfg.state_dir / "rewrites"


def latest_rewrite_dir(cfg: Config, cid: str) -> Path | None:
    root = rewrites_dir(cfg) / cid
    if not root.is_dir():
        return None
    dirs = sorted(
        (p for p in root.iterdir() if p.is_dir() and (p / "plan.json").is_file())
    )
    return dirs[-1] if dirs else None


def resolve_pack_dir(cfg: Config, raw: Path) -> Path | None:
    """Accept a pack.json path or a stamp/critique folder that contains one."""
    path = raw.expanduser()
    if path.is_file() and path.name == "pack.json":
        return path.parent
    if path.is_dir():
        if (path / "pack.json").is_file():
            return path
        nested = latest_pack_dir(cfg, path.name)
        if nested is not None:
            return nested
        # stamp folder under critiques/<id>/<stamp>
        if path.parent.is_dir() and (path / "pack.json").is_file():
            return path
    return None


def resolve_latest_pack(
    cfg: Config, *, item_key: str = "", file_path: Path | None = None
) -> Path | None:
    if item_key:
        return latest_pack_dir(cfg, item_key)
    if file_path is not None:
        cid = critique_id(kind="file", original_name=file_path.name)
        return latest_pack_dir(cfg, cid)
    return None


def _manuscript_path(pack: dict[str, Any], file_path: Path | None) -> Path | None:
    if file_path is not None:
        return file_path
    inp = pack.get("input") or {}
    staged = str(inp.get("staged_path") or "").strip()
    path = str(inp.get("path") or "").strip()
    for candidate in (path, staged):
        if candidate:
            p = Path(candidate)
            if p.is_file():
                return p
    return None


_ACRONYM_PAREN = re.compile(r"\(([A-Z]{2,12})\)\s*$")
_LEADING_FUNCTION = frozenset(
    {"the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "at", "by"}
)


def _acronym_replacement(quote: str, suggested: str, finding: dict[str, Any]) -> str | None:
    """Keep ``(TOKEN)`` when swapping a parenthetical expansion; refuse over-wide quotes."""
    from .glossary import tokenize

    extra = finding.get("extra") if isinstance(finding.get("extra"), dict) else {}
    token = str(extra.get("token") or "").strip().upper()
    paren = _ACRONYM_PAREN.search(quote)
    bare_quote = _ACRONYM_PAREN.sub("", quote).strip()
    bare_suggested = _ACRONYM_PAREN.sub("", suggested).strip()
    q_toks = tokenize(bare_quote)
    s_toks = tokenize(bare_suggested)
    if q_toks and q_toks[0][2].lower() in _LEADING_FUNCTION:
        if not s_toks or s_toks[0][2].lower() != q_toks[0][2].lower():
            return None
    if paren:
        tok = (token or paren.group(1)).upper()
        if tok and f"({tok})" not in suggested:
            suggested = f"{suggested} ({tok})"
            bare_suggested = _ACRONYM_PAREN.sub("", suggested).strip()
            s_toks = tokenize(bare_suggested)
        # Quote should be roughly ``expansion (TOKEN)`` — not ``Part IV on … (TOKEN)``.
        if len(q_toks) > len(s_toks) + 1:
            return None
    elif len(q_toks) > len(s_toks) + 1:
        return None
    return suggested


def _deterministic_edit(
    finding: dict[str, Any],
    aln: Alignment,
    area: str,
) -> RewriteEdit | None:
    suggested = str(finding.get("suggested") or "").strip()
    if not suggested:
        extra = finding.get("extra") if isinstance(finding.get("extra"), dict) else {}
        suggested = str(extra.get("suggested") or "").strip()
    quote = aln.quote
    if not suggested:
        detail = str(finding.get("detail") or "")
        match = _VALE_SWAP.search(detail)
        if match:
            suggested = match.group(1).strip()
    if not suggested or not quote or suggested == quote:
        return None
    code = str(finding.get("code") or "")
    # Retracted cites never become a body delete.
    if code in COMMENT_ONLY_CODES:
        return None
    if code in {"acronym_expansion_mismatch", "acronym_phrase_mismatch"}:
        suggested_fixed = _acronym_replacement(quote, suggested, finding)
        if suggested_fixed is None:
            return None
        suggested = suggested_fixed
        if suggested == quote:
            return None
    return RewriteEdit(
        kind="replace",
        finding_ids=[str(finding.get("id") or "")],
        area=area,
        loc=aln.loc,
        quote=quote,
        replacement=suggested,
        source_paragraph=aln.paragraph,
        target_paragraph=aln.paragraph.replace(quote, suggested, 1),
        start=aln.start,
        end=aln.end,
    )


def _comment_edit(
    finding: dict[str, Any],
    aln: Alignment,
    area: str,
) -> RewriteEdit:
    body = str(finding.get("detail") or finding.get("quote") or "").strip()
    return RewriteEdit(
        kind="comment",
        finding_ids=[str(finding.get("id") or "")],
        area=area,
        loc=aln.loc,
        quote=aln.quote,
        body=body[:500],
        source_paragraph=aln.paragraph,
        target_paragraph=aln.paragraph,
        start=aln.start,
        end=aln.end,
    )


def _area_needs_llm(findings: list[dict[str, Any]], det_ids: set[str]) -> bool:
    return any(str(f.get("id") or "") not in det_ids for f in findings)


def _paragraphs(doc: Any, text: str) -> list[str]:
    paras = [p for p in (doc.paragraphs or []) if str(p).strip()]
    if paras:
        return paras
    return [p for p in text.split("\n\n") if p.strip()]


def _write_tracked(
    folder: Path,
    manuscript: Path,
    paragraphs: list[str],
    edits: list[RewriteEdit],
) -> tuple[Path, Path | None]:
    """Native tracked file when the source is Office; Word spine otherwise."""
    suffix = manuscript.suffix.lower()
    if suffix == ".docx":
        dest = folder / "tracked.docx"
        apply_tracked_docx(manuscript, dest, edits)
        return dest, manuscript
    if suffix == ".pptx":
        dest = folder / "tracked.pptx"
        apply_pptx(manuscript, dest, edits)
        return dest, manuscript
    if suffix == ".odt":
        dest = folder / "tracked.odt"
        apply_odt(manuscript, dest, edits)
        return dest, manuscript
    dest = folder / "tracked.docx"
    build_docx_from_paragraphs(dest, paragraphs, edits)
    return dest, None


def _write_odt(
    folder: Path,
    manuscript: Path,
    paragraphs: list[str],
    edits: list[RewriteEdit],
) -> tuple[Path, Path | None]:
    dest = folder / "tracked.odt"
    if manuscript.suffix.lower() == ".odt":
        apply_odt(manuscript, dest, edits)
        return dest, manuscript
    build_odt_from_paragraphs(dest, paragraphs, edits)
    return dest, None


def build_rewrite(
    cfg: Config,
    *,
    pack: dict[str, Any],
    manuscript: Path,
    areas: tuple[str, ...] | None = None,
    outputs: tuple[str, ...] | None = None,
    comments: str | None = None,
    dry_run: bool = False,
    llm_client: Any | None = None,
    on_status: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Align findings, propose edits, write ``state/rewrites/<id>/<stamp>/``."""
    say = on_status or (lambda _msg: None)
    area_ids = parse_rewrite_areas_list(
        list(areas) if areas is not None else list(cfg.rewrite_areas)
    )
    output_ids = parse_rewrite_outputs(
        list(outputs) if outputs is not None else list(cfg.rewrite_outputs)
    )
    comment_mode = parse_rewrite_comments(
        comments if comments is not None else cfg.rewrite_comments
    )
    specialists = rewrite_areas_for(cfg, list(area_ids))
    cid = str(pack.get("critique_id") or "")
    if not cid:
        inp = pack.get("input") or {}
        cid = critique_id(
            kind=str(inp.get("kind") or "file"),
            item_key=str(inp.get("item_key") or ""),
            original_name=Path(str(inp.get("title") or manuscript.name)).name,
        )

    say(f"Extracting {manuscript.name}…")
    doc = extract_path(manuscript)
    text = doc.text or ""
    findings = [f for f in (pack.get("findings") or []) if isinstance(f, dict)]
    llm_block = pack.get("llm") if isinstance(pack.get("llm"), dict) else {}
    if comment_mode in {"substantive", "all"}:
        for row in llm_block.get("reviewers") or []:
            if not isinstance(row, dict):
                continue
            note = str(row.get("narrative") or "").strip()
            if not note:
                continue
            findings.append(
                {
                    "id": f"narrative-{row.get('id') or 'reviewer'}",
                    "code": "reviewer_note",
                    "lane": "suggested",
                    "severity": "info",
                    "loc": "",
                    "quote": "",
                    "detail": note[:500],
                    "source": "llm",
                }
            )

    buckets, skips = bucket_findings(findings, areas=area_ids, hay=text)
    alignments: dict[str, Alignment] = {}
    say("Aligning findings…")
    pending: dict[str, list[dict[str, Any]]] = {a: [] for a in area_ids}
    for area, rows in buckets.items():
        for row in rows:
            fid = str(row.get("id") or "")
            bound = align_finding(row, text=text, paragraphs=doc.paragraphs)
            if isinstance(bound, str):
                if comment_mode != "off" and area == "comments":
                    skips.append({"finding_id": fid, "reason": bound})
                else:
                    skips.append({"finding_id": fid, "reason": bound})
                continue
            alignments[fid] = bound
            pending[area].append(row)

    proposed: list[RewriteEdit] = []
    det_ids: set[str] = set()
    models: dict[str, str] = {}

    for area, rows in pending.items():
        for row in rows:
            fid = str(row.get("id") or "")
            aln = alignments.get(fid)
            if aln is None:
                continue
            code = str(row.get("code") or "")
            if code in COMMENT_ONLY_CODES or area == "comments":
                proposed.append(_comment_edit(row, aln, area))
                det_ids.add(fid)
                continue
            det = _deterministic_edit(row, aln, area)
            if det is not None:
                proposed.append(det)
                det_ids.add(fid)

    timeout = float(cfg.rewrite_timeout_s or 0) or max(float(cfg.llm_timeout_s), 600.0)
    for spec in specialists:
        rows = [
            r
            for r in pending.get(spec.id, [])
            if str(r.get("id") or "") not in det_ids
        ]
        if not rows:
            continue
        if not _area_needs_llm(rows, det_ids):
            continue
        if llm_client is None:
            for r in rows:
                skips.append(
                    {"finding_id": str(r.get("id") or ""), "reason": "needs_author"}
                )
            continue
        excerpt = budget_excerpt(cfg, text)
        edits, extra_skips, model = proposed_from_area(
            cfg,
            area=spec,
            findings=rows,
            alignments=alignments,
            excerpt=excerpt,
            client=llm_client,
            timeout_s=timeout,
            on_status=on_status,
        )
        models[spec.id] = model
        proposed.extend(edits)
        skips.extend(extra_skips)

    plan = merge_edits(
        proposed, max_edits=int(cfg.rewrite_max_edits or 80), existing_skips=skips
    )
    plan.models = models
    plan.worklog = {
        "addressed": [
            f"{e.area}:{e.kind}:{e.quote[:60]}" for e in plan.edits
        ],
        "models": models,
    }

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "critique_id": cid,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "input": {
            "path": str(manuscript),
            "format": doc.format,
            "critique_pack": str(pack.get("pack_dir") or ""),
        },
        "areas": list(area_ids),
        "outputs": list(output_ids),
        "comments": comment_mode,
        "counts": {
            "edits": len(plan.edits),
            "skips": len(plan.skips),
            "by_kind": {},
            "by_area": {},
        },
    }
    by_kind: dict[str, int] = {}
    by_area: dict[str, int] = {}
    for e in plan.edits:
        by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
        by_area[e.area] = by_area.get(e.area, 0) + 1
    payload["counts"]["by_kind"] = by_kind
    payload["counts"]["by_area"] = by_area
    payload["plan"] = plan.to_dict()

    folder: Path | None = None
    if not dry_run:
        say("Writing rewrite pack…")
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        folder = rewrites_dir(cfg) / cid / stamp
        folder.mkdir(parents=True, exist_ok=True)
        payload["pack_dir"] = str(folder)
        write_json(folder / "plan.json", plan.to_dict())
        (folder / "pack.md").write_text(
            render_markdown(payload, plan), encoding="utf-8"
        )
        write_json(folder / "pack.json", payload)
        if "sidecar" in output_ids:
            sidecar = apply_to_text(text, plan.edits)
            suffix = ".md" if manuscript.suffix.lower() in {".md", ".txt", ""} else ".txt"
            (folder / f"sidecar{suffix}").write_text(sidecar, encoding="utf-8")
        paras = _paragraphs(doc, text)
        office: dict[str, tuple[Path, Path | None]] = {}
        if "tracked" in output_ids:
            dest, source = _write_tracked(folder, manuscript, paras, plan.edits)
            office[dest.name] = (dest, source)
            payload["tracked"] = dest.name
        if "odt" in output_ids:
            if "tracked.odt" in office:
                dest, source = office["tracked.odt"]
            else:
                dest, source = _write_odt(folder, manuscript, paras, plan.edits)
                office[dest.name] = (dest, source)
            payload["odt"] = dest.name
        if "pdf" in output_ids:
            pdf_dest = folder / "tracked.pdf"
            pdf_skips = build_pdf_from_paragraphs(pdf_dest, paras, plan.edits)
            payload["pdf"] = pdf_dest.name if pdf_dest.is_file() else ""
            payload["pdf_audit"] = {
                "skipped": pdf_skips[0] if pdf_skips and not pdf_dest.is_file() else "",
                "structural": (
                    pdf_structural_issues(pdf_dest) if pdf_dest.is_file() else pdf_skips
                ),
            }
        if office:
            audits = {
                name: audit_office_file(cfg, dest, source=source)
                for name, (dest, source) in office.items()
            }
            payload["audits"] = audits
            primary = payload.get("tracked") or payload.get("odt") or next(iter(audits))
            payload["openxml_audit"] = audits.get(str(primary), next(iter(audits.values())))
            write_json(folder / "pack.json", payload)
            (folder / "pack.md").write_text(
                render_markdown(payload, plan), encoding="utf-8"
            )
        elif payload.get("pdf_audit"):
            write_json(folder / "pack.json", payload)
            (folder / "pack.md").write_text(
                render_markdown(payload, plan), encoding="utf-8"
            )
    payload["_plan"] = plan
    payload["_doc"] = doc
    return payload
