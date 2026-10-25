"""``paperful.critique.pack.v1``: findings, markdown, dismiss, orchestrator."""

from __future__ import annotations

import hashlib
import json
import re
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
    }
)
LANES = ("checked", "suggested")
SEVERITIES = ("info", "warn", "major")


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


def render_markdown(pack: dict[str, Any], *, show_dismissed: bool = False) -> str:
    counts = pack.get("counts") or {}
    inp = pack.get("input") or {}
    title = inp.get("title") or inp.get("item_key") or inp.get("path") or "manuscript"
    lines = [
        f"# Critique: {title}",
        "",
        "Pre-submission / reading-aid pack. Not a referee report and not a grade.",
        "",
        "## Counts",
        "",
        f"- findings: {counts.get('findings', 0)}",
        f"- dismissed: {counts.get('dismissed', 0)}",
    ]
    for label, key in (("lane", "by_lane"), ("severity", "by_severity"), ("code", "by_code")):
        bucket = counts.get(key) or {}
        if bucket:
            parts = ", ".join(f"{k} {v}" for k, v in sorted(bucket.items()))
            lines.append(f"- {label}: {parts}")
    lines.append("")
    findings = list(pack.get("findings") or [])
    if not show_dismissed:
        findings = [f for f in findings if not f.get("dismissed")]
    checked = [f for f in findings if f.get("lane") != "suggested"]
    suggested = [f for f in findings if f.get("lane") == "suggested"]
    lines.extend(_section("Checked", checked))
    if suggested:
        lines.extend(_section("Suggested", suggested))
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


def _section(heading: str, rows: list[dict[str, Any]]) -> list[str]:
    out = ["", f"## {heading}", ""]
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
    payload["created_at"] = payload.get("created_at") or datetime.now(
        tz=timezone.utc
    ).isoformat()
    write_json(folder / "pack.json", payload)
    (folder / "pack.md").write_text(
        render_markdown(payload, show_dismissed=show_dismissed), encoding="utf-8"
    )
    return folder


def latest_pack_dir(cfg: Config, cid: str) -> Path | None:
    root = cfg.state_dir / "critiques" / cid
    if not root.is_dir():
        return None
    dirs = sorted((p for p in root.iterdir() if p.is_dir() and (p / "pack.json").is_file()))
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
    force: bool = False,
    show_dismissed: bool = False,
    offline: bool = False,
    client: Any | None = None,
    llm_client: Any | None = None,
    backend: Any | None = None,
    scope_items: list[Item] | None = None,
    stage_uploads: bool = True,
) -> dict[str, Any]:
    """Run checkers and write a pack (unless ``dry_run``)."""
    from .critique_checks import run_checks
    from .critique_llm import suggested_from_llm
    from .lint import resolve_pdf_path
    from .store import Manifest

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
            doc = ExtractedDoc(text="", format="pdf", finding="no_file")
        else:
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
        doc = extract_path(src)
        fmt = doc.format
        title = original_name or src.name
        item_key = ""

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
    )
    llm_meta: dict[str, Any] | None = None
    if use_llm:
        extra, llm_meta = suggested_from_llm(
            cfg,
            doc,
            findings,
            item=item,
            client=llm_client,
            force=force,
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
    }
    folder: Path | None = None
    if not dry_run:
        folder = write_pack(
            cfg, cid=cid, payload=payload, show_dismissed=show_dismissed
        )
        payload["pack_dir"] = str(folder)
    payload["critique_id"] = cid
    payload["_findings"] = findings
    payload["_doc"] = doc
    return payload


def _scope_label(collections: list[str] | None, library: bool, item: Item | None) -> str:
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
        "<p>Critique pack from <code>paperful critique</code>. "
        "Checked rows are deterministic; suggested rows (if any) are a model. "
        "Not a referee report.</p>",
        f"<p>Findings: {counts.get('findings', 0)} "
        f"(checked { (counts.get('by_lane') or {}).get('checked', 0) }, "
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
