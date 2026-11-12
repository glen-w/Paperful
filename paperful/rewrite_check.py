"""Post-edit Vale / glossary / cite-vs-bibliography checks. Not a second critique."""

from __future__ import annotations

from .config import Config
from .rewrite_grounding import cites_ok
from .rewrite_plan import RewriteEdit


def _glossary_regressed(cfg: Config, source: str, target: str) -> bool:
    try:
        from .glossary import load_glossary, scan_glossary
    except ImportError:
        return False
    entries, _issues = load_glossary(cfg)
    if not entries:
        return False
    sim = float(getattr(cfg, "critique_glossary_similarity_min", 0.88) or 0.88)
    before = scan_glossary(source or "", entries, similarity_min=sim)
    after = scan_glossary(target or "", entries, similarity_min=sim)
    return len(after) > len(before)


def _vale_regressed(cfg: Config, source: str, target: str) -> bool:
    from .critique_extract import ExtractedDoc
    from .critique_vale import resolve_vale_ini, run_vale

    if resolve_vale_ini(cfg) is None:
        return False
    src_doc = ExtractedDoc(text=source or "", format="md", paragraphs=[source or ""])
    tgt_doc = ExtractedDoc(text=target or "", format="md", paragraphs=[target or ""])
    src_hits, _ = run_vale(cfg, src_doc)
    tgt_hits, _ = run_vale(cfg, tgt_doc)
    return len(tgt_hits) > len(src_hits)


def _cite_regressed(full_text: str, source: str, target: str) -> bool:
    """True when the edit introduces a cite key that is not in the manuscript."""
    del source
    return not cites_ok(target or "", full_text or "")


def edit_breaks_checks(
    cfg: Config,
    edit: RewriteEdit,
    *,
    full_text: str,
) -> str | None:
    """Return ``broken_check`` when the body edit introduces a new hygiene issue."""
    if edit.kind not in {"replace", "insert", "delete"}:
        return None
    source = edit.source_paragraph or edit.quote or ""
    target = edit.target_paragraph or ""
    if not target:
        if edit.kind == "replace":
            target = (source or "").replace(edit.quote, edit.replacement, 1)
        elif edit.kind == "insert":
            target = f"{source} {edit.replacement}".strip()
        else:
            target = (source or "").replace(edit.quote, "", 1)
    if _glossary_regressed(cfg, source, target):
        return "broken_check"
    if _cite_regressed(full_text, source, target):
        return "broken_check"
    try:
        if _vale_regressed(cfg, source, target):
            return "broken_check"
    except OSError:
        return None
    return None


def filter_broken_edits(
    cfg: Config,
    edits: list[RewriteEdit],
    skips: list[dict[str, str]],
    *,
    full_text: str,
) -> list[RewriteEdit]:
    kept: list[RewriteEdit] = []
    for edit in edits:
        reason = edit_breaks_checks(cfg, edit, full_text=full_text)
        if reason:
            fid = (edit.finding_ids or [""])[0]
            skips.append({"finding_id": fid, "reason": reason})
            continue
        kept.append(edit)
    return kept
