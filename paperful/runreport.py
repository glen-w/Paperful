"""End-of-run summary and auditable run reports on disk."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from .config import Config
from .page_signals import classify_page_block, miss_label
from .quotes import price_token_in

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


# Required on every object from build_report(). Extra keys may be added.
RUN_REPORT_KEYS = frozenset(
    {
        "schema",
        "command",
        "started_at",
        "finished_at",
        "duration_s",
        "scope",
        "sources_configured",
        "flags",
        "paths",
        "summary",
        "items",
    }
)
RUN_REPORT_SUMMARY_KEYS = frozenset(
    {
        "processed",
        "pdfs_downloaded",
        "attached",
        "attach_failed",
        "not_found",
        "no_identifier",
        "captcha",
        "error",
        "skipped_manifest",
        "linked_url_skipped",
        "fields_corrected",
        "fields_corrected_by_kind",
        "identifiers_verified",
        "by_source",
        "sources_checked",
        "errors_by_type",
        "attach_failed_by_code",
        "write_api",
    }
)
RUN_REPORT_PATH_KEYS = frozenset({"out_dir", "manifest", "state_dir"})
RUN_REPORT_ITEM_KEYS = frozenset(
    {
        "itemKey",
        "title",
        "status",
        "source",
        "reason",
        "doi",
        "doi_verified",
        "attempts",
        "fields_corrected",
        "path",
        "error_type",
    }
)


def _attempt_note(attempt: str, prefix: str) -> str | None:
    if not attempt.startswith(prefix) or not attempt.endswith(")"):
        return None
    return attempt[len(prefix) : -1]


# One reason per item that did not yield a PDF. A page block beats a plain miss.
_SAVED_STATUSES = frozenset({"ok", "attached", "attach_failed"})
_WALLS = frozenset({"captcha", "cloudflare", "blocked", "paywall", "login"})
_MISS_ORDER = (
    "captcha",
    "cloudflare",
    "blocked",
    "paywall",
    "login",
    "session_expired",
    "paused",
    "download_failed",
    "step_budget",
    "no_identifier",
    "error",
    "not_found",
)
_MISS_LABELS = {
    "session_expired": "session expired",
    "download_failed": "download failed",
    "step_budget": "step budget",
    "no_identifier": "no identifier",
    "not_found": "not found",
}


def _attempt_reasons(attempt: str) -> set[str]:
    """Block and failure labels carried by one source attempt."""
    reasons: set[str] = set()
    _name, sep, rest = attempt.partition(":")
    outcome = rest.split("(", 1)[0] if sep else ""
    if outcome == "captcha":
        reasons.add("captcha")
    note = ""
    if attempt.endswith(")") and "(" in attempt:
        note = attempt[attempt.find("(") + 1 : -1]
    head = miss_label(note) if note else ""
    if head in _WALLS:
        reasons.add(head)
    elif head == "step budget":
        reasons.add("step_budget")
    elif note:
        # The source name is not page text (`unpaywall` contains "paywall").
        label = classify_page_block(note)
        if label:
            reasons.add(label)
    if "session expired" in attempt:
        reasons.add("session_expired")
    if "circuit open" in attempt:
        reasons.add("paused")
    if "download-failed" in attempt:
        reasons.add("download_failed")
    return reasons


def item_miss_reason(item: dict[str, Any]) -> str | None:
    """Why this item has no PDF, or None when a PDF was saved.

    One label. Captcha, Cloudflare, and the other page blocks win over
    ``not_found``, which is what the ledger stores after every source misses.
    """
    status = str(item.get("status") or "")
    if not status or status in _SAVED_STATUSES:
        return None
    found: set[str] = set()
    for attempt in item.get("attempts") or []:
        found |= _attempt_reasons(str(attempt))
    if status == "captcha":
        found.add("captcha")
    if status == "no_identifier":
        found.add("no_identifier")
    if status == "error":
        found.add("error")
    if status == "retryable" and "session_expired" not in found:
        found.add("paused")
    if status == "not_found":
        found.add("not_found")
    for reason in _MISS_ORDER:
        if reason in found:
            return reason
    return status


def not_downloaded_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    """Count items with no PDF, one reason each."""
    counts: dict[str, int] = {}
    for item in items:
        reason = item_miss_reason(item)
        if not reason:
            continue
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def paywall_price_totals(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Sum publisher prices on items that were not saved, one price each.

    Currencies stay separate. ``total`` is a two-decimal string.
    """
    totals: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status") or "")
        if not status or status in _SAVED_STATUSES:
            continue
        quote = None
        for attempt in item.get("attempts") or []:
            quote = price_token_in(str(attempt))
            if quote is not None:
                break
        if quote is None:
            continue
        amount, currency = quote
        totals[currency] = totals.get(currency, Decimal("0")) + amount
        counts[currency] = counts.get(currency, 0) + 1
    return {
        currency: {"articles": counts[currency], "total": f"{amount:.2f}"}
        for currency, amount in sorted(totals.items())
    }


