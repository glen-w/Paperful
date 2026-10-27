"""``paperful rewrite`` implementation (CLI parses flags only)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .runreport import write_command_report


def run_rewrite(
    console: Console,
    *,
    pack_path: Path | None,
    item: list[str],
    file_path: Path | None,
    area: list[str] | None,
    output: list[str] | None,
    comments: str | None,
    dry_run: bool,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod
    from .agent_json import envelope
    from .critique import load_pack
    from .critique_extract import ExtractError
    from .llm import get_client
    from .llm.preflight import validate_llm_for_verb
    from .llm.validate import LlmConfigError
    from .rewrite import (
        _manuscript_path,
        build_rewrite,
        resolve_latest_pack,
        resolve_pack_dir,
    )
    from .rewrite_areas import parse_rewrite_areas_list, parse_rewrite_outputs

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    item_keys = [k.strip() for k in item if k and k.strip()]
    has_pack = pack_path is not None
    has_item = bool(item_keys)
    has_file = file_path is not None
    if not (has_pack or has_item or has_file):
        console.print("[red]Pass --pack PATH, --item KEY, or --file PATH.[/]")
        raise typer.Exit(1)
    if has_item and has_file and not has_pack:
        console.print("[red]Pass --item or --file (or --pack with --file), not both.[/]")
        raise typer.Exit(1)
    if len(item_keys) > 1:
        console.print("[red]Pass a single --item KEY.[/]")
        raise typer.Exit(1)

    folder = None
    if pack_path is not None:
        folder = resolve_pack_dir(cfg, pack_path)
        if folder is None:
            console.print(f"[red]No pack.json under {pack_path}.[/]")
            raise typer.Exit(1)
    else:
        folder = resolve_latest_pack(
            cfg,
            item_key=item_keys[0] if item_keys else "",
            file_path=file_path,
        )
        if folder is None:
            console.print(
                "[red]No critique pack on disk. Run paperful critique first "
                "or pass --pack.[/]"
            )
            raise typer.Exit(1)

    pack = load_pack(folder)
    if not pack:
        console.print(f"[red]Could not read pack.json in {folder}.[/]")
        raise typer.Exit(1)
    pack["pack_dir"] = str(folder)
    pack["critique_id"] = pack.get("critique_id") or folder.parent.name

    manuscript = _manuscript_path(pack, file_path)
    if manuscript is None or not manuscript.is_file():
        console.print(
            "[red]Manuscript file is missing. Pass --file PATH to the draft.[/]"
        )
        raise typer.Exit(1)

    try:
        area_ids = parse_rewrite_areas_list(
            area if area else list(cfg.rewrite_areas)
        )
        output_ids = parse_rewrite_outputs(
            output if output else list(cfg.rewrite_outputs)
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    llm_client = None
    # LLM only if a non-style area is on, or style may need it; try when enabled.
    needs_model = any(a != "style" for a in area_ids) or bool(cfg.llm_enabled)
    if cfg.llm_enabled and needs_model:
        try:
            validate_llm_for_verb(cfg)
            llm_client = get_client(cfg)
        except LlmConfigError as exc:
            if any(a != "style" for a in area_ids):
                console.print(str(exc), markup=False, style="red")
                raise typer.Exit(1) from exc
            llm_client = None

    started = time.time()
    json_out_flag = json_out

    def on_status(msg: str) -> None:
        if json_out_flag:
            print(msg, file=sys.stderr)
        else:
            console.print(msg, style="dim")

    try:
        result = build_rewrite(
            cfg,
            pack=pack,
            manuscript=manuscript,
            areas=area_ids,
            outputs=output_ids,
            comments=comments,
            dry_run=dry_run,
            llm_client=llm_client,
            on_status=on_status,
        )
    except ExtractError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    counts = result.get("counts") or {}
    write_command_report(
        cfg,
        command="rewrite",
        scope=str(result.get("critique_id") or ""),
        summary={
            "edits": counts.get("edits", 0),
            "skips": counts.get("skips", 0),
            "pack_dir": result.get("pack_dir") or "",
        },
        items=[],
        flags={
            "dry_run": dry_run,
            "areas": list(area_ids),
            "outputs": list(output_ids),
        },
        started=started,
    )
    payload = envelope(
        command="rewrite",
        summary={
            "edits": counts.get("edits", 0),
            "skips": counts.get("skips", 0),
            "pack_dir": result.get("pack_dir") or "",
            "critique_id": result.get("critique_id") or "",
        },
        items=[
            {
                "kind": e.get("kind"),
                "area": e.get("area"),
                "quote": (e.get("quote") or "")[:80],
            }
            for e in ((result.get("plan") or {}).get("edits") or [])
        ],
        flags={"dry_run": dry_run, "areas": list(area_ids), "outputs": list(output_ids)},
        exit_code=0,
    )

    def _human() -> None:
        if result.get("pack_dir"):
            console.print(f"Pack: {result['pack_dir']}")
        console.print(
            f"Edits: {counts.get('edits', 0)} · skips: {counts.get('skips', 0)}"
        )
        plan = result.get("plan") or {}
        rows = list(plan.get("edits") or [])
        if not rows:
            console.print("[green]No edits.[/]")
            return
        table = Table(title="Rewrite")
        table.add_column("Kind")
        table.add_column("Area")
        table.add_column("Quote", style="dim")
        for e in rows[:40]:
            table.add_row(
                str(e.get("kind") or ""),
                str(e.get("area") or ""),
                str(e.get("quote") or "")[:60],
            )
        console.print(table)
        if dry_run:
            console.print("[dim]Dry-run: nothing written.[/]")

    if json_out:
        cli_mod._emit_agent(payload, json_out=True, human=_human)
        return
    _human()
