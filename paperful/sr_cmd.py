"""``paperful sr`` — systematic review protocol and screening (local, no scheduler)."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from .config_check import check_config
from .sr.protocol import load_protocol, save_protocol
from .sr.screen import append_screen_decision, load_screen_ledger

console = Console()


def run_sr_init(
    cfg,
    *,
    slug: str,
    title: str,
    question: str,
) -> int:
    save_protocol(
        cfg.state_dir,
        slug,
        {"title": title, "question": question, "exclude_reasons": []},
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


def run_sr_status(cfg, *, slug: str) -> int:
    protocol = load_protocol(cfg.state_dir, slug)
    rows = load_screen_ledger(cfg.state_dir, slug)
    counts = {"include": 0, "exclude": 0, "maybe": 0}
    for row in rows:
        d = str(row.get("decision") or "")
        if d in counts:
            counts[d] += 1
    console.print(
        f"Review {slug}: {protocol.get('title') or protocol.get('question') or '(no title)'}"
    )
    console.print(f"Screening: {counts}")
    return 0


def run_config_check(cfg, path: Path | None) -> int:
    issues = check_config(path or getattr(cfg, "config_path", None))
    if not issues:
        console.print("Config OK", style="green")
        return 0
    for line in issues:
        console.print(line, style="yellow")
    return 1