def _browser_miss_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    """Bucket ``browser_agent:not_found(...)`` notes by page label."""
    counts: dict[str, int] = {}
    for item in items:
        for attempt in item.get("attempts") or []:
            note = _attempt_note(attempt, "browser_agent:not_found(")
            if note is None:
                continue
            label = miss_label(note)
            counts[label] = counts.get(label, 0) + 1
    return counts


def _agent_after_playwright(items: list[dict[str, Any]]) -> int:
    """Hits where the agent note records a prior Playwright miss."""
    n = 0
    for item in items:
        for attempt in item.get("attempts") or []:
            note = _attempt_note(attempt, "browser_agent:found(")
            if note and "; after " in note:
                n += 1
    return n


def low_download_advice(*, downloaded: int, sought: int, collection: str = "") -> str | None:
    """What to do next when a fetch saved few PDFs for the items it tried.

    Small runs stay quiet. Under a quarter saved, on eight or more items, is low.
    """
    if sought < 8 or downloaded * 4 >= sought:
        return None
    target = collection.strip()
    retry = (
        f'paperful run -C "{target}" --retry-failed'
        if target
        else "paperful run --retry-failed"
    )
    return (
        "Few PDFs for this many items. Open access plus a live proxy session "
        "is what fills recent papers. Sci-Hub stops for the rest of a run after "
        "captchas, and papers dated after 2021 are not sent there.\n"
        "  paperful session login ezproxy\n"
        "  paperful session login scholar\n"
        f"  {retry}"
    )


def outcome_banner(summary: dict[str, Any]) -> str:
    """Locked one-line end-of-run banner."""
    downloaded = int(summary.get("pdfs_downloaded") or 0)
    attached = int(summary.get("attached") or 0)
    deferred = int(summary.get("skipped_manifest") or 0) + int(
        summary.get("linked_url_skipped") or 0
    )
    not_found = int(summary.get("not_found") or 0)
    write = summary.get("write_api")
    if write is True:
        api = "yes"
    elif write is False:
        api = "no"
    else:
        api = "unknown"
    return (
        f"downloaded {downloaded} · attached {attached} · deferred {deferred} "
        f"· not_found {not_found} · write-api {api}"
    )


