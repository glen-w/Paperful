"""``paperful.critique.pack.v1``: findings, markdown, dismiss, orchestrator."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import Config
from .critique_extract import ExtractedDoc, extract_path, loc_of_span, stage_file
from .dedupe import scope_slug
from .store import write_json
from .zot import Item

SCHEMA = "paperful.critique.pack.v1"
CRITIQUE_PACK_KEYS = frozenset(
    {
        "schema",
        "input",
        "scope",
        "created_at",
        "counts",
        "findings",
        "overlap",
        "sections_used",
        "llm",
        "metrics",
    }
)
LANES = ("checked", "suggested")
SEVERITIES = ("info", "warn", "major")
_SEV_RANK = {"major": 0, "warn": 1, "info": 2}
_HYGIENE_CODES = frozenset(
    {
        "acronym_undefined",
        "acronym_expansion_mismatch",
        "acronym_phrase_mismatch",
        "long_sentence",
        "hedge_words",
        "passive_voice",
        "readability_summary",
        "lexical_diversity_summary",
        "ai_tell",
        "ai_tell_summary",
        "ai_tells_abstain",
    }
)
_AI_TELL_DISCLAIMER = (
    "These signals are associated with some LLM-style prose. They are **not proof** "
    "of AI authorship. Formal academic English (including ESL) often looks “smooth” "
    "on the same metrics. Do not use this pack for integrity proceedings."
)
_FORENSICS_INTRO = (
    "Anomalies to investigate from PaperGuard (external tool). "
    "Not a misconduct verdict and not a Paperful grade."
)


@dataclass
class Finding:
    id: str
    code: str
    lane: str  # checked | suggested
    severity: str  # info | warn | major
    loc: str
    quote: str
    source: str
    detail: str = ""
    dismissed: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        extra = row.pop("extra", {}) or {}
        if extra:
            row.update(extra)
        return row


def finding_id(code: str, loc: str, quote: str, detail: str = "") -> str:
    raw = f"{code}|{loc}|{(quote or '')[:120]}|{(detail or '')[:120]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def make_finding(
    *,
    code: str,
    severity: str,
    loc: str = "",
    quote: str = "",
    source: str = "rule",
    detail: str = "",
    lane: str = "checked",
    extra: dict[str, Any] | None = None,
) -> Finding:
    q = re.sub(r"\s+", " ", (quote or "").strip())[:200]
    d = re.sub(r"\s+", " ", (detail or "").strip())
    return Finding(
        id=finding_id(code, loc, q, d),
        code=code,
        lane=lane if lane in LANES else "checked",
        severity=severity if severity in SEVERITIES else "info",
        loc=loc,
        quote=q,
        source=source,
        detail=d,
        extra=dict(extra or {}),
    )


def critique_id(*, kind: str, item_key: str = "", original_name: str = "") -> str:
    """Stable id: item key, or ``file-<stem>`` so re-runs keep dismissals."""
    if kind == "item" and item_key:
        return item_key
    from .critique_extract import safe_filename

    stem = Path(safe_filename(original_name or "file")).stem.strip(".-") or "file"
    return f"file-{stem[:60]}"


def dismissed_path(cfg: Config, cid: str) -> Path:
    return cfg.state_dir / "critiques" / cid / "dismissed.jsonl"


def load_dismissed(cfg: Config, cid: str) -> set[str]:
    path = dismissed_path(cfg, cid)
    ids: set[str] = set()
    if not path.is_file():
        return ids
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                ids.add(line)
                continue
            if isinstance(row, dict) and row.get("id"):
                ids.add(str(row["id"]))
            elif isinstance(row, str):
                ids.add(row)
    except OSError:
        return ids
    return ids


def dismiss_finding(cfg: Config, cid: str, fid: str) -> Path:
    path = dismissed_path(cfg, cid)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "id": fid,
                    "at": datetime.now(tz=timezone.utc).isoformat(),
                }
            )
            + "\n"
        )
    return path


def apply_dismissals(findings: list[Finding], dismissed: set[str]) -> list[Finding]:
    for f in findings:
        if f.id in dismissed:
            f.dismissed = True
    return findings


def count_findings(findings: list[Finding]) -> dict[str, Any]:
    visible = [f for f in findings if not f.dismissed]
    by_code: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_lane: dict[str, int] = {}
    for f in visible:
        by_code[f.code] = by_code.get(f.code, 0) + 1
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        by_lane[f.lane] = by_lane.get(f.lane, 0) + 1
    return {
        "findings": len(visible),
        "dismissed": sum(1 for f in findings if f.dismissed),
        "by_code": by_code,
        "by_severity": by_severity,
        "by_lane": by_lane,
    }


def _fmt_metric(value: Any, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _render_metrics_md(metrics: dict[str, Any]) -> list[str]:
    from .critique_ai_tells import MIN_AI_TELL_WORDS

    lines = ["## Metrics", ""]
    lines.append(
        "Academic Flesch Reading Ease is often 0–30; that is expected, not a defect. "
        "TTR is length-sensitive — quote MTLD when it is present."
    )
    lines.append("")
    read = metrics.get("readability") or {}
    lex = metrics.get("lexical_diversity") or {}
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(
        f"| Flesch Reading Ease | {_fmt_metric(read.get('flesch_reading_ease'))} |"
    )
    lines.append(f"| Gunning Fog | {_fmt_metric(read.get('gunning_fog'))} |")
    lines.append(f"| ARI | {_fmt_metric(read.get('ari'))} |")
    lines.append(
        f"| Avg sentence length (words) | {_fmt_metric(read.get('avg_sentence_length'))} |"
    )
    lines.append(
        f"| Words / sentences | {read.get('word_count', 'n/a')} / "
        f"{read.get('sentence_count', 'n/a')} |"
    )
    lines.append(f"| TTR | {_fmt_metric(lex.get('ttr'), 3)} |")
    lines.append(f"| MTLD | {_fmt_metric(lex.get('mtld'), 1)} |")
    lines.append(f"| Hapax rate | {_fmt_metric(lex.get('hapax_rate'), 3)} |")
    lines.append(
        f"| Types / tokens | {lex.get('type_count', 'n/a')} / {lex.get('token_count', 'n/a')} |"
    )
    lines.append("")
    tells = metrics.get("ai_tells") or {}
    lines.append("### AI-prose signals")
    lines.append("")
    lines.append(_AI_TELL_DISCLAIMER)
    lines.append("")
    if tells.get("abstain"):
        lines.append(
            f"- Abstain: fewer than {MIN_AI_TELL_WORDS} words "
            f"({tells.get('word_count', 0)} tokens)."
        )
    else:
        lines.append(
            f"- Burstiness (sentence-length CV): {_fmt_metric(tells.get('burstiness_cv'), 2)}"
        )
        lines.append(f"- Tell-phrase hits: {tells.get('tell_phrase_total', 0)}")
        flags = list(tells.get("unicode_flags") or []) + list(
            tells.get("discourse") or []
        )
        if flags:
            lines.append(f"- Other flags: {', '.join(str(f) for f in flags)}")
    lines.append("")
    return lines


def _is_hygiene_finding(row: dict[str, Any]) -> bool:
    """True when the finding is polish noise, not a critical-path defect."""
    code = str(row.get("code") or "")
    if code.startswith("vale_"):
        return True
    return code in _HYGIENE_CODES


def _incomplete_lane_rows(llm: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Skipped review-lane ids and reasons for the pack.md banner."""
    if not isinstance(llm, dict) or not llm:
        return []
    rows: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(label: str, reason: str) -> None:
        name = str(label or "").strip() or "lane"
        why = str(reason or "").strip()
        if not why:
            return
        key = (name, why)
        if key in seen:
            return
        seen.add(key)
        rows.append(key)

    reviewer_skipped = False
    marg_reviewer_skip = False
    context_reviewer_skip = False
    adversary_reviewer_skip = False
    for raw in llm.get("reviewers") or []:
        if not isinstance(raw, dict) or not raw.get("skipped"):
            continue
        rid = str(raw.get("id") or "reviewer")
        add(rid, str(raw["skipped"]))
        reviewer_skipped = True
        if rid.startswith("marg"):
            marg_reviewer_skip = True
        if rid.startswith("context"):
            context_reviewer_skip = True
        if rid.startswith("adversary"):
            adversary_reviewer_skip = True
    if llm.get("skipped") and not reviewer_skipped:
        add("llm", str(llm["skipped"]))
    marg = llm.get("marg") if isinstance(llm.get("marg"), dict) else {}
    if marg.get("skipped") and not marg_reviewer_skip:
        add("marg", str(marg["skipped"]))
    ctx = llm.get("context") if isinstance(llm.get("context"), dict) else {}
    if ctx.get("skipped") and not context_reviewer_skip:
        add(str(ctx.get("id") or "context"), str(ctx["skipped"]))
    adv = llm.get("adversary") if isinstance(llm.get("adversary"), dict) else {}
    if adv.get("skipped") and not adversary_reviewer_skip:
        add("adversary", str(adv["skipped"]))
    return rows


