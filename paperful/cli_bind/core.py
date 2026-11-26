"""Signatures: entry point, serve, doctor, config, sr, collections."""

from __future__ import annotations

from rich.markup import escape
from pathlib import Path

import typer

from paperful.cli import (
    JOBS,
    __version__,
    app,
    collections_app,
    config_app,
    console,
    sr_app,
)
from paperful.cli_bind._shared import (
    AgentFormatOpt,
    ConfigOpt,
    ProfileOpt,
    RunConfigFileOpt,
    _cfg,
)


@app.callback()
def _main(
    offline: bool = typer.Option(
        False,
        "--offline",
        help="Do not contact the reference manager. Work from the mirror as it is.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Debug log on stderr. Tokens are redacted."
    ),
) -> None:
    """paperful."""
    from paperful import cli_runtime as _rt
    from paperful.log import configure

    _rt._OFFLINE = offline
    configure(verbose=verbose)


@app.command()
def jobs() -> None:
    """List canonical verbs for the five jobs (library, find, completeness, mirror, control)."""
    for name, verbs in JOBS.items():
        console.print(f"[bold]{name}[/]: {', '.join(verbs)}")
    console.print(
        "Snowball grows the library (metadata parents). "
        "Run fills PDFs for items already there. "
        "Reachout lists missing PDFs for author contact (no fetch, no mail). "
        "Twenty lookup caches CRM contacts locally. twenty sync --apply writes People."
    )


@app.command()
def mcp(config: Path | None = ConfigOpt) -> None:
    """Optional stdio MCP: read-only gaps, snowball preview, export, refs_gap, ask, precedent, stuff, metrics_show."""
    from paperful.mcp_server import serve_stdio

    serve_stdio(_cfg(config))