def build_report(
    stats: Any,
    cfg: Config,
    *,
    command: str = "run",
    scope: str = "",
    flags: dict[str, Any] | None = None,
    write_api: bool | None = None,
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
                + int(getattr(stats, "retryable", 0))
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
            "retryable": int(getattr(stats, "retryable", 0)),
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
            "browser_misses": _browser_miss_counts(item_dicts),
            "not_downloaded": not_downloaded_counts(item_dicts),
            "paywall_prices": paywall_price_totals(item_dicts),
            "agent_after_playwright": _agent_after_playwright(item_dicts),
            "write_api": write_api,
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
    summary.setdefault("write_api", None)
    return write_run_report(cfg, report, as_last_run=False)


def print_run_summary(
    console: Console, report: dict[str, Any], report_path: Path | None = None
) -> None:
    """Human-readable end-of-run / last-run summary."""
    s = report.get("summary") or {}
    console.print()
    console.print(f"[bold]{outcome_banner(s)}[/]")
    title = Table(title="Run summary", show_header=False, box=None, padding=(0, 2))
    title.add_column("k", style="bold")
    title.add_column("v")

    downloaded = s.get("pdfs_downloaded", 0)
    title.add_row("PDFs downloaded", str(downloaded))
    title.add_row(
        "Attached", f"{s.get('attached', 0)}  (failed {s.get('attach_failed', 0)})"
    )
    missed = s.get("not_downloaded")
    if not isinstance(missed, dict):
        missed = not_downloaded_counts(report.get("items") or [])
    if any(int(v or 0) for v in missed.values()):
        title.add_row("Not downloaded", _fmt_not_downloaded(missed))
    quotes = s.get("paywall_prices")
    if not isinstance(quotes, dict):
        quotes = paywall_price_totals(report.get("items") or [])
    if quotes:
        title.add_row("To buy", _fmt_paywall_prices(quotes))
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

    misses = s.get("browser_misses") or {}
    if misses:
        console.print(
            "Browser misses: "
            + ", ".join(
                f"{k}={v}"
                for k, v in sorted(misses.items(), key=lambda kv: (-kv[1], kv[0]))
            )
        )
    after = int(s.get("agent_after_playwright") or 0)
    if after:
        console.print(f"Agent PDFs after a Playwright miss: {after}")

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
    if int(attach_codes.get("quota") or 0) > 0:
        console.print(
            "Quota: PDFs are in out/. Free Zotero Storage or empty the trash, "
            "then paperful attach."
        )
    saved = int(s.get("attached") or 0) or int(s.get("pdfs_downloaded") or 0)
    sought = (
        saved
        + int(s.get("not_found") or 0)
        + int(s.get("captcha") or 0)
        + int(s.get("error") or 0)
        + int(s.get("no_identifier") or 0)
        + int(s.get("attach_failed") or 0)
    )
    advice = low_download_advice(
        downloaded=saved,
        sought=sought,
        collection=str(report.get("scope") or ""),
    )
    if advice:
        console.print(f"[yellow]{advice}[/]")
    if int(misses.get("ezproxy") or 0) > 0 or int(missed.get("session_expired") or 0) > 0:
        console.print(
            "EZProxy misses: run `uv run paperful session login ezproxy` on the host "
            "(not inside the container), then retry."
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


_MONEY = {"EUR": "€", "USD": "$", "GBP": "£"}


def _fmt_paywall_prices(prices: dict[str, Any]) -> str:
    ranked = sorted(
        prices.items(),
        key=lambda kv: (-int((kv[1] or {}).get("articles") or 0), kv[0]),
    )
    parts: list[str] = []
    for currency, info in ranked:
        if not isinstance(info, dict):
            continue
        articles = int(info.get("articles") or 0)
        total = str(info.get("total") or "")
        if articles <= 0 or not total:
            continue
        try:
            shown = f"{Decimal(total):,.2f}"
        except Exception:
            shown = total
        symbol = _MONEY.get(currency)
        money = f"{symbol}{shown}" if symbol else f"{shown} {currency}"
        noun = "article" if articles == 1 else "articles"
        parts.append(f"{money} for {articles} {noun}")
    return ", ".join(parts)


def _fmt_not_downloaded(counts: dict[str, int]) -> str:
    total = sum(int(v or 0) for v in counts.values())
    parts = ", ".join(
        f"{_MISS_LABELS.get(k, k)} {int(v)}"
        for k, v in sorted(
            ((k, v) for k, v in counts.items() if int(v or 0)),
            key=lambda kv: (-int(kv[1]), kv[0]),
        )
    )
    return f"{total}  ({parts})" if parts else "0"


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
