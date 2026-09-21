"""End-of-run summary and auditable run reports on disk."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from .config import Config

_ENRICH_MATCH = re.compile(
    r"^(?P<source>crossref|openalex|semanticscholar|pubmed|url|meta|arxiv):matched"
)
_SWAP = re.compile(r"^swap:")
_VERIFY_OK = re.compile(r"^verify:ok")


@dataclass
class ItemOutcome:
    itemKey: str
    title: str
    status: str
    source: str | None = None
    reason: str = ""
    doi: str | None = None
    doi_verified: str = ""
    attempts: list[str] = field(default_factory=list)
    fields_corrected: list[str] = field(default_factory=list)
    path: str | None = None
    error_type: str | None = None


def classify_enrichment(notes: list[str]) -> list[str]:
    """Map prepare_identifiers notes to field-correction labels for this item."""
    labels: list[str] = []
    for note in notes:
        if _SWAP.match(note):
            labels.append("doi_swap")
        elif _VERIFY_OK.match(note):
            labels.append("doi_verified")
        else:
            m = _ENRICH_MATCH.match(note)
            if m:
                labels.append(f"doi_{m.group('source')}")
    # Preserve order, drop duplicates
    seen: set[str] = set()
    out: list[str] = []
    for lab in labels:
        if lab not in seen:
            seen.add(lab)
            out.append(lab)
    return out


def bump_nested(
    counter: dict[str, dict[str, int]], outer: str, inner: str, n: int = 1
) -> None:
    bucket = counter.setdefault(outer, {})
    bucket[inner] = bucket.get(inner, 0) + n


def bump(counter: dict[str, int], key: str, n: int = 1) -> None:
    counter[key] = counter.get(key, 0) + n


def error_type_for(
    status: str, reason: str = "", attach_code: str | None = None
) -> str | None:
    """Typed error label for summary/report; None when the outcome is not an error."""
    if status == "attach_failed":
        return f"attach:{attach_code or 'other'}"
    if status == "captcha":
        return "captcha"
    if status == "error":
        if reason:
            # keep short stable keys
            cleaned = re.sub(r"\s+", "_", reason.strip().lower())[:60]
            return f"error:{cleaned}" if cleaned else "error"
        return "error"
    return None


def build_report(
    stats: Any,
    cfg: Config,
    *,
    command: str = "run",
    scope: str = "",
    flags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a JSON-serialisable audit report from RunStats (or compatible)."""
    started = getattr(stats, "started_at", 0) or 0
    finished = getattr(stats, "finished_at", 0) or time.time()
    # `ok` is bumped on every successful download; `attached` is a later step on the same items.
    downloaded = int(getattr(stats, "ok", 0))
    fields = dict(getattr(stats, "fields_corrected", {}) or {})
    # doi_verified is hygiene, not a correction — keep in report but split for summary clarity
    corrections = {k: v for k, v in fields.items() if k != "doi_verified"}
    verified = int(fields.get("doi_verified", 0))

    items = getattr(stats, "items", []) or []
    item_dicts = [
        asdict(i) if hasattr(i, "__dataclass_fields__") else dict(i) for i in items
    ]

    return {
        "schema": "paperful.run_report.v1",
        "command": command,
        "started_at": (
            datetime.fromtimestamp(started, tz=timezone.utc).isoformat()
            if started
            else None
        ),
        "finished_at": datetime.fromtimestamp(finished, tz=timezone.utc).isoformat(),
        "duration_s": round(finished - started, 2) if started else None,
        "scope": scope or getattr(stats, "scope", ""),
        "sources_configured": list(getattr(stats, "sources_configured", []) or []),
        "flags": flags or {},
        "paths": {
            "out_dir": str(cfg.out_dir),
            "manifest": str(cfg.manifest_path),
            "state_dir": str(cfg.state_dir),
        },
        "summary": {
            "processed": len(item_dicts)
            or (
                int(getattr(stats, "ok", 0))
                + int(getattr(stats, "not_found", 0))
                + int(getattr(stats, "no_identifier", 0))
                + int(getattr(stats, "captcha", 0))
                + int(getattr(stats, "error", 0))
                + int(getattr(stats, "attach_failed", 0))
                # attached is a subset of ok (download then attach); do not double-count
            ),
            "pdfs_downloaded": downloaded,
            "attached": int(getattr(stats, "attached", 0)),
            "attach_failed": int(getattr(stats, "attach_failed", 0)),
            "not_found": int(getattr(stats, "not_found", 0)),
            "no_identifier": int(getattr(stats, "no_identifier", 0)),
            "captcha": int(getattr(stats, "captcha", 0)),
            "error": int(getattr(stats, "error", 0)),
            "skipped_manifest": int(getattr(stats, "skipped_manifest", 0)),
            "linked_url_skipped": int(getattr(stats, "linked_url_skipped", 0)),
            "fields_corrected": sum(corrections.values()),
            "fields_corrected_by_kind": corrections,
            "identifiers_verified": verified,
            "by_source": dict(getattr(stats, "by_source", {}) or {}),
            "sources_checked": dict(getattr(stats, "sources_checked", {}) or {}),
            "errors_by_type": dict(getattr(stats, "errors_by_type", {}) or {}),
            "attach_failed_by_code": dict(
                getattr(stats, "attach_failed_by_code", {}) or {}
            ),
        },
        "items": item_dicts,
    }


def write_run_report(
    cfg: Config, report: dict[str, Any], *, as_last_run: bool = True
) -> Path | None:
    """Write `state/runs/<stamp>.json` and optionally refresh `state/last-run.json`."""
    try:
        runs_dir = cfg.state_dir / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        cmd = str(report.get("command") or "run")
        path = runs_dir / f"{stamp}-{cmd}.json"
        text = json.dumps(report, indent=2, ensure_ascii=False)
        path.write_text(text)
        if as_last_run:
            (cfg.state_dir / "last-run.json").write_text(text)
        from .pack import note_pack_step

        note_pack_step(cfg, report, path)
        return path
    except OSError:
        return None


def write_command_report(
    cfg: Config,
    *,
    command: str,
    scope: str,
    summary: dict[str, Any],
    items: list[dict[str, Any]],
    flags: dict[str, Any] | None = None,
    started: float | None = None,
    finished: float | None = None,
    errors: list[str] | None = None,
    extra_paths: dict[str, str] | None = None,
) -> Path | None:
    """Write a `paperful.run_report.v1` file without replacing `last-run.json`."""
    finished_ts = finished if finished is not None else time.time()
    paths = {
        "out_dir": str(cfg.out_dir),
        "manifest": str(cfg.manifest_path),
        "state_dir": str(cfg.state_dir),
    }
    if extra_paths:
        paths.update(extra_paths)
    report: dict[str, Any] = {
        "schema": "paperful.run_report.v1",
        "command": command,
        "started_at": (
            datetime.fromtimestamp(started, tz=timezone.utc).isoformat()
            if started
            else None
        ),
        "finished_at": datetime.fromtimestamp(finished_ts, tz=timezone.utc).isoformat(),
        "duration_s": round(finished_ts - started, 2) if started else None,
        "scope": scope,
        "flags": flags or {},
        "paths": paths,
        "summary": summary,
        "items": items,
    }
    if errors is not None:
        report["errors"] = errors
    return write_run_report(cfg, report, as_last_run=False)


def print_run_summary(
    console: Console, report: dict[str, Any], report_path: Path | None = None
) -> None:
    """Human-readable end-of-run / last-run summary."""
    s = report.get("summary") or {}
    console.print()
    title = Table(title="Run summary", show_header=False, box=None, padding=(0, 2))
    title.add_column("k", style="bold")
    title.add_column("v")

    downloaded = s.get("pdfs_downloaded", 0)
    title.add_row("PDFs downloaded", str(downloaded))
    title.add_row(
        "Attached", f"{s.get('attached', 0)}  (failed {s.get('attach_failed', 0)})"
    )
    title.add_row(
        "Fields corrected",
        _fmt_fields(
            s.get("fields_corrected", 0), s.get("fields_corrected_by_kind") or {}
        ),
    )
    verified = s.get("identifiers_verified", 0)
    if verified:
        title.add_row("Identifiers verified", str(verified))
    title.add_row(
        "Sources checked", _fmt_sources_checked(s.get("sources_checked") or {})
    )
    title.add_row("Errors", _fmt_errors(s.get("errors_by_type") or {}))
    deferred = (
        int(s.get("skipped_manifest", 0))
        + int(s.get("linked_url_skipped", 0))
        + int(s.get("not_found", 0))
        + int(s.get("no_identifier", 0))
    )
    title.add_row(
        "Deferred / skipped",
        (
            f"{deferred}  "
            f"(manifest {s.get('skipped_manifest', 0)}, "
            f"linked-url {s.get('linked_url_skipped', 0)}, "
            f"not_found {s.get('not_found', 0)}, "
            f"no_identifier {s.get('no_identifier', 0)})"
        ),
    )
    console.print(title)

    by_src = s.get("by_source") or {}
    if by_src:
        console.print(
            "PDFs by source: "
            + ", ".join(
                f"{k}={v}"
                for k, v in sorted(by_src.items(), key=lambda kv: (-kv[1], kv[0]))
            )
        )
    attach_codes = s.get("attach_failed_by_code") or {}
    if attach_codes:
        console.print(
            "Attach failures: "
            + ", ".join(f"{k}={v}" for k, v in sorted(attach_codes.items()))
        )
    if report.get("command") == "run" and s.get("fields_corrected"):
        console.print(
            "[dim]Field corrections above are in-memory DOI enrichments for this run; "
            "use fix-metadata --apply to write them into the library.[/]"
        )

    paths = report.get("paths") or {}
    if report_path:
        console.print(f"[dim]Run report: {report_path}[/]")
    console.print(
        f"[dim]PDFs: {paths.get('out_dir', '')}   manifest: {paths.get('manifest', '')}[/]"
    )


def _fmt_fields(total: int, by_kind: dict[str, int]) -> str:
    if not total:
        return "0"
    parts = ", ".join(
        f"{k}={v}" for k, v in sorted(by_kind.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    return f"{total}  ({parts})" if parts else str(total)


def _fmt_sources_checked(checked: dict[str, dict[str, int]]) -> str:
    if not checked:
        return "0"
    totals = []
    grand = 0
    for src, outcomes in sorted(checked.items()):
        n = sum(outcomes.values())
        grand += n
        found = outcomes.get("found", 0)
        totals.append(f"{src}={n}" + (f"({found} hit)" if found else ""))
    return f"{grand} checks  (" + ", ".join(totals) + ")"


def _fmt_errors(errors: dict[str, int]) -> str:
    if not errors:
        return "0"
    total = sum(errors.values())
    parts = ", ".join(
        f"{k}={v}" for k, v in sorted(errors.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    return f"{total}  ({parts})"
