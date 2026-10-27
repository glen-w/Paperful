"""``paperful critique`` implementation (CLI parses flags only)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .runreport import write_command_report


def run_critique(
    console: Console,
    *,
    item: list[str],
    file_path: Path | None,
    collection: list[str],
    library: bool | None,
    dry_run: bool,
    apply: bool,
    llm: bool | None,
    ai_model: bool = False,
    vale: bool = False,
    forensics: bool = False,
    advanced: bool | None = None,
    lane: list[str] | None = None,
    grobid: bool | None = None,
    reviewer: list[str] | None = None,
    force: bool,
    show_dismissed: bool,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod
    from .agent_json import envelope
    from .critique import build_critique, note_html
    from .critique_extract import SUPPORTED, ExtractError
    from .critique_forensics import SIBLING_TABLE_SUFFIXES
    from .library import LibraryError
    from .llm import get_client
    from .llm.preflight import validate_llm_for_verb
    from .llm.validate import LlmConfigError
    from .pipeline import make_client
    from .store import Manifest

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    item_keys = [k.strip() for k in item if k and k.strip()]
    if bool(item_keys) == bool(file_path):
        console.print("[red]Pass exactly one of --item KEY or --file PATH.[/]")
        raise typer.Exit(1)
    if apply and not item_keys:
        console.print("[red]--apply posts a child note and needs --item.[/]")
        raise typer.Exit(1)
    if apply and dry_run:
        console.print("[red]--dry-run cannot be combined with --apply.[/]")
        raise typer.Exit(1)
    if file_path is not None and file_path.suffix.lower() not in (
        SUPPORTED | SIBLING_TABLE_SUFFIXES
    ):
        console.print(
            "[red]Unsupported format. Save as pdf, txt, md, html, rtf, docx, odt, "
            "pptx (legacy .doc needs antiword, catdoc, or LibreOffice), "
            "or csv/xlsx/xls for --forensics.[/]"
        )
        raise typer.Exit(1)

    from .critique_lanes import lanes_need_llm, resolve_critique_lanes

    try:
        lanes = resolve_critique_lanes(
            cfg, lane_flags=lane or [], llm=llm, advanced=advanced
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    use_llm = "reviewers" in lanes
    use_ai_model = bool(ai_model) or cfg.critique_ai_model
    use_vale = bool(vale) or cfg.critique_vale
    use_forensics = bool(forensics) or cfg.critique_forensics
    use_advanced = "marg" in lanes
    use_grobid = cfg.grobid_enabled if grobid is None else grobid
    reviewer_ids = [r.strip() for r in (reviewer or []) if r and str(r).strip()]
    llm_client = None
    if lanes_need_llm(lanes):
        try:
            validate_llm_for_verb(cfg)
        except LlmConfigError as exc:
            console.print(str(exc), markup=False, style="red")
            raise typer.Exit(1) from exc
        llm_client = get_client(cfg)
    if use_advanced and use_grobid and not json_out:
        from .grobid_client import grobid_egress_is_remote

        if grobid_egress_is_remote(cfg):
            console.print(
                "[yellow]GROBID is not local — PDF bytes leave this machine.[/]"
            )

    offline = cli_mod._offline()
    if "context-web" in lanes and not offline and not json_out:
        from .snowball.searxng import searxng_base_url

        extra = " and SearXNG" if searxng_base_url(cfg) else ""
        console.print(
            f"[yellow]context-web lane queries OpenAlex{extra} — "
            "literature metadata leaves this machine.[/]"
        )
    backend = None
    scope_items = []
    target = None
    if item_keys:
        cli_mod._require_manager(cfg)
        backend = cli_mod._connect(cfg, quiet=json_out)
        loaded = cli_mod._load_scope(
            backend,
            json_out=json_out,
            collection=collection,
            library=bool(library),
            year_from=None,
            year_to=None,
            item_type=[],
            item_keys=item_keys,
        )
        items = loaded.items
        if not items:
            console.print("[red]Item not in the mirror / scope.[/]")
            raise typer.Exit(1)
        target = items[0]
        if collection or library:
            scope_loaded = cli_mod._load_scope(
                backend,
                json_out=True,
                collection=collection,
                library=bool(library),
                year_from=None,
                year_to=None,
                item_type=[],
            )
            scope_items = scope_loaded.items
        else:
            scope_items = items
    elif collection or library:
        try:
            cli_mod._require_manager(cfg)
            backend = cli_mod._connect(cfg, quiet=True)
            loaded = cli_mod._load_scope(
                backend,
                json_out=True,
                collection=collection,
                library=bool(library),
                year_from=None,
                year_to=None,
                item_type=[],
            )
            scope_items = loaded.items
        except Exception:
            scope_items = []

    if apply and backend is not None and not backend.supports_write():
        raise LibraryError("critique --apply needs write access to the library")

    if scope_items and not json_out:
        console.print(f"[dim]Scope: {len(scope_items)} item(s)[/]")

    http = None if offline else make_client(cfg)
    started = time.time()
    t0 = time.perf_counter()

    def _on_status(msg: str) -> None:
        elapsed = time.perf_counter() - t0
        console.print(f"[dim]{elapsed:5.0f}s[/] {escape(msg)}")

    try:
        with cli_mod._spinner("Critique", json_out=json_out) as spin:

            def on_status(msg: str) -> None:
                spin(msg)
                if not json_out:
                    _on_status(msg)

            pack = build_critique(
                cfg,
                item=target,
                file_path=file_path,
                collections=collection or None,
                library=bool(library),
                dry_run=dry_run,
                use_llm=use_llm,
                use_ai_model=use_ai_model,
                use_vale=use_vale,
                use_forensics=use_forensics,
                use_advanced=use_advanced,
                lanes=lanes,
                use_grobid=use_grobid,
                reviewer_ids=reviewer_ids or None,
                force=force,
                show_dismissed=show_dismissed,
                offline=offline,
                client=http,
                llm_client=llm_client,
                backend=backend,
                scope_items=scope_items,
                on_status=on_status,
            )
    except ExtractError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    finally:
        if http is not None:
            http.close()

    applied = 0
    if apply and target is not None and backend is not None:
        html = note_html(pack)
        tag = (cfg.critique_tag or "paperful-critique").strip()
        backend.create_or_update_note(target.key, html, tag)
        applied = 1
        cli_mod._flush(backend)

    counts = pack.get("counts") or {}
    findings = pack.get("findings") or []
    write_command_report(
        cfg,
        command="critique",
        scope=str(pack.get("scope") or ""),
        summary={
            "findings": counts.get("findings", 0),
            "by_code": counts.get("by_code") or {},
            "applied": applied,
            "pack_dir": pack.get("pack_dir") or "",
        },
        items=[
            {
                "itemKey": pack.get("critique_id") or "",
                "title": (pack.get("input") or {}).get("title") or "",
                "status": f.get("code") or "",
                "reason": f.get("detail") or "",
            }
            for f in findings
            if not f.get("dismissed")
        ],
        flags={
            "dry_run": dry_run,
            "apply": apply,
            "llm": use_llm,
            "ai_model": use_ai_model,
            "vale": use_vale,
            "forensics": use_forensics,
            "advanced": use_advanced,
            "lanes": list(lanes),
            "grobid": use_grobid,
            "offline": offline,
        },
        started=started,
    )
    payload = envelope(
        command="critique",
        summary={
            "findings": counts.get("findings", 0),
            "by_code": counts.get("by_code") or {},
            "by_lane": counts.get("by_lane") or {},
            "pack_dir": pack.get("pack_dir") or "",
            "critique_id": pack.get("critique_id") or "",
            "applied": applied,
        },
        items=[
            {
                "id": f.get("id"),
                "code": f.get("code"),
                "lane": f.get("lane"),
                "severity": f.get("severity"),
                "loc": f.get("loc"),
                "detail": f.get("detail"),
                "dismissed": f.get("dismissed"),
            }
            for f in findings
        ],
        flags={
            "dry_run": dry_run,
            "apply": apply,
            "llm": use_llm,
            "advanced": use_advanced,
            "lanes": list(lanes),
            "grobid": use_grobid,
            "forensics": use_forensics,
        },
        exit_code=0,
    )

    def _human() -> None:
        visible = [f for f in findings if show_dismissed or not f.get("dismissed")]
        if pack.get("pack_dir"):
            console.print(f"Pack: {pack['pack_dir']}")
        console.print(
            f"Findings: {counts.get('findings', 0)} "
            f"(checked {(counts.get('by_lane') or {}).get('checked', 0)}, "
            f"suggested {(counts.get('by_lane') or {}).get('suggested', 0)})"
        )
        if not visible:
            console.print("[green]No findings.[/]")
            return
        table = Table(title="Critique")
        table.add_column("Lane")
        table.add_column("Sev")
        table.add_column("Code")
        table.add_column("Loc", style="dim")
        table.add_column("Id", style="dim")
        table.add_column("Detail")
        for f in visible:
            table.add_row(
                str(f.get("lane") or ""),
                str(f.get("severity") or ""),
                str(f.get("code") or ""),
                str(f.get("loc") or ""),
                str(f.get("id") or "")[:12],
                str(f.get("detail") or "")[:80],
            )
        console.print(table)
        if applied:
            console.print("[green]Wrote child note.[/]")

    if json_out:
        cli_mod._emit_agent(payload, json_out=True, human=_human)
        return
    _human()


def run_dismiss(
    console: Console,
    *,
    finding_id: str,
    critique_id: str | None,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod
    from .agent_json import envelope
    from .critique import dismiss_finding, latest_pack_dir, load_pack

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    fid = (finding_id or "").strip()
    if not fid:
        console.print("[red]Pass a finding id.[/]")
        raise typer.Exit(1)
    cid = (critique_id or "").strip()
    if not cid:
        root = cfg.state_dir / "critiques"
        if not root.is_dir():
            console.print("[red]No critique packs on disk; pass --critique-id.[/]")
            raise typer.Exit(1)
        # Newest critique folder with a pack.
        newest = None
        newest_mtime = 0.0
        for child in root.iterdir():
            if not child.is_dir() or child.name == "uploads":
                continue
            pack_dir = latest_pack_dir(cfg, child.name)
            if pack_dir is None:
                continue
            mtime = pack_dir.stat().st_mtime
            if mtime >= newest_mtime:
                newest_mtime = mtime
                newest = child.name
        cid = newest or ""
    if not cid:
        console.print("[red]Could not infer critique id; pass --critique-id.[/]")
        raise typer.Exit(1)
    pack_dir = latest_pack_dir(cfg, cid)
    pack = load_pack(pack_dir) if pack_dir else None
    known = {str(f.get("id")) for f in (pack or {}).get("findings") or []}
    if pack and fid not in known:
        console.print(f"[red]Finding {fid} is not in the latest pack for {cid}.[/]")
        raise typer.Exit(1)
    path = dismiss_finding(cfg, cid, fid)
    payload = envelope(
        command="critique dismiss",
        summary={"critique_id": cid, "id": fid, "path": str(path)},
        items=[{"id": fid, "critique_id": cid}],
        flags={},
        exit_code=0,
    )
    if json_out:
        cli_mod._emit_agent(payload, json_out=True, human=lambda: None)
        return
    console.print(f"Dismissed {fid} on {cid} → {path}")