def _render_incomplete_lanes(llm: dict[str, Any]) -> list[str]:
    rows = _incomplete_lane_rows(llm)
    if not rows:
        return []
    lines = ["## Incomplete lanes", ""]
    for label, reason in rows:
        lines.append(f"- `{label}`: {reason}")
    lines.append("")
    return lines


def _render_reviewer_notes(llm: dict[str, Any]) -> list[str]:
    reviewer_rows = [
        r
        for r in (llm.get("reviewers") or [])
        if isinstance(r, dict) and (r.get("narrative") or "").strip()
    ]
    if not reviewer_rows:
        narrative = (llm.get("narrative") or "").strip()
        if narrative:
            reviewer_rows = [
                {
                    "id": "reviewer",
                    "model": llm.get("model") or "",
                    "narrative": narrative,
                }
            ]
    if not reviewer_rows:
        return []
    heading = "Reviewer notes" if len(reviewer_rows) > 1 else "Reviewer note"
    lines = [f"## {heading}", ""]
    for row in reviewer_rows:
        model = row.get("model") or ""
        rid = row.get("id") or "reviewer"
        label = f"{rid} ({model})" if model else rid
        lines.append(f"### {label}")
        lines.append("")
        lines.append(str(row.get("narrative") or "").strip())
        lines.append("")
    return lines


def render_markdown(pack: dict[str, Any], *, show_dismissed: bool = False) -> str:
    counts = pack.get("counts") or {}
    inp = pack.get("input") or {}
    title = inp.get("title") or inp.get("item_key") or inp.get("path") or "manuscript"
    lines = [
        f"# Critique: {title}",
        "",
    ]
    llm = pack.get("llm") or {}
    if isinstance(llm, dict):
        lines.extend(_render_incomplete_lanes(llm))
        lines.extend(_render_reviewer_notes(llm))
    lines.extend(
        [
            "## Counts",
            "",
            f"- findings: {counts.get('findings', 0)}",
            f"- dismissed: {counts.get('dismissed', 0)}",
        ]
    )
    for label, key in (
        ("lane", "by_lane"),
        ("severity", "by_severity"),
        ("code", "by_code"),
    ):
        bucket = counts.get(key) or {}
        if bucket:
            parts = ", ".join(f"{k} {v}" for k, v in sorted(bucket.items()))
            lines.append(f"- {label}: {parts}")
    lines.append("")
    metrics = pack.get("metrics")
    if isinstance(metrics, dict) and metrics:
        lines.extend(_render_metrics_md(metrics))
    findings = list(pack.get("findings") or [])
    if not show_dismissed:
        findings = [f for f in findings if not f.get("dismissed")]
    hygiene = [f for f in findings if _is_hygiene_finding(f)]
    rest = [f for f in findings if not _is_hygiene_finding(f)]
    critical = [f for f in rest if f.get("lane") != "suggested"]
    suggested = [f for f in rest if f.get("lane") == "suggested"]
    critical.sort(
        key=lambda f: (
            _SEV_RANK.get(str(f.get("severity") or ""), 9),
            str(f.get("code") or ""),
        )
    )
    lines.extend(_section("Critical path", critical))
    if suggested:
        lines.extend(_section("Suggested", suggested))
    if pack.get("forensics") is not None:
        pg_rows = [f for f in findings if f.get("source") == "paperguard"]
        lines.extend(
            _section(
                "Forensics (PaperGuard)",
                pg_rows,
                intro=_FORENSICS_INTRO,
            )
        )
    if hygiene:
        lines.extend(_section("Hygiene", hygiene))
    overlap = pack.get("overlap") or []
    if overlap:
        lines.extend(["", "## Overlap spans", ""])
        for row in overlap:
            lines.append(
                f"- `{row.get('other_key')}` ({row.get('source')}): "
                f"“{row.get('ngram', '')[:120]}”"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _section(heading: str, rows: list[dict[str, Any]], *, intro: str = "") -> list[str]:
    out = ["", f"## {heading}", ""]
    if intro:
        out.append(intro)
        out.append("")
    if not rows:
        out.append("_None._")
        out.append("")
        return out
    for f in rows:
        loc = f.get("loc") or ""
        head = f"**{f.get('code')}** ({f.get('severity')}"
        if loc:
            head += f", {loc}"
        if f.get("dismissed"):
            head += ", dismissed"
        head += ")"
        out.append(f"- {head}: {f.get('detail') or f.get('quote') or ''}")
        if f.get("quote") and f.get("detail"):
            out.append(f"  > {f['quote']}")
    out.append("")
    return out


def write_pack(
    cfg: Config,
    *,
    cid: str,
    payload: dict[str, Any],
    stamp: str | None = None,
    show_dismissed: bool = False,
) -> Path:
    stamp = stamp or datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = cfg.state_dir / "critiques" / cid / stamp
    folder.mkdir(parents=True, exist_ok=True)
    payload.setdefault("schema", SCHEMA)
    payload["created_at"] = (
        payload.get("created_at") or datetime.now(tz=timezone.utc).isoformat()
    )
    write_json(folder / "pack.json", payload)
    (folder / "pack.md").write_text(
        render_markdown(payload, show_dismissed=show_dismissed), encoding="utf-8"
    )
    return folder


def latest_pack_dir(cfg: Config, cid: str) -> Path | None:
    root = cfg.state_dir / "critiques" / cid
    if not root.is_dir():
        return None
    dirs = sorted(
        (p for p in root.iterdir() if p.is_dir() and (p / "pack.json").is_file())
    )
    return dirs[-1] if dirs else None


def load_pack(folder: Path) -> dict[str, Any] | None:
    path = folder / "pack.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def build_critique(
    cfg: Config,
    *,
    item: Item | None = None,
    file_path: Path | None = None,
    collections: list[str] | None = None,
    library: bool = False,
    dry_run: bool = False,
    use_llm: bool = False,
    use_ai_model: bool = False,
    use_vale: bool = False,
    use_forensics: bool = False,
    use_advanced: bool = False,
    lanes: tuple[str, ...] | list[str] | None = None,
    use_grobid: bool = False,
    reviewer_ids: list[str] | None = None,
    force: bool = False,
    show_dismissed: bool = False,
    offline: bool = False,
    client: Any | None = None,
    llm_client: Any | None = None,
    backend: Any | None = None,
    scope_items: list[Item] | None = None,
    stage_uploads: bool = True,
    on_status: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run checkers and write a pack (unless ``dry_run``)."""
    from .critique_checks import run_checks
    from .critique_lanes import lanes_need_llm, ordered_lanes
    from .critique_llm import suggested_from_llm
    from .lint import resolve_pdf_path
    from .store import Manifest

    if lanes is None:
        shim: list[str] = []
        if use_llm:
            shim.append("reviewers")
        if use_advanced:
            shim.append("marg")
        lanes = tuple(shim)
    lanes = ordered_lanes(lanes)

    say = on_status or (lambda _msg: None)

    if bool(item) == bool(file_path):
        raise ValueError("pass exactly one of item or file_path")

    staged: Path | None = None
    src: Path | None = None
    kind = "item"
    item_key = ""
    title = ""
    fmt = ""
    if item is not None:
        kind = "item"
        item_key = item.key
        title = item.title or item.key
        manifest = Manifest(cfg.manifest_path)
        src = resolve_pdf_path(cfg, item, manifest)
        if src is None:
            say(f"No PDF on disk for {item_key}")
            doc = ExtractedDoc(text="", format="pdf", finding="no_file")
        else:
            say(f"Extracting {src.name}…")
            doc = extract_path(src)
            fmt = doc.format
    else:
        kind = "file"
        assert file_path is not None
        src = file_path
        original_name = file_path.name
        if stage_uploads:
            staged = stage_file(cfg, file_path)
            src = staged
        say(f"Extracting {original_name}…")
        doc = extract_path(src)
        fmt = doc.format
        title = original_name or src.name
        item_key = ""

    words = len((doc.text or "").split())
    say(f"Extracted {words:,} words ({fmt or doc.format or 'unknown'})")
    cid = critique_id(
        kind=kind,
        item_key=item_key,
        original_name=file_path.name if file_path is not None else "",
    )
    scope = _scope_label(collections, library, item)
    findings, overlap_rows, sections_used = run_checks(
        cfg,
        doc,
        item=item,
        collections=collections or [],
        library=library,
        offline=offline,
        client=client,
        backend=backend,
        scope_items=scope_items or [],
        force=force,
        on_status=on_status,
    )
    from .critique_ai_model import run_ai_model
    from .critique_ai_tells import compute_ai_tells
    from .critique_forensics import (
        persist_forensics_report,
        resolve_forensics_files,
        run_forensics,
    )
    from .critique_metrics import compute_style_metrics
    from .critique_vale import run_vale

    say("Metrics and heuristic AI-prose tells…")
    metrics = compute_style_metrics(doc.text or "")
    metrics["ai_tells"] = compute_ai_tells(doc.text or "", doc.paragraphs or None)
    vale_meta: dict[str, Any] | None = None
    if use_vale:
        say("Vale house-style pass…")
        vale_findings, vale_meta = run_vale(cfg, doc)
        findings.extend(vale_findings)
    ai_model_meta: dict[str, Any] | None = None
    if use_ai_model:
        say("AI-text model (Binoculars) on full extract…")
        ai_result = run_ai_model(doc.text or "")
        if ai_result is None:
            findings.append(
                make_finding(
                    code="ai_model_unavailable",
                    severity="info",
                    lane="suggested",
                    loc="document",
                    detail=(
                        "Optional AI-text model extra is not installed "
                        "(Binoculars / torch). Heuristic tells still ran."
                    ),
                    source="ai_model",
                )
            )
            ai_model_meta = {"skipped": "unavailable"}
        else:
            findings.append(
                make_finding(
                    code="ai_tell_summary",
                    severity="info",
                    lane="suggested",
                    loc="model",
                    detail=(
                        f"{ai_result.get('backend')} score "
                        f"{ai_result.get('score')}. "
                        "Not proof of AI authorship; do not use for integrity proceedings."
                    ),
                    source="ai_model",
                )
            )
            ai_model_meta = ai_result
    forensics_meta: dict[str, Any] | None = None
    forensics_raw: str | None = None
    if use_forensics:
        say("PaperGuard forensics (subprocess)…")
        scan_files = resolve_forensics_files(src, item_mode=item is not None)
        doi = ""
        if item is not None and not offline:
            doi = str(getattr(item, "doi", None) or "").strip()
        pg_findings, forensics_meta, forensics_raw = run_forensics(
            cfg,
            files=scan_files,
            doi=doi or None,
            offline=offline,
        )
        findings.extend(pg_findings)

    llm_meta: dict[str, Any] | None = None
    if lanes_need_llm(lanes):
        pdf = src if src is not None and src.suffix.lower() == ".pdf" else None
        extra, llm_meta = suggested_from_llm(
            cfg,
            doc,
            findings,
            item=item,
            client=llm_client,
            force=force,
            metrics=metrics,
            reviewer_ids=reviewer_ids,
            lanes=lanes,
            use_grobid=use_grobid,
            pdf_path=pdf,
            offline=offline,
            scope_items=scope_items or [],
            on_status=on_status,
        )
        findings.extend(extra)

    dismissed = load_dismissed(cfg, cid)
    apply_dismissals(findings, dismissed)
    if not show_dismissed:
        # JSON keeps dismissed rows; markdown omits them in render_markdown.
        pass

    inp: dict[str, Any] = {
        "kind": kind,
        "item_key": item_key,
        "title": title,
        "format": fmt or doc.format,
        "path": str(src) if src else "",
        "staged_path": str(staged) if staged else "",
        "extract": doc.finding,
    }
    payload = {
        "schema": SCHEMA,
        "input": inp,
        "scope": scope,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "counts": count_findings(findings),
        "findings": [f.to_dict() for f in findings],
        "overlap": overlap_rows,
        "sections_used": sections_used,
        "llm": llm_meta,
        "metrics": metrics,
    }
    if ai_model_meta is not None:
        payload["ai_model"] = ai_model_meta
    if vale_meta is not None:
        payload["vale"] = vale_meta
    if forensics_meta is not None:
        payload["forensics"] = forensics_meta
    folder: Path | None = None
    if not dry_run:
        say("Writing pack…")
        folder = write_pack(
            cfg, cid=cid, payload=payload, show_dismissed=show_dismissed
        )
        if forensics_raw and forensics_meta is not None:
            dest = persist_forensics_report(folder, forensics_raw)
            forensics_meta["report_path"] = str(dest)
            payload["forensics"] = forensics_meta
            write_json(folder / "pack.json", payload)
        payload["pack_dir"] = str(folder)
    payload["critique_id"] = cid
    payload["_findings"] = findings
    payload["_doc"] = doc
    return payload


def _scope_label(
    collections: list[str] | None, library: bool, item: Item | None
) -> str:
    if library:
        return "library"
    if collections:
        return ",".join(collections)
    if item is not None and item.collection_paths:
        return item.collection_paths[0]
    return ""


def note_html(pack: dict[str, Any]) -> str:
    from html import escape

    from .notehtml import wrap

    counts = pack.get("counts") or {}
    visible = [f for f in pack.get("findings") or [] if not f.get("dismissed")]
    checked = [f for f in visible if f.get("lane") != "suggested"]
    lines = [
        "<p>Critique pack from <code>paperful critique</code>.</p>",
        f"<p>Findings: {counts.get('findings', 0)} "
        f"(checked {(counts.get('by_lane') or {}).get('checked', 0)}, "
        f"suggested {(counts.get('by_lane') or {}).get('suggested', 0)}).</p>",
        "<ul>",
    ]
    for f in checked[:40]:
        loc = escape(str(f.get("loc") or ""))
        code = escape(str(f.get("code") or ""))
        detail = escape(str(f.get("detail") or f.get("quote") or ""))
        loc_bit = f" ({loc})" if loc else ""
        lines.append(f"<li><strong>{code}</strong>{loc_bit}: {detail}</li>")
    lines.append("</ul>")
    extra = f"{counts.get('findings', 0)} findings"
    return wrap("\n".join(lines), note_type="critique", verb="critique", extra=extra)
