"""``paperful attachments`` implementation (CLI parses flags only)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .library import LibraryError
from .runreport import write_command_report
from .store import Manifest

def run_attachments(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    dry_run: bool,
    apply: bool,
    fix_broken: bool | None,
    merge_files: bool | None,
    rename: bool | None,
    link: bool | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    as_json: bool,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
) -> None:
    from . import cli_runtime as cli_mod

    from .attachments import (
        SurgeryFlags,
        mirror_has_bytes,
        apply_actions,
        apply_refusal,
        mirror_pdfs_for,
        pdf_children,
        plan_actions,
        stem_filename,
        summarize,
    )

    if cli_mod._scope_unset(collection, library, profile, run_config):
        cli_mod._refuse_missing_scope()
    cfg = cli_mod._cfg(config)
    bound = cli_mod._bind_run(
        cfg,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
    )
    collection, library, year_from, year_to, item_type = cli_mod._take_scope(bound)
    limit = bound.limit
    if dry_run and apply:
        console.print("[red]Pass either --dry-run or --apply, not both.[/]")
        raise typer.Exit(1)
    if not collection and not library:
        cli_mod._refuse_missing_scope()
    flags = SurgeryFlags(
        fix_broken=cli_mod._opt_bool(fix_broken, cfg.attachments_fix_broken),
        merge_files=cli_mod._opt_bool(merge_files, cfg.attachments_merge_files),
        rename=cli_mod._opt_bool(rename, cfg.attachments_rename),
        link=cli_mod._opt_bool(link, cfg.attachments_link),
    )
    cli_mod._require_manager(cfg)
    # Mirror-first: the scan reads children from the mirror (record.json). The
    # manager is only asked about bytes the mirror folder does not hold, and
    # for writes (--apply), which exit 2 when it is closed.
    backend = cli_mod._connect(cfg, quiet=as_json)
    loaded = cli_mod._load_scope(
        backend,
        json_out=as_json,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    items, scope = loaded.items, loaded.label
    if limit:
        items = items[:limit]
    started = time.time()
    children = []
    mirrors: dict = {}
    stems: dict = {}
    unread: list[str] = []
    unchecked = 0
    offline = getattr(backend, "live", backend) is None
    with cli_mod._item_progress(json_out=as_json) as progress:
        for item in cli_mod._track(progress, "Scanning attachments")(items):
            try:
                raw = backend.children(item.key) or []
            except LibraryError:
                # Not the same as an item with no attachments. Leave it out.
                unread.append(item.key)
                continue
            mirrors[item.key] = mirror_pdfs_for(cfg.out_dir, item)
            present: dict[str, bool] = {}
            for ch in raw:
                if not isinstance(ch, dict):
                    continue
                ckey = str(ch.get("key") or (ch.get("data") or {}).get("key") or "")
                if mirror_has_bytes(ch, mirrors[item.key]):
                    present[ckey] = True
                    continue
                if offline and (ch.get("data") or {}).get("linkMode") != "linked_file":
                    # Cannot tell a missing file from a lazy mirror. Do not call it a ghost.
                    unchecked += 1
                present[ckey] = cli_mod._child_bytes(backend, ch)
            kids = pdf_children(item.key, raw, present=present)
            children.extend(kids)
            stems[item.key] = stem_filename(item)
    scan = plan_actions(
        children,
        mirrors,
        stems,
        flags,
        out_dir=cfg.out_dir,
        library_type=str(getattr(backend, "library_type", "user")),
    )
    applied = 0
    errors: list[str] = list(scan.refusals)
    if unread:
        errors.append(f"{len(unread)} item(s) could not be read and were skipped")
    notes: list[str] = []
    if unchecked:
        notes.append(
            f"{unchecked} attachment(s) not in the mirror folder were not checked "
            "for a stored file: the library is not reachable."
        )
    if apply and flags.any:
        refusal = apply_refusal(
            manager=cfg.manager,
            library_type=str(getattr(backend, "library_type", "user")),
            link=flags.link,
        )
        if refusal:
            errors.append(refusal)
        elif not backend.supports_write():
            cli_mod._exit_env(cli_mod._no_write(backend), cfg)
        else:
            try:
                with cli_mod._item_progress(json_out=as_json) as progress:
                    applied, apply_errors = apply_actions(
                        backend,
                        scan.actions,
                        out_dir=cfg.out_dir,
                        track=cli_mod._track(progress, "Applying changes"),
                    )
            except LibraryError as exc:
                cli_mod._exit_env(str(exc))
            errors.extend(apply_errors)
    counts = summarize(scan.findings)
    report_items = [
        {
            "kind": f.kind,
            "parent": f.parent_key,
            "attachment": f.attachment_key,
            "detail": f.detail,
            "md5": f.md5,
        }
        for f in scan.findings
        if f.kind != "ok"
    ]
    write_command_report(
        cfg,
        command="attachments",
        scope=scope,
        summary={
            "items": len(items),
            "findings": counts,
            "actions": len(scan.actions) if apply and flags.any else 0,
            "applied": applied,
        },
        items=report_items,
        flags={
            "apply": apply,
            "dry_run": dry_run or not apply,
            "fix_broken": flags.fix_broken,
            "merge_files": flags.merge_files,
            "rename": flags.rename,
            "link": flags.link,
        },
        started=started,
        errors=errors,
    )
    payload = {
        "scope": scope,
        "items": len(items),
        "findings": counts,
        "actions": [
            {"op": a.op, "parent": a.parent_key, "attachment": a.attachment_key}
            for a in scan.actions
        ],
        "applied": applied,
        "errors": errors,
        "notes": notes,
    }
    if as_json:
        console.print(
            json.dumps(payload, indent=2), soft_wrap=True, highlight=False, markup=False
        )
    else:
        console.print(f"Scope: [bold]{scope}[/] — {len(items)} items")
        cli_mod._print_attachment_table(counts)
        if apply and flags.any and not errors:
            console.print(f"Applied: {applied}")
        elif flags.any and not apply:
            console.print(
                f"Would apply {len(scan.actions)} change(s). Pass [bold]--apply[/] to write them."
            )
        else:
            console.print(
                "Report only. Pass [bold]--fix-broken[/], [bold]--merge-files[/], "
                "[bold]--rename[/], or [bold]--link[/] with [bold]--apply[/] to change Zotero."
            )
        for note in notes:
            console.print(f"[yellow]{note}[/]")
        if errors:
            console.print(f"Errors: {len(errors)}")
            for err in errors[:20]:
                console.print(f"[yellow]{err}[/]")
    if errors and apply:
        raise typer.Exit(1)
