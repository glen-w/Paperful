"""Completeness verbs after the CLI parses flags."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from .config import wants_disk, wants_zotero
from .library import LibraryError
from .runreport import ItemOutcome, build_report, write_command_report, write_run_report
from .store import Manifest


def run_dedupe(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    dry_run: bool,
    apply: bool | None,
    apply_medium: bool,
    phase: str,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    as_json: bool,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli as cli_mod

    from .dedupe import (
        PHASES,
        apply_merge,
        attach_merge_previews,
        classify,
        merge_apply_total,
        merge_preview_total,
        pack_counts,
        write_pack,
    )

    phase_name = phase.strip().lower()
    if phase_name not in PHASES:
        console.print(f"[red]Unknown phase '{phase}'.[/] Known: {', '.join(PHASES)}")
        raise typer.Exit(1)
    if cli_mod._scope_unset(collection, library, profile, run_config):
        cli_mod._refuse_missing_scope()
    cfg = cli_mod._cfg(config)
    json_out, as_json = cli_mod._agent_wins(fmt, as_json)
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
        apply=apply,
    )
    collection, library, year_from, year_to, item_type = cli_mod._take_scope(bound)
    limit = bound.limit
    apply = bound.apply
    if dry_run and apply:
        console.print("[red]Pass either --dry-run or --apply, not both.[/]")
        raise typer.Exit(1)
    if not collection and not library:
        cli_mod._refuse_missing_scope()
    cli_mod._require_manager(cfg)
    quiet = as_json or json_out
    backend = cli_mod._connect(cfg, quiet=quiet)
    items: list
    scope: str
    groups: list
    if quiet:
        loaded = cli_mod._loaded_scope(
            backend,
            collection=collection,
            library=library,
            year_from=year_from,
            year_to=year_to,
            item_type=item_type,
        )
        items, scope = loaded.items, loaded.label
        if limit:
            items = items[:limit]
        try:
            groups = classify(items, phase_name)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1)
        attach_merge_previews(backend, groups)
    else:
        with cli_mod._item_progress() as progress:
            load_id = progress.add_task("Connecting to Zotero scope…", total=None)

            def _load_status(msg: str) -> None:
                progress.update(load_id, description=msg)

            loaded = cli_mod._loaded_scope(
                backend,
                collection=collection,
                library=library,
                year_from=year_from,
                year_to=year_to,
                item_type=item_type,
                status=_load_status,
            )
            items, scope = loaded.items, loaded.label
            if limit:
                items = items[:limit]
            progress.update(
                load_id,
                description=f"Scope: {scope} — {len(items)} items",
                total=1,
                completed=1,
            )
            class_id = progress.add_task("Classifying duplicates…", total=1)
            try:
                groups = classify(items, phase_name)
            except ValueError as exc:
                console.print(f"[red]{exc}[/]")
                raise typer.Exit(1)
            progress.advance(class_id)
            preview_n = merge_preview_total(groups)
            preview_id = progress.add_task(
                "Previewing merges…", total=preview_n or 1
            )

            def _preview_status(keep: str, drop: str) -> None:
                progress.update(
                    preview_id, description=f"Preview merge {drop} → keep {keep}"
                )

            def _preview_advance() -> None:
                progress.advance(preview_id)

            attach_merge_previews(
                backend,
                groups,
                on_preview=_preview_status if preview_n else None,
                on_advance=_preview_advance if preview_n else None,
            )
            if not preview_n:
                progress.advance(preview_id)
            progress.update(
                preview_id,
                description=f"Found {len(groups)} duplicate group(s)",
                completed=preview_n or 1,
            )
    json_path, md_path = write_pack(
        cfg.state_dir, scope, groups, phase=phase_name, n_items=len(items)
    )
    counts = pack_counts(groups, len(items))
    applied = 0
    errors: list[str] = []
    if apply:
        if not backend.supports_write():
            cli_mod._exit_env(cli_mod._no_write(backend), cfg)
        from .remarks import remark_duplicates

        remark_duplicates(backend, groups, items, surface=cfg.remarks_surface)
        merge_n = merge_apply_total(groups, apply_medium=apply_medium)
        try:
            if quiet:
                applied, errors = apply_merge(
                    backend,
                    groups,
                    apply_medium=apply_medium,
                    audit_path=cfg.dedupe_applied_path,
                    scope=scope,
                    pack=json_path,
                )
            else:
                with cli_mod._item_progress() as progress:
                    merge_id = progress.add_task("Merging duplicates…", total=merge_n or 1)

                    def _merge_status(keep: str, drop: str, phase: str) -> None:
                        progress.update(
                            merge_id,
                            description=f"[{phase}] merge {drop} → keep {keep}",
                        )

                    def _merge_advance() -> None:
                        progress.advance(merge_id)

                    applied, errors = apply_merge(
                        backend,
                        groups,
                        apply_medium=apply_medium,
                        audit_path=cfg.dedupe_applied_path,
                        scope=scope,
                        pack=json_path,
                        on_merge=_merge_status if merge_n else None,
                        on_advance=_merge_advance if merge_n else None,
                    )
                    if not merge_n:
                        progress.advance(merge_id)
        except LibraryError as exc:
            cli_mod._exit_env(str(exc))
    payload = {
        "pack": str(json_path),
        "markdown": str(md_path),
        "counts": counts,
        "applied": applied,
        "errors": errors,
    }
    from .agent_json import batch_exit, envelope

    code = batch_exit(ok=applied, failed=len(errors)) if apply else 0
    agent = envelope(
        command="dedupe",
        summary={
            **counts,
            "applied": applied,
            "errors": len(errors),
        },
        paths={"pack": str(json_path), "markdown": str(md_path)},
        flags={"apply": bool(apply), "apply_medium": apply_medium, "phase": phase_name},
        exit_code=code,
    )

    def _human_dedupe() -> None:
        console.print(f"Scope: [bold]{scope}[/] — {len(items)} items")
        cli_mod._print_dedupe_table(groups)
        console.print(f"[dim]Wrote {json_path}[/]")
        console.print(f"[dim]Wrote {md_path}[/]")
        if apply:
            console.print(f"Merged: {applied}")
            if apply_medium:
                console.print("[dim]Included medium_title_year groups.[/]")
            elif any(g.phase == "medium_title_year" and g.trash for g in groups):
                console.print(
                    "Title+year groups were not merged. Pass [bold]--apply-medium[/] to include them."
                )
        else:
            console.print(
                "Dry-run. Pass [bold]--apply[/] to merge high_doi extras onto the keeper "
                "(title+year needs [bold]--apply-medium[/])."
            )
        if errors:
            console.print(f"Errors: {len(errors)}")
            for err in errors[:20]:
                console.print(f"[yellow]{err}[/]")

    if json_out:
        cli_mod._emit_agent(agent, json_out=True, human=_human_dedupe)
        return
    if as_json:
        console.print(
            json.dumps(payload, indent=2), soft_wrap=True, highlight=False, markup=False
        )
        if errors:
            raise typer.Exit(1)
        return
    _human_dedupe()
    if errors:
        raise typer.Exit(1)


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
    from . import cli as cli_mod

    from .attachments import (
        SurgeryFlags,
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
    backend = cli_mod._live_backend(cfg, quiet=as_json)
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
    with cli_mod._item_progress(json_out=as_json) as progress:
        for item in cli_mod._track(progress, "Scanning attachments")(items):
            try:
                raw = backend.children(item.key) or []
            except LibraryError:
                # Not the same as an item with no attachments. Leave it out.
                unread.append(item.key)
                continue
            present = {
                str(ch.get("key") or (ch.get("data") or {}).get("key") or ""): cli_mod._child_bytes(
                    backend, ch
                )
                for ch in raw
                if isinstance(ch, dict)
            }
            kids = pdf_children(item.key, raw, present=present)
            children.extend(kids)
            mirrors[item.key] = mirror_pdfs_for(cfg.out_dir, item)
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
        if errors:
            console.print(f"Errors: {len(errors)}")
            for err in errors[:20]:
                console.print(f"[yellow]{err}[/]")
    if errors and apply:
        raise typer.Exit(1)


def run_summarize(
    console: Console,
    *,
    item: list[str],
    collection: list[str],
    library: bool | None,
    apply: bool | None,
    to_dest: str | None,
    prompt: Path | None,
    force: bool,
    order_value: str | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    max_new: int | None,
    max_minutes: float | None,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli as cli_mod

    from .llm import llm_egress_is_remote
    from .llm.preflight import validate_llm_for_verb
    from .llm.validate import LlmConfigError
    from .summarize import SummaryRow, order_items, summarize_items

    if not item and cli_mod._scope_unset(collection, library, profile, run_config):
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    bound = cli_mod._bind_run(
        cfg,
        use_apply=True,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        apply=apply,
    )
    collection, library, year_from, year_to, item_type = cli_mod._take_scope(bound)
    limit = bound.limit
    apply = bound.apply
    if not item and not collection and not library:
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    dest = to_dest if to_dest is not None else cfg.summarize_dest
    queue_order = order_value if order_value is not None else cfg.summarize_order
    if apply and dest == "disk":
        console.print(
            "[red]--apply writes a Zotero note; it conflicts with --to disk.[/]"
        )
        raise typer.Exit(1)
    cli_mod._require_manager(cfg)
    try:
        validate_llm_for_verb(cfg)
    except LlmConfigError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    if llm_egress_is_remote(cfg):
        console.print(
            "[yellow]Remote LLM — PDF text may leave this machine for this run.[/]"
        )
    if prompt is not None:
        cfg.summarize_prompt_template = str(prompt.expanduser().resolve())
    backend = cli_mod._connect(cfg, quiet=json_out)
    manifest = Manifest(cfg.manifest_path)
    loaded = cli_mod._load_scope(
        backend,
        json_out=json_out,
        collection=collection,
        library=bool(library),
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        item_keys=item,
        pdfs_only=True,
    )
    items, scope = loaded.items, loaded.label
    items = order_items(items, queue_order)
    if limit:
        items = items[:limit]
    started = time.time()
    deadline = (
        started + max_minutes * 60.0 if max_minutes is not None and max_minutes > 0 else None
    )
    agent_box: list[dict[str, Any]] = []

    def _finish(
        outcomes: list[dict],
        summarized: int,
        failed: int,
        skipped: int,
        not_reached: int = 0,
    ) -> None:
        write_command_report(
            cfg,
            command="summarize",
            scope=scope,
            summary={
                "summarized": summarized,
                "failed": failed,
                "skipped": skipped,
                "not_reached": not_reached,
                "dest": dest,
                "order": queue_order,
            },
            items=outcomes,
            flags={
                "to": dest,
                "order": queue_order,
                "max_new": max_new,
                "max_minutes": max_minutes,
            },
            started=started,
        )
        from .agent_json import batch_exit, envelope

        code = batch_exit(ok=summarized, failed=failed)
        payload = envelope(
            command="summarize",
            summary={
                "summarized": summarized,
                "failed": failed,
                "skipped": skipped,
                "not_reached": not_reached,
            },
            items=outcomes,
            flags={"to": dest, "order": queue_order},
            exit_code=code,
        )
        agent_box.append(payload)

    def _show(row: SummaryRow) -> None:
        if json_out:
            return
        who = row.label or row.title or row.key
        if row.status == "summarized":
            console.print(f"[green]Wrote[/] {who}")
            if row.disk_path:
                console.print(f"  {row.disk_path}")
            if row.note_key:
                console.print(f"  attached note {row.note_key}")
        elif row.status == "skipped":
            console.print(f"[dim]{who}[/]: {row.reason}")
        elif not row.fatal:
            console.print(f"[yellow]{who}[/]: {row.reason}")

    if not items:
        _finish([], 0, 0, 0)
        cli_mod._emit_agent(
            agent_box[-1],
            json_out=json_out,
            human=lambda: console.print("[yellow]No items with PDFs in scope.[/]"),
        )
        return
    with cli_mod._item_progress(json_out=json_out) as progress:
        batch = summarize_items(
            cfg,
            items,
            manifest,
            backend,
            dest=dest,
            force=force,
            on_row=_show,
            track=cli_mod._track(progress, "Summarizing"),
            max_new=max_new,
            deadline=deadline,
        )
    outcomes = [
        {
            "itemKey": row.key,
            "title": row.title,
            "status": row.status,
            **({"reason": row.reason} if row.reason else {}),
        }
        for row in batch.rows
    ]
    _finish(
        outcomes,
        batch.summarized,
        batch.failed,
        batch.skipped,
        batch.not_reached,
    )
    if batch.fatal and not json_out:
        console.print(f"[red]{batch.fatal}[/]")
        raise typer.Exit(1)

    def _human_sum() -> None:
        if batch.fatal:
            console.print(f"[red]{batch.fatal}[/]")
            return
        where = cfg.summaries_dir if wants_disk(dest) else "Zotero"
        console.print(f"Summarized {batch.summarized}/{len(items)} items under {where}")
        if batch.not_reached:
            console.print(f"Not reached: {batch.not_reached} (time or --max-new limit).")
        if batch.skipped:
            console.print(
                f"Skipped {batch.skipped} already summarized for this model "
                "(pass --force to redo)."
            )
        if dest == "disk":
            console.print("Zotero not written (dest=disk).")

    if batch.fatal:
        agent_box[-1]["exit"] = 1
        agent_box[-1]["ok"] = False
    cli_mod._emit_agent(agent_box[-1], json_out=json_out, human=_human_sum)
    if batch.fatal:
        raise typer.Exit(1)
    cli_mod._flush(backend)


def run_synthesize(
    console: Console,
    *,
    item: list[str],
    collection: list[str],
    library: bool | None,
    to_dest: str | None,
    report_collection: str | None,
    prompt: Path | None,
    dry_run: bool,
    force: bool,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli as cli_mod

    from .llm import LLMClientError, get_client, llm_egress_is_remote
    from .llm.preflight import validate_llm_for_verb
    from .llm.validate import LlmConfigError
    from .synthesize import (
        ReduceCapError,
        SynthesisEvent,
        prepare_synthesis,
        report_is_current,
        write_synthesis,
    )

    if not item and cli_mod._scope_unset(collection, library, profile, run_config):
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
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
    if not item and not collection and not library:
        console.print("[red]Give --item KEY and/or --collection / --library.[/]")
        raise typer.Exit(1)
    dest = to_dest if to_dest is not None else cfg.synthesize_dest
    if report_collection and not wants_zotero(dest):
        console.print(
            "[red]--report-collection files a Zotero note; it conflicts with --to disk.[/]"
        )
        raise typer.Exit(1)
    cli_mod._require_manager(cfg)
    try:
        validate_llm_for_verb(cfg)
    except LlmConfigError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    if llm_egress_is_remote(cfg) and not dry_run:
        console.print(
            "[yellow]Remote LLM — summary text may leave this machine for this run.[/]"
        )
    if prompt is not None:
        cfg.synthesize_prompt_template = str(prompt.expanduser().resolve())
    backend = cli_mod._connect(cfg, quiet=json_out)
    loaded = cli_mod._load_scope(
        backend,
        json_out=json_out,
        collection=collection,
        library=bool(library),
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        item_keys=item,
    )
    items, scope = loaded.items, loaded.label
    items.sort(
        key=lambda it: (it.year or 9999, (it.first_author or "").lower(), it.key)
    )
    if limit:
        items = items[:limit]
    targets = []
    if wants_zotero(dest):
        if report_collection:
            try:
                targets = [backend.resolve_collection(report_collection)]
            except LookupError as exc:
                console.print(f"[red]{exc}[/]")
                raise typer.Exit(1)
        elif collection:
            seen_keys: set[str] = set()
            for spec in collection:
                try:
                    root = backend.resolve_collection(spec)
                except LookupError as exc:
                    console.print(f"[red]{exc}[/]")
                    raise typer.Exit(1)
                if root.key not in seen_keys:
                    seen_keys.add(root.key)
                    targets.append(root)
        else:
            console.print(
                "[red]Pass -C or --report-collection to file the Zotero note, or --to disk.[/]"
            )
            raise typer.Exit(1)
    slug_parts = []
    if library:
        slug_parts.append("library")
    slug_parts.extend(collection)
    slug_parts.extend(item)
    if year_from is not None or year_to is not None:
        slug_parts.append(f"{year_from or ''}-{year_to or ''}")
    types = cli_mod._resolve_types(item_type)
    if types:
        slug_parts.extend(sorted(types))
    with cli_mod._item_progress(json_out=json_out) as progress:
        prepared = prepare_synthesis(
            cfg,
            items,
            backend,
            slug_parts,
            track=cli_mod._track(progress, "Reading summaries"),
        )
    sources, missing, slug = prepared.sources, prepared.missing, prepared.slug
    plan = prepared.chunks
    on_disk = sum(1 for src in sources if src.origin == "disk")
    from_note = sum(1 for src in sources if src.origin == "note")
    if dry_run:
        console.print(
            f"Sources: {on_disk} on disk, {from_note} from Zotero notes, {len(missing)} missing"
        )
        if plan:
            sizes = ", ".join(str(n) for n in plan)
            console.print(f"Chunks: {len(plan)} ({sizes} chars)")
        else:
            console.print("[yellow]No summary notes in scope.[/]")
        if wants_disk(dest):
            console.print(f"Disk: {cfg.reports_dir / (slug + '.html')}")
        for root in targets:
            console.print(f"Zotero: {root.path} ({root.key})")
        raise typer.Exit(0)
    if not sources:
        console.print(
            "[yellow]No summary notes in scope.[/] Run [bold]paperful summarize[/] first."
        )
        raise typer.Exit(0)
    if not force and report_is_current(cfg, slug, sources, dest=dest):
        console.print(
            f"Report up to date ({len(sources)} summaries unchanged). Pass [bold]--force[/] to regenerate."
        )
        raise typer.Exit(0)
    started = time.time()

    def _announce(event: SynthesisEvent) -> None:
        if event.kind == "html":
            console.print(f"[green]Wrote[/] {event.path}")
        elif event.kind == "note":
            console.print(
                f"  attached note {event.note_key} in {event.collection_path}"
            )
        elif event.kind == "json":
            console.print(f"[green]Wrote[/] {event.path}")

    try:
        with cli_mod._spinner("Writing the report…", json_out=json_out):
            written = write_synthesis(
                cfg,
                sources=sources,
                missing=missing,
                scope=scope,
                slug=slug,
                dest=dest,
                targets=targets,
                backend=backend,
                client=get_client(cfg),
                log=lambda line: console.print(f"[dim]{line}[/]"),
                announce=_announce,
            )
    except ReduceCapError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    except LibraryError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    except (OSError, ValueError, LLMClientError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    n_chunks = written.n_chunks
    outcomes = [
        ItemOutcome(
            itemKey=src.key, title=src.title, status="summarized", reason=src.origin
        )
        for src in sources
    ]
    outcomes.extend(
        ItemOutcome(itemKey=it.key, title=it.title, status="missing_summary")
        for it in missing
    )

    class _Stats:
        pass

    stats = _Stats()
    stats.started_at = started
    stats.finished_at = time.time()
    stats.items = outcomes
    stats.scope = scope
    report = build_report(
        stats,
        cfg,
        command="synthesize",
        scope=scope,
        flags={
            "to": dest,
            "chunks": n_chunks,
            "included": len(sources),
            "missing": len(missing),
            "slug": slug,
        },
    )
    report["summary"]["included"] = len(sources)
    report["summary"]["missing"] = len(missing)
    report["summary"]["chunks"] = n_chunks
    path = write_run_report(cfg, report, as_last_run=False)
    from .agent_json import envelope

    payload = envelope(
        command="synthesize",
        summary={
            "included": len(sources),
            "missing": len(missing),
            "chunks": n_chunks,
        },
        paths={"report": str(path) if path else ""},
        flags={"to": dest, "slug": slug},
    )
    cli_mod._emit_agent(
        payload,
        json_out=json_out,
        human=lambda: console.print(
            f"Synthesized {len(sources)} summaries ({len(missing)} not included) → {path}"
        ),
    )
    cli_mod._flush(backend)