@app.command()
def serve(
    host: str = typer.Option(
        "127.0.0.1",
        help="Bind address. Default is localhost only.",
    ),
    port: int = typer.Option(8765, help="TCP port."),
    allow_remote_bind: bool = typer.Option(
        False,
        "--allow-remote-bind",
        help=(
            "Allow binding a non-loopback address (e.g. 0.0.0.0). "
            "Set PAPERFUL_UI_TOKEN or --ui-token to require a bearer token."
        ),
    ),
    ui_token: str = typer.Option(
        "",
        "--ui-token",
        envvar="PAPERFUL_UI_TOKEN",
        help="Require this bearer token on workbench requests (except /health).",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Localhost workbench and JSON API. Needs paperful\\[serve]."""
    from paperful.serve import SERVE_HINT, fastapi_available, run_server

    if not fastapi_available():
        console.print(f"[red]{SERVE_HINT}[/]")
        raise typer.Exit(1)
    try:
        run_server(
            _cfg(config),
            host=host,
            port=port,
            allow_remote_bind=allow_remote_bind,
            ui_token=ui_token or None,
        )
    except RuntimeError as exc:
        console.print(f"[red]{escape(str(exc))}[/]")
        raise typer.Exit(1) from exc


@app.command()
def version() -> None:
    console.print(__version__)


@app.command()
def doctor(
    config: Path | None = ConfigOpt,
    guide: bool | None = typer.Option(
        None,
        "--guide/--no-guide",
        help="Walk through amber/red fixes interactively (default: on when stdin is a TTY)",
    ),
    probe: bool = typer.Option(
        False,
        "--probe/--no-probe",
        help="Hit Scholar / EZProxy session_ok (network); amber when files exist but CAS/captcha",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Print checks as JSON (name, status, code, detail)."
    ),
) -> None:
    """Check Zotero, paths, email, and optional browser sessions (green / amber / red)."""
    from paperful.doctor_cmd import run_doctor

    run_doctor(
        console,
        config=config,
        guide=guide,
        probe=probe,
        as_json=as_json,
    )


@config_app.command("check")
def config_check(
    config: Path | None = ConfigOpt,
) -> None:
    """Report unknown config.toml keys and secrets that belong in the environment."""
    from paperful.sr_cmd import run_config_check

    cfg = _cfg(config)
    raise typer.Exit(run_config_check(cfg, config))


@sr_app.command("init")
def sr_init(
    slug: str = typer.Option(
        ..., "--slug", "-s", help="Review id (folder under state/sr/)"
    ),
    title: str = typer.Option("", "--title", help="Short review title"),
    question: str = typer.Option("", "--question", "-q", help="Review question"),
    snowball_run: str = typer.Option(
        "", "--snowball-run", help="Existing snowball run id to screen. Read-only."
    ),
    search_run: str = typer.Option(
        "", "--search-run", help="Existing search run id to screen. Read-only."
    ),
    reason: list[str] = typer.Option(
        [],
        "--reason",
        help="Allowed exclude reason (repeatable). Off-list excludes fail.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Create or overwrite a review protocol under state/sr/<slug>/."""
    from paperful.sr_cmd import run_sr_init

    cfg = _cfg(config)
    raise typer.Exit(
        run_sr_init(
            cfg,
            slug=slug,
            title=title,
            question=question,
            snowball_run=snowball_run,
            search_run=search_run,
            exclude_reasons=list(reason) or None,
        )
    )


@sr_app.command("screen")
def sr_screen(
    slug: str = typer.Option(..., "--slug", "-s"),
    identity: str = typer.Option(
        ..., "--identity", "-i", help="Work identity (OpenAlex id or DOI)"
    ),
    decision: str = typer.Option(
        ..., "--decision", "-d", help="include | exclude | maybe"
    ),
    reason: str = typer.Option("", "--reason", "-r", help="Reason code or note"),
    reviewer: str = typer.Option(
        "", "--reviewer", help="Reviewer id (default operator)"
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Append one screening decision to the review ledger."""
    from paperful.sr_cmd import run_sr_screen

    cfg = _cfg(config)
    try:
        code = run_sr_screen(
            cfg,
            slug=slug,
            identity=identity,
            decision=decision,
            reason=reason,
            reviewer=reviewer,
        )
    except ValueError as exc:
        console.print(str(exc))
        raise typer.Exit(1) from exc
    raise typer.Exit(code)


@sr_app.command("status")
def sr_status(
    slug: str = typer.Option(..., "--slug", "-s"),
    config: Path | None = ConfigOpt,
) -> None:
    """Show protocol summary and screening counts."""
    from paperful.sr_cmd import run_sr_status

    cfg = _cfg(config)
    raise typer.Exit(run_sr_status(cfg, slug=slug))


@sr_app.command("export")
def sr_export(
    slug: str = typer.Option(..., "--slug", "-s"),
    fmt: str = typer.Option(
        "csv",
        "--format",
        help="csv (included.csv), ris, covidence, rayyan, or asreview",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Print included rows. Does not write the library."""
    from paperful.sr_cmd import run_sr_export

    cfg = _cfg(config)
    raise typer.Exit(run_sr_export(cfg, slug=slug, fmt=fmt))


@sr_app.command("import")
def sr_import(
    slug: str = typer.Option(..., "--slug", "-s"),
    path: Path = typer.Argument(..., exists=True, dir_okay=False),
    fmt: str = typer.Option("csv", "--format"),
    apply: bool = typer.Option(
        False, "--apply", help="Append decisions to the screening ledger."
    ),
    collection: str = typer.Option(
        "",
        "--collection",
        "-C",
        help="With --apply, create included parents through the search apply path.",
    ),
    reviewer: str = typer.Option("", "--reviewer"),
    config: Path | None = ConfigOpt,
) -> None:
    """Read a screening file. Dry-run unless --apply. Parents need --collection."""
    from paperful.sr_cmd import run_sr_import

    cfg = _cfg(config)
    raise typer.Exit(
        run_sr_import(
            cfg,
            slug=slug,
            path=str(path),
            fmt=fmt,
            apply=apply,
            reviewer=reviewer,
            collection=collection,
        )
    )


@collections_app.callback(invoke_without_command=True)
def collections_root(
    ctx: typer.Context,
    config: Path | None = ConfigOpt,
) -> None:
    """Show the collection tree with item counts and how many lack a PDF."""
    if ctx.invoked_subcommand is not None:
        return
    from paperful.collections_cmd import run_collections_show

    run_collections_show(console, config=config)


@collections_app.command("list")
def collections_list(config: Path | None = ConfigOpt) -> None:
    """Show the collection tree with item counts and how many lack a PDF."""
    from paperful.collections_cmd import run_collections_show

    run_collections_show(console, config=config)


@collections_app.command("children")
def collections_children_cmd(
    parent: str = typer.Option(
        ...,
        "--parent",
        "-p",
        help="Parent collection path.",
    ),
    exclude: str = typer.Option(
        "",
        "--exclude",
        help="Child collection name to omit.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Print child collection paths under --parent (for night batch scripts)."""
    from paperful.collections_cmd import run_collections_children_paths

    for path in run_collections_children_paths(
        parent=parent,
        exclude_name=exclude or None,
        config=config,
    ):
        print(path)


@collections_app.command("add")
def collections_add_cmd(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Target collection path/name/key."
    ),
    keys_file: Path = typer.Option(
        ...,
        "--keys-file",
        help="Text file: one library item key per line.",
        exists=True,
        dir_okay=False,
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Add membership. Default is dry-run."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Classify only (default)."),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """File existing item keys into a collection. Dry-run unless --apply. Does not create items."""
    from paperful.collections_cmd import run_collections_add

    run_collections_add(
        console,
        collection=collection,
        keys_file=keys_file,
        apply=apply,
        dry_run=dry_run,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )
