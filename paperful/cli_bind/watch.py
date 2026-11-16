"""Signatures: authorwatch, network, keepup, capture."""

from __future__ import annotations

from rich.markup import escape
import json
import sys
from pathlib import Path
from typing import Any, Callable

import typer

from paperful.cli import (
    authorwatch_app,
    capture_app,
    console,
    keepup_app,
    network_app,
)
from paperful.cli_bind._shared import (
    AgentFormatOpt,
    ConfigOpt,
    _cfg,
)


def _authorwatch_call(action: Callable[[], Any]) -> Any:
    from paperful.authorwatch import AuthorwatchError

    try:
        return action()
    except AuthorwatchError as exc:
        console.print(f"[red]{escape(str(exc))}[/]")
        raise typer.Exit(exc.code) from exc


@authorwatch_app.command("save")
def authorwatch_save(
    name: str = typer.Argument(..., help="List name under state/authorwatch/<name>/."),
    config: Path | None = ConfigOpt,
) -> None:
    """Create an empty people list. No API keys."""
    from paperful.authorwatch_cmd import run_authorwatch_save

    run_authorwatch_save(
        console,
        name=name,
        config=config,
    )


@authorwatch_app.command("add")
def authorwatch_add(
    name: str = typer.Argument(..., help="List name."),
    orcid: str = typer.Option(
        "", "--orcid", help="ORCID iD (URL or XXXX-XXXX-XXXX-XXXX)."
    ),
    display_name: str = typer.Option(
        "", "--name", help="Display name when ORCID is unknown."
    ),
    affiliation: str = typer.Option(
        "", "--affiliation", help="Host or institution hint for resolve."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Append a person. --orcid is enough; --name stays unresolved until resolve."""
    from paperful.authorwatch_cmd import run_authorwatch_add

    run_authorwatch_add(
        console,
        name=name,
        orcid=orcid,
        display_name=display_name,
        affiliation=affiliation,
        config=config,
    )


@authorwatch_app.command("remove")
def authorwatch_remove(
    name: str = typer.Argument(..., help="List name."),
    orcid: str = typer.Option("", "--orcid", help="ORCID iD to drop."),
    person_id: str = typer.Option("", "--id", help="Person id from people.jsonl."),
    config: Path | None = ConfigOpt,
) -> None:
    """Drop a member by ORCID or id."""
    from paperful.authorwatch_cmd import run_authorwatch_remove

    run_authorwatch_remove(
        console,
        name=name,
        orcid=orcid,
        person_id=person_id,
        config=config,
    )


@authorwatch_app.command("show")
def authorwatch_show(
    name: str = typer.Argument(..., help="List name."),
    config: Path | None = ConfigOpt,
) -> None:
    """People counts, held candidates, baseline, next step. Does not open the library."""
    from paperful.authorwatch_cmd import run_authorwatch_show

    run_authorwatch_show(
        console,
        name=name,
        config=config,
    )


@authorwatch_app.command("resolve")
def authorwatch_resolve(
    name: str = typer.Argument(..., help="List name."),
    config: Path | None = ConfigOpt,
) -> None:
    """Fill missing ORCID/OpenAlex ids. Ambiguous names stay held."""
    from paperful.authorwatch_cmd import run_authorwatch_resolve

    run_authorwatch_resolve(
        console,
        name=name,
        config=config,
    )


@authorwatch_app.command("suggest")
def authorwatch_suggest_cmd(
    name: str = typer.Argument(..., help="List name."),
    collection: str = typer.Option(
        ..., "--collection", "-C", help="Collection scope for ranking."
    ),
    method: str = typer.Option(
        "corpus",
        "--method",
        help="corpus, most_cited, coauthor, or mix.",
    ),
    limit: int = typer.Option(15, "--limit", help="Max new suggestions this call."),
    config: Path | None = ConfigOpt,
) -> None:
    """Propose people to follow from a collection (local corpus / OpenAlex)."""
    from paperful.authorwatch_cmd import run_authorwatch_suggest

    run_authorwatch_suggest(
        console,
        name=name,
        collection=collection,
        method=method,
        limit=limit,
        config=config,
    )


@authorwatch_app.command("accept")
def authorwatch_accept_cmd(
    name: str = typer.Argument(..., help="List name."),
    suggestion_id: list[str] = typer.Option(
        [], "--id", help="Suggestion id from suggestions.jsonl (repeatable)."
    ),
    all_pending: bool = typer.Option(
        False, "--all-pending", help="Accept every pending suggestion."
    ),
    dismiss_rest: bool = typer.Option(
        False, "--dismiss-rest", help="Mark unselected pending rows dismissed."
    ),
    seed_from: str | None = typer.Option(
        None,
        "--seed-from",
        help="After accept, run authorwatch with --backfill-from (YYYY-MM-DD).",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Move checked suggestions onto the people list."""
    from paperful.authorwatch_cmd import run_authorwatch_accept

    run_authorwatch_accept(
        console,
        name=name,
        suggestion_id=suggestion_id,
        all_pending=all_pending,
        dismiss_rest=dismiss_rest,
        seed_from=seed_from,
        config=config,
    )


@authorwatch_app.command("delete")
def authorwatch_delete_cmd(
    name: str = typer.Argument(..., help="List name."),
    yes: bool = typer.Option(False, "--yes", help="Remove state/authorwatch/<name>/."),
    config: Path | None = ConfigOpt,
) -> None:
    """Delete a list and its ledger."""
    from paperful.authorwatch_cmd import run_authorwatch_delete

    run_authorwatch_delete(
        console,
        name=name,
        yes=yes,
        config=config,
    )


@authorwatch_app.command("import")
def authorwatch_import(
    name: str = typer.Argument(..., help="List name."),
    path: Path | None = typer.Option(None, "--file", help="CSV, JSON, or ORCID list."),
    source: str = typer.Option(
        "csv",
        "--source",
        help="csv, json, orcid; rg/linkedin/academia need --file (no scrape).",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Import people from a file. Social --source without --file prints the export recipe."""
    from paperful.authorwatch_cmd import run_authorwatch_import

    run_authorwatch_import(
        console,
        name=name,
        path=path,
        source=source,
        config=config,
    )


@authorwatch_app.command("run")
def authorwatch_run(
    name: str = typer.Argument(..., help="List name."),
    backfill_from: str | None = typer.Option(
        None,
        "--backfill-from",
        help="YYYY-MM-DD publication date; propose recent works on this run.",
    ),
    max_authors: int = typer.Option(
        50, "--max-authors", help="Cap OpenAlex author polls."
    ),
    per_author_limit: int = typer.Option(
        200, "--per-author-limit", help="Max works per author this run."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Cursor baseline (proposes 0) unless --backfill-from. Never creates library items."""
    from paperful.authorwatch_cmd import run_authorwatch_run

    run_authorwatch_run(
        console,
        name=name,
        backfill_from=backfill_from,
        max_authors=max_authors,
        per_author_limit=per_author_limit,
        config=config,
    )


@authorwatch_app.command("briefing")
def authorwatch_briefing(
    name: str = typer.Argument(..., help="List name."),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Write markdown from the inbox plus OpenAlex people context. Does not create items."""
    from paperful.authorwatch_cmd import run_authorwatch_briefing

    run_authorwatch_briefing(
        console,
        name=name,
        config=config,
        fmt=fmt,
    )


@authorwatch_app.command("digest")
def authorwatch_digest_cmd(
    name: str = typer.Argument(..., help="List name."),
    config: Path | None = ConfigOpt,
) -> None:
    """Write digest.md from the inbox. Does not create items."""
    from paperful.authorwatch_cmd import run_authorwatch_digest

    run_authorwatch_digest(
        console,
        name=name,
        config=config,
    )


@authorwatch_app.command("apply")
def authorwatch_apply_cmd(
    name: str = typer.Argument(..., help="List name."),
    collection: str = typer.Option(
        ..., "--collection", "-C", help="Target collection path."
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Create metadata parents. Default is dry-run. PDFs stay paperful run.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Create inbox rows in -C. Independent of \\[snowball] enabled."""
    from paperful.authorwatch_cmd import run_authorwatch_apply

    run_authorwatch_apply(
        console,
        name=name,
        collection=collection,
        apply=apply,
        config=config,
    )


@network_app.command("orcid")
def network_orcid_cmd(
    orcid: str = typer.Argument(..., help="16-digit ORCID with hyphens."),
    phases: str = typer.Option(
        "bbnj",
        "--phases",
        help="Named preset (bbnj) or a TOML file with \\[\\[phases]].",
    ),
    partition: str = typer.Option(
        "none",
        "--partition",
        help="Brokerage groups: region, discipline, sector, or none.",
    ),
    max_works: int = typer.Option(500, "--max-works", help="OpenAlex works cap."),
    max_alters: int = typer.Option(
        150, "--max-alters", help="Keep the ego plus this many co-authors."
    ),
    figures: bool = typer.Option(
        False,
        "--figures",
        help="Write phase PNG files (needs the network extra).",
    ),
    run_id: str | None = typer.Option(
        None, "--run-id", help="Override the generated run id."
    ),
    out_dir: Path | None = typer.Option(
        None,
        "--out-dir",
        help="Write the run here. Default: state/network/<run-id>/.",
    ),
    fmt: str = AgentFormatOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Build an ORCID ego co-authorship network and slice it by negotiation phase."""
    from paperful.network.command import run_network_orcid

    run_network_orcid(
        console,
        orcid,
        phases=phases,
        partition=partition,
        max_works=max_works,
        max_alters=max_alters,
        figures=figures,
        fmt=fmt,
        config=config,
        run_id=run_id,
        out_dir=out_dir,
    )


@network_app.command("show")
def network_show_cmd(
    run_id: str = typer.Argument(..., help="Run id under state/network/."),
    phase: str = typer.Option(
        "", "--phase", help="Restrict the table to one phase id."
    ),
    fmt: str = AgentFormatOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Print ego metrics for a saved network run. Does not call OpenAlex."""
    from paperful.network.command import run_network_show

    run_network_show(console, run_id, phase=phase, fmt=fmt, config=config)


@network_app.command("list")
def network_list_cmd(
    fmt: str = AgentFormatOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """List saved ego-network runs under state/network/."""
    from paperful.network.command import run_network_list

    run_network_list(console, config=config, fmt=fmt)


@network_app.command("export")
def network_export_cmd(
    run_id: str = typer.Argument(..., help="Run id under state/network/."),
    fmt: str = typer.Option(
        "csv",
        "--format",
        help="csv (default), gexf, or graphml (gexf/graphml need NetworkX).",
    ),
    dest: Path | None = typer.Option(
        None, "--dest", help="Output path. Default: the run dir."
    ),
    phase: str = typer.Option("", "--phase", help="Export one phase subgraph."),
    config: Path | None = ConfigOpt,
) -> None:
    """Write edges as CSV, or a GEXF/GraphML graph."""
    from paperful.network.command import run_network_export

    run_network_export(console, run_id, fmt=fmt, dest=dest, phase=phase, config=config)


@network_app.command("attributes")
def network_attributes_cmd(
    run_id: str = typer.Argument(..., help="Run id under state/network/."),
    write_template: bool = typer.Option(
        False,
        "--write-template",
        help="(Re)write attributes.csv from OpenAlex seeds without recomputing metrics.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Write or reload the hand-coding CSV (discipline, sector, region, career stage)."""
    from paperful.network.command import run_network_attributes

    run_network_attributes(
        console, run_id, write_template=write_template, config=config
    )


def _keepup_call(action: Callable[[], Any]) -> Any:
    from paperful.keepup import KeepupError
    from paperful.snowball.command import SnowballError

    try:
        return action()
    except (KeepupError, SnowballError) as exc:
        console.print(f"[red]{escape(str(exc))}[/]")
        raise typer.Exit(getattr(exc, "code", 2) or 2) from exc


@keepup_app.command("save")
def keepup_save(
    name: str = typer.Argument(..., help="Job name under state/keepup/<name>/."),
    collection: str = typer.Option(
        ..., "--collection", "-C", help="Target Zotero collection path."
    ),
    watch: list[str] = typer.Option(
        [], "--watch", help="Snowball watch name (repeatable)."
    ),
    authorwatch: list[str] = typer.Option(
        [], "--authorwatch", help="Authorwatch list name (repeatable)."
    ),
    source: list[str] = typer.Option(
        [],
        "--source",
        help="Built-in source type. Use cites for what-cites-my-collection.",
    ),
    interval_days: int | None = typer.Option(
        None,
        "--interval-days",
        help="Days between polls (default \\[keepup].interval_days or 7).",
    ),
    per_seed_limit: int = typer.Option(
        20, "--per-seed-limit", help="OpenAlex citing works per seed paper."
    ),
    max_candidates: int = typer.Option(
        100, "--max-candidates", help="Cap proposed rows per cites poll (0 = no cap)."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Create or update a keepup job. No API keys."""
    from paperful.keepup_cmd import run_keepup_save

    run_keepup_save(
        console,
        name=name,
        collection=collection,
        watch=watch,
        authorwatch=authorwatch,
        source=source,
        interval_days=interval_days,
        per_seed_limit=per_seed_limit,
        max_candidates=max_candidates,
        config=config,
    )


@keepup_app.command("list")
def keepup_list_cmd(config: Path | None = ConfigOpt) -> None:
    """List keepup jobs."""
    from paperful.keepup_cmd import run_keepup_list

    run_keepup_list(
        console,
        config=config,
    )


@keepup_app.command("show")
def keepup_show(
    name: str = typer.Argument(..., help="Job name."),
    config: Path | None = ConfigOpt,
) -> None:
    """Show job ledger. Does not open the library."""
    from paperful.keepup_cmd import run_keepup_show

    run_keepup_show(
        console,
        name=name,
        config=config,
    )


@keepup_app.command("delete")
def keepup_delete(
    name: str = typer.Argument(..., help="Job name."),
    yes: bool = typer.Option(False, "--yes", help="Remove state/keepup/<name>/."),
    config: Path | None = ConfigOpt,
) -> None:
    """Delete a keepup job ledger."""
    from paperful.keepup_cmd import run_keepup_delete

    run_keepup_delete(
        console,
        name=name,
        yes=yes,
        config=config,
    )


@keepup_app.command("run")
def keepup_run(
    name: str = typer.Argument(..., help="Job name."),
    force: bool = typer.Option(
        False, "--force", help="Ignore interval_days and poll now."
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="After polling, create parents in the job collection.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Poll sources (respecting interval). Baseline proposes nothing."""
    from paperful.keepup_cmd import run_keepup_run

    run_keepup_run(
        console,
        name=name,
        force=force,
        apply=apply,
        config=config,
    )


@keepup_app.command("digest")
def keepup_digest(
    name: str = typer.Argument(..., help="Job name."),
    config: Path | None = ConfigOpt,
) -> None:
    """Rebuild digest.md from the keepup inbox. Does not create items."""
    from paperful.keepup_cmd import run_keepup_digest

    run_keepup_digest(
        console,
        name=name,
        config=config,
    )


@keepup_app.command("apply")
def keepup_apply_cmd(
    name: str = typer.Argument(..., help="Job name."),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Create metadata parents. Default is dry-run.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Create parents from the keepup inbox into the job collection."""
    from paperful.keepup_cmd import run_keepup_apply

    run_keepup_apply(
        console,
        name=name,
        apply=apply,
        config=config,
    )


@keepup_app.command("dismiss")
def keepup_dismiss(
    name: str = typer.Argument(..., help="Job name."),
    doi: str = typer.Option("", "--doi", help="DOI to mute."),
    identity: str = typer.Option(
        "", "--identity", help="Identity key (doi:… or openalex:…)."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Mute a work so keepup never re-proposes it."""
    from paperful.keepup_cmd import run_keepup_dismiss

    run_keepup_dismiss(
        console,
        name=name,
        doi=doi,
        identity=identity,
        config=config,
    )


@capture_app.callback(invoke_without_command=True)
def capture_main(
    ctx: typer.Context,
    stdio: bool = typer.Option(
        False, "--stdio", help="Native messaging loop for the Firefox add-on."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Mirror capture. ``--stdio`` speaks Firefox native messaging."""
    if ctx.invoked_subcommand is not None:
        return
    if not stdio:
        console.print(ctx.get_help())
        raise typer.Exit(0)
    from paperful.capture_host import serve_stdio

    serve_stdio(_cfg(config))


@capture_app.command("plan")
def capture_plan(
    doi: str = typer.Option("", "--doi"),
    url: str = typer.Option("", "--url"),
    title: str = typer.Option("", "--title"),
    year: int | None = typer.Option(None, "--year"),
    pdf_url: str = typer.Option("", "--pdf-url"),
    config: Path | None = ConfigOpt,
) -> None:
    """Dry-run identity: create, update, blocked, or ambiguous. Writes nothing."""
    from paperful.capture import as_year, plan_page

    result = plan_page(
        _cfg(config),
        doi=doi,
        url=url,
        title=title,
        year=year if year is not None else as_year(year),
        pdf_url=pdf_url,
    )
    console.print_json(json.dumps(result))


@capture_app.command("apply")
def capture_apply(config: Path | None = ConfigOpt) -> None:
    """Read one JSON object on stdin and write the mirror."""
    from paperful.capture import apply_page

    try:
        body = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        console.print_json(json.dumps({"ok": False, "reason": "invalid"}))
        raise typer.Exit(2)
    if not isinstance(body, dict):
        console.print_json(json.dumps({"ok": False, "reason": "invalid"}))
        raise typer.Exit(2)
    result = apply_page(_cfg(config), body)
    code = int(result.pop("code", 0 if result.get("ok") else 2))
    console.print_json(json.dumps(result))
    if code:
        raise typer.Exit(code)


@capture_app.command("session")
def capture_session(config: Path | None = ConfigOpt) -> None:
    """Print the open handoff tab list, or an empty list."""
    from paperful.capture import read_session

    console.print_json(json.dumps(read_session(_cfg(config))))


@capture_app.command("install-host")
def capture_install_host(config: Path | None = ConfigOpt) -> None:
    """Install the user-level Firefox native messaging host (macOS, Linux, Windows)."""
    from paperful.capture_host import install_host

    line = install_host(_cfg(config), config)
    console.print(line)
