"""``paperful htmlpdf proposals`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table


def run_htmlpdf_proposals_list(
    console: Console,
    *,
    status: str,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod
    from .agent_json import envelope
    from .sources.htmlpdf import list_proposals

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    want = None if status == "all" else status
    rows = list_proposals(cfg, status=want)
    payload = envelope(
        command="htmlpdf proposals list",
        summary={"count": len(rows)},
        items=rows,
        flags={"status": status},
    )

    def _human() -> None:
        if not rows:
            console.print("No HTML snapshot proposals.")
            return
        table = Table(title="htmlpdf proposals")
        table.add_column("id")
        table.add_column("item")
        table.add_column("status")
        for row in rows:
            table.add_row(
                str(row.get("id")), str(row.get("item_key")), str(row.get("status"))
            )
        console.print(table)

    cli_mod._emit_agent(payload, json_out=json_out, human=_human)


def run_htmlpdf_proposals_apply(
    console: Console,
    *,
    proposal_id: str,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod
    from .agent_json import envelope
    from .provenance import provenance_stamp
    from .sources.htmlpdf import load_proposal, mark_applied, proposal_gate

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    cli_mod._require_manager(cfg)
    backend = cli_mod._connect(cfg, quiet=json_out)
    if not backend.supports_write():
        cli_mod._exit_env("htmlpdf proposals apply needs library write support.", cfg)
    _path, payload_row = load_proposal(cfg, proposal_id)
    if payload_row.get("status") != "pending":
        console.print(
            f"[red]Proposal {proposal_id} is {payload_row.get('status') or 'not pending'}.[/]"
        )
        raise typer.Exit(1)
    refusal = proposal_gate(payload_row)
    if refusal:
        console.print(
            f"[red]Proposal {proposal_id} failed the page gate ({refusal}).[/]"
        )
        raise typer.Exit(1)
    pdf = Path(str(payload_row.get("pdf") or ""))
    item_key = str(payload_row.get("item_key") or "")
    if not pdf.is_file() or not item_key:
        console.print("[red]Proposal is missing a PDF or item key.[/]")
        raise typer.Exit(1)
    note = provenance_stamp("htmlpdf")
    result = backend.attach(item_key, pdf, note=note)
    if not result.ok:
        console.print(f"[red]{result.reason}[/]")
        raise typer.Exit(1)
    data = mark_applied(cfg, proposal_id, item_key=item_key)
    cli_mod._flush(backend)
    payload = envelope(
        command="htmlpdf proposals apply",
        summary={"id": proposal_id, "item_key": item_key},
        items=[data],
        flags={"apply": True},
    )

    def _human_apply() -> None:
        console.print(f"Attached snapshot {proposal_id} → {item_key}")

    cli_mod._emit_agent(payload, json_out=json_out, human=_human_apply)


def run_htmlpdf_proposals_reject(
    console: Console,
    *,
    proposal_id: str,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod
    from .agent_json import envelope
    from .sources.htmlpdf import reject_proposal

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    try:
        data = reject_proposal(cfg, proposal_id)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    payload = envelope(
        command="htmlpdf proposals reject",
        summary={"id": proposal_id, "status": "rejected"},
        items=[data],
    )

    def _human_reject() -> None:
        console.print(f"Rejected proposal {proposal_id}")

    cli_mod._emit_agent(payload, json_out=json_out, human=_human_reject)
