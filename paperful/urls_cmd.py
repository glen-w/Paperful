"""``paperful urls`` implementation (CLI parses flags only)."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
from rich.console import Console
from rich.table import Table

from .runreport import write_command_report


def run_urls(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    apply: bool,
    limit: int | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod
    from .agent_json import envelope
    from .urls import probe_target, targets_for_item

    if cli_mod._scope_unset(collection, library, None, None):
        cli_mod._refuse_missing_scope()
    started = time.time()
    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    cli_mod._require_manager(cfg)
    backend = cli_mod._connect(cfg, quiet=json_out)
    keys, scope = cli_mod._scope_keys(backend, collection, library)
    items = backend.items_in_scope(keys)
    if limit:
        items = items[:limit]
    findings = []
    applied = 0
    refused = 0
    with httpx.Client(follow_redirects=True, timeout=8.0) as client:
        for item in items:
            children = []
            if hasattr(backend, "children"):
                try:
                    children = backend.children(item.key)
                except Exception:
                    children = []
            for target in targets_for_item(item, children):
                finding = probe_target(client, target, playbooks=cfg.grey_playbooks)
                row = finding.to_dict()
                if apply:
                    patch_key = (
                        finding.attachment_key
                        if finding.role == "linked_pdf" and finding.attachment_key
                        else item.key if finding.role == "parent" else ""
                    )
                    if (
                        not finding.rewrite
                        or not patch_key
                        or not backend.supports_write()
                    ):
                        refused += 1
                        row["apply"] = "refused"
                    else:
                        backend.apply_patch(patch_key, {"url": finding.rewrite})
                        applied += 1
                        row["apply"] = "rewritten"
                findings.append(row)
    summary = {
        "scope": scope,
        "checked": len(findings),
        "applied": applied,
        "refused": refused,
    }
    for code in ("ok", "redirect", "soft_404", "hard_dead", "paywall_html"):
        summary[code] = sum(1 for row in findings if row["code"] == code)
    write_command_report(
        cfg,
        command="urls",
        scope=scope,
        summary=summary,
        items=findings,
        flags={"apply": apply},
        started=started,
    )
    payload = envelope(
        command="urls check", summary=summary, items=findings, flags={"apply": apply}
    )

    def _human() -> None:
        table = Table(title="URL health")
        table.add_column("code")
        table.add_column("item")
        table.add_column("url")
        for row in findings:
            table.add_row(row["code"], row["item_key"], row["url"][:80])
        console.print(table)
        if apply:
            console.print(
                f"Rewrote {applied}. Refused {refused} (no known playbook rewrite)."
            )

    cli_mod._emit_agent(payload, json_out=json_out, human=_human)
