"""``paperful snowball trends`` — publication-year counts (read-only)."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .command import SnowballError
from .trends import trends_for_scope


def run_trends(
    console: Console,
    *,
    query: str | None,
    profile: str | None,
    year_from: int | None,
    year_to: int | None,
    config,
    fmt: str,
) -> None:
    from .. import cli as cli_mod
    from ..agent_json import envelope

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    try:
        report = trends_for_scope(
            cfg,
            query=query,
            profile=profile,
            year_from=year_from,
            year_to=year_to,
        )
    except SnowballError as exc:
        payload = envelope(
            command="snowball trends",
            exit_code=exc.code,
            summary={"error": str(exc)},
            flags={"read_only": True},
        )
        cli_mod._emit_agent(
            payload,
            json_out=json_out,
            human=lambda: console.print(f"[red]{exc}[/]"),
        )
        return

    def _human() -> None:
        title = "Publication trends"
        if report.profile:
            title += f" (profile {report.profile})"
        console.print(f"{title} — [bold]{report.query}[/]")
        console.print(f"Matched works (sum of years): {report.total}")
        if not report.years:
            console.print("[dim]No year buckets returned.[/]")
            return
        table = Table(title="By year")
        table.add_column("Year", justify="right")
        table.add_column("Works", justify="right")
        for row in report.years:
            table.add_row(str(row.year), str(row.count))
        console.print(table)

    payload = envelope(
        command="snowball trends",
        summary={
            "query": report.query,
            "profile": report.profile or "",
            "total": report.total,
            "years": [{"year": row.year, "count": row.count} for row in report.years],
        },
        flags={"read_only": True, "dry_run": True},
    )
    cli_mod._emit_agent(payload, json_out=json_out, human=_human)
