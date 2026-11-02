"""``paperful sr`` — systematic review protocol and screening (local, no scheduler)."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from .config_check import check_config
from .fsio import atomic_write_text
from .sr.exchange import (
    apply_import,
    create_included_parents,
    export_text,
    parse_import,
)
from .sr.identify import identified_ids, load_identification
from .sr.prisma import counts_hold, prisma_counts, prisma_payload, prisma_svg
from .sr.protocol import load_protocol, save_protocol
from .sr.screen import append_screen_decision, latest_decisions, load_screen_ledger

console = Console()


def run_sr_init(
    cfg,
    *,
    slug: str,
    title: str,
    question: str,
    snowball_run: str = "",
    search_run: str = "",
    exclude_reasons: list[str] | None = None,
) -> int:
    existing = load_protocol(cfg.state_dir, slug)
    save_protocol(
        cfg.state_dir,
        slug,
        {
            "title": title or existing.get("title") or "",
            "question": question or existing.get("question") or "",
            "exclude_reasons": (
                exclude_reasons
                if exclude_reasons is not None
                else list(existing.get("exclude_reasons") or [])
            ),
            "snowball_run": snowball_run or existing.get("snowball_run") or "",
            "search_run": search_run or existing.get("search_run") or "",
        },
    )
    console.print(f"Wrote protocol under state/sr/{slug}/")
    return 0


def run_sr_screen(
    cfg,
    *,
    slug: str,
    identity: str,
    decision: str,
    reason: str,
    reviewer: str,
) -> int:
    append_screen_decision(
        cfg.state_dir,
        slug,
        identity=identity,
        decision=decision,
        reason=reason,
        reviewer=reviewer or "operator",
    )
    console.print(f"Recorded {decision} for {identity}")
    return 0


def exclude_histogram(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if row.get("decision") != "exclude":
            continue
        key = str(row.get("reason") or "")
        counts[key] = counts.get(key, 0) + 1
    return counts


def review_counts(cfg, slug: str) -> dict[str, int]:
    protocol = load_protocol(cfg.state_dir, slug)
    decisions = latest_decisions(load_screen_ledger(cfg.state_dir, slug))
    identified = identified_ids(load_identification(cfg.state_dir, protocol))
    included = excluded = maybe = 0
    for row in decisions.values():
        label = str(row.get("decision") or "")
        if label == "include":
            included += 1
        elif label == "exclude":
            excluded += 1
        elif label == "maybe":
            maybe += 1
    counts = prisma_counts(
        len(identified),
        included=included,
        excluded=excluded,
        maybe=maybe,
    )
    if not counts_hold(counts):
        raise RuntimeError("PRISMA counts do not add up")
    return counts


def run_sr_status(cfg, *, slug: str) -> int:
    protocol = load_protocol(cfg.state_dir, slug)
    counts = review_counts(cfg, slug)
    from .sr.protocol import review_dir

    dest = review_dir(cfg.state_dir, slug)
    dest.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        dest / "prisma.svg",
        prisma_svg(counts, title=str(protocol.get("title") or slug)),
    )
    atomic_write_text(
        dest / "prisma.json",
        json.dumps(prisma_payload(counts), indent=2) + "\n",
    )
    console.print(
        f"Review {slug}: {protocol.get('title') or protocol.get('question') or '(no title)'}"
    )
    console.print(
        "PRISMA "
        f"identified {counts['identified']} · screened {counts['screened']} · "
        f"included {counts['included']} · excluded {counts['excluded']} · "
        f"maybe {counts['maybe']} · pending {counts['pending']}"
    )
    hist = exclude_histogram(load_screen_ledger(cfg.state_dir, slug))
    if hist:
        parts = [f"{reason} {n}" for reason, n in sorted(hist.items())]
        console.print("Exclude reasons: " + " · ".join(parts))
    return 0


def run_sr_export(cfg, *, slug: str, fmt: str, only_included: bool = True) -> int:
    protocol = load_protocol(cfg.state_dir, slug)
    rows = load_identification(cfg.state_dir, protocol)
    decisions = latest_decisions(load_screen_ledger(cfg.state_dir, slug))
    text = export_text(rows, fmt=fmt, decisions=decisions, only_included=only_included)
    console.print(text, end="" if text.endswith("\n") or not text else "\n")
    return 0


def run_sr_import(
    cfg,
    *,
    slug: str,
    path: str,
    fmt: str,
    apply: bool,
    reviewer: str,
    collection: str = "",
) -> int:
    body = Path(path).read_text(encoding="utf-8")
    parsed = parse_import(body, fmt=fmt)
    result = apply_import(
        cfg.state_dir,
        slug,
        parsed,
        reviewer=reviewer or "operator",
        apply=apply,
    )
    if apply and collection:
        created = create_included_parents(cfg, result["rows"], collection)
        result["library"] = {
            key: created.get(key)
            for key in ("created", "skipped_exists", "failed", "skipped")
            if key in created or key == "skipped"
        }
    verb = "applied" if apply else "would append"
    console.print(
        f"{verb} {result['written'] if apply else result['planned']} decision(s)"
    )
    if not apply:
        console.print("Dry-run. Pass --apply to write the screening ledger.")
    return 0


def run_config_check(cfg, path: Path | None) -> int:
    issues = check_config(path or getattr(cfg, "config_path", None))
    if not issues:
        console.print("Config OK", style="green")
        return 0
    for line in issues:
        console.print(line, style="yellow")
    return 1
