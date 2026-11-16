"""Signatures: search, urls, gaps, run, attach, inbox, notes, refs."""

from __future__ import annotations

from pathlib import Path

import typer

from paperful.cli import (
    app,
    console,
    htmlpdf_proposals_app,
    inbox_app,
    notes_app,
    refs_app,
    search_app,
    search_watch_app,
)
from paperful.cli_bind._shared import (
    AgentFormatOpt,
    BrowserAgentOpt,
    CamofoxOpt,
    ConfigOpt,
    CreateTagOpt,
    EzproxyReloginOpt,
    ItemTypeOpt,
    LibraryOpt,
    NoAttachOpt,
    ProfileOpt,
    ReRequestOpt,
    RequestRgOpt,
    RetryFailedOpt,
    RunConfigFileOpt,
    SciHubOpt,
    StrictPdfDoiOpt,
    TryAllOpt,
    TwentyWritebackOpt,
    UpgradeLinkedOpt,
    UpgradeSnapshotOpt,
    YearFromOpt,
    YearToOpt,
)


@search_app.command("run")
def search_cmd(
    terms: list[str] | None = typer.Argument(
        None,
        help="Query terms (AND). Quote phrases. Optional with --run-id or --list.",
    ),
    hosts: str = typer.Option(
        "",
        "--hosts",
        help="Comma-separated allowlist (also injected as site: ORs). Empty keeps any non-blocked host.",
    ),
    filetype: str = typer.Option(
        "pdf",
        "--filetype",
        help="Append filetype:pdf to the query (default). Pass none to skip.",
    ),
    max_hits: int | None = typer.Option(
        None,
        "--max",
        help="Max kept hits. Default: \\[search].max or 20.",
    ),
    probe: bool | None = typer.Option(
        None,
        "--probe/--no-probe",
        help="HEAD/GET first bytes for PDF vs HTML (default: \\[search].probe, on).",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Create metadata parents in -C. Default is dry-run. PDFs stay paperful run.",
    ),
    collection: str = typer.Option(
        "",
        "--collection",
        "-C",
        help="Target collection path. Required with --apply.",
    ),
    run_id: str | None = typer.Option(
        None, "--run-id", help="Reprint a saved run under state/search/."
    ),
    out_dir: Path | None = typer.Option(
        None,
        "--out-dir",
        help="Write the search pack here. Default: state/search/<run-id>/. Does not imply --apply.",
    ),
    list_runs_flag: bool = typer.Option(
        False, "--list", help="List saved runs under state/search/."
    ),
    fmt: str = AgentFormatOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Discover grey PDFs and landings via SearXNG. Metadata only; PDFs stay Wanted / run."""
    from paperful.search.command import run_search_cmd

    run_search_cmd(
        console,
        terms or [],
        hosts=hosts,
        filetype=filetype,
        max_hits=max_hits,
        probe=probe,
        fmt=fmt,
        config=config,
        run_id=run_id,
        out_dir=out_dir,
        apply=apply,
        collection=collection,
        list_runs_flag=list_runs_flag,
    )


@search_watch_app.command("save")
def search_watch_save(
    name: str = typer.Argument(
        ..., help="Watch name under state/search/watches/<name>/."
    ),
    query: str = typer.Option(
        "",
        "--query",
        help="Grey query terms (same as paperful search). Optional with --from-run.",
    ),
    hosts: str = typer.Option("", "--hosts", help="Comma-separated allowlist."),
    filetype: str = typer.Option("pdf", "--filetype", help="pdf (default) or none."),
    max_hits: int | None = typer.Option(None, "--max", help="Max kept hits."),
    probe: bool | None = typer.Option(
        None,
        "--probe/--no-probe",
        help="HEAD/GET first bytes (default: \\[search].probe).",
    ),
    interval_days: int = typer.Option(
        7,
        "--interval-days",
        help="Days between polls. 0 = every run. You still cron search watch run.",
    ),
    from_run: str | None = typer.Option(
        None,
        "--from-run",
        help="Copy query/hosts from a saved state/search/<run-id>/ pack.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Point a watch at a grey query. No API keys. Does not poll until watch run."""
    from paperful.search.command import run_search_watch_save

    run_search_watch_save(
        console,
        name,
        query=query,
        hosts=hosts,
        filetype=filetype,
        max_hits=max_hits,
        probe=probe,
        interval_days=interval_days,
        from_run=from_run,
        config=config,
    )


@search_watch_app.command("run")
def search_watch_run(
    name: str = typer.Argument(..., help="Watch name."),
    force: bool = typer.Option(
        False,
        "--force",
        help="Run even when the interval has not elapsed.",
    ),
    fmt: str = AgentFormatOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Baseline on first run; later runs write only unseen URLs to the inbox."""
    from paperful.search.command import run_search_watch_run

    run_search_watch_run(console, name, force=force, fmt=fmt, config=config)


@search_watch_app.command("apply")
def search_watch_apply(
    name: str = typer.Argument(..., help="Watch name."),
    collection: str = typer.Option(
        "",
        "--collection",
        "-C",
        help="Target collection path. Required.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Create metadata parents. Default is dry-run. PDFs stay paperful run.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Create metadata parents from the watch inbox. Dry-run unless --apply."""
    from paperful.search.command import run_search_watch_apply

    run_search_watch_apply(
        console,
        name,
        collection=collection,
        apply=apply,
        config=config,
    )


@search_watch_app.command("show")
def search_watch_show(
    name: str = typer.Argument(..., help="Watch name."),
    config: Path | None = ConfigOpt,
) -> None:
    """Print query, seen URLs, inbox, and when the next poll is due."""
    from paperful.search.command import run_search_watch_show

    run_search_watch_show(console, name, config=config)


@search_watch_app.command("list")
def search_watch_list(
    fmt: str = AgentFormatOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """List saved grey watches under state/search/watches/."""
    from paperful.search.command import run_search_watch_list

    run_search_watch_list(console, fmt=fmt, config=config)


@search_watch_app.command("due")
def search_watch_due(
    fmt: str = AgentFormatOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Print watches whose interval has elapsed, for cron. Does not run them."""
    from paperful.search.command import run_search_watch_due

    run_search_watch_due(console, fmt=fmt, config=config)


@app.command("urls")
def urls_check(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Rewrite a URL only when a grey playbook already knows the PDF target.",
    ),
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """HEAD/GET metadata and linked-PDF URLs. Report only unless --apply."""
    from paperful.urls_cmd import run_urls

    run_urls(
        console,
        collection=collection,
        library=library,
        apply=apply,
        limit=limit,
        config=config,
        fmt=fmt,
    )


@htmlpdf_proposals_app.command("list")
def htmlpdf_proposals_list(
    status: str = typer.Option(
        "pending", "--status", help="pending, applied, rejected, or all."
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    from paperful.htmlpdf_cmd import run_htmlpdf_proposals_list

    run_htmlpdf_proposals_list(console, status=status, config=config, fmt=fmt)


@htmlpdf_proposals_app.command("apply")
def htmlpdf_proposals_apply(
    proposal_id: str = typer.Argument(..., help="Proposal id."),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    from paperful.htmlpdf_cmd import run_htmlpdf_proposals_apply

    run_htmlpdf_proposals_apply(
        console, proposal_id=proposal_id, config=config, fmt=fmt
    )


@htmlpdf_proposals_app.command("reject")
def htmlpdf_proposals_reject(
    proposal_id: str = typer.Argument(..., help="Proposal id."),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    from paperful.htmlpdf_cmd import run_htmlpdf_proposals_reject

    run_htmlpdf_proposals_reject(
        console, proposal_id=proposal_id, config=config, fmt=fmt
    )


@app.command()
def gaps(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    list_missing: bool = typer.Option(
        False,
        "--list-missing",
        help="List items with no stored PDF (key, title, DOI, URL, hint).",
    ),
    handoff: str | None = typer.Option(
        None,
        "--handoff",
        help=(
            "After listing: list (default), tabs (open URLs), walk (interactive "
            "Downloads ingest), or watch (tabs + poll the inbox.dir folder)."
        ),
    ),
    include_doi_tabs: bool = typer.Option(
        False,
        "--include-doi-tabs",
        help="With --handoff tabs|watch, also open doi.org for doi_only rows.",
    ),
    downloads_dir: Path | None = typer.Option(
        None,
        "--downloads-dir",
        help="Directory for --handoff walk newest-PDF pickup (default ~/Downloads).",
    ),
    request_rg: bool | None = RequestRgOpt,
    re_request: bool = ReRequestOpt,
    to: Path | None = typer.Option(
        None,
        "--to",
        help="Write the missing-PDF list to a .tsv or .md file.",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Legacy counts JSON. Prefer --format json."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Count items with no stored PDF, a linked PDF URL only, or no DOI.

    Points at `run` (PDFs) and `lint` (identifiers). Does not write the library
    unless ``--handoff walk`` or ``--handoff watch`` attaches files.
    """
    from paperful.gaps_cmd import run_gaps_command

    run_gaps_command(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        list_missing=list_missing,
        handoff=handoff,
        include_doi_tabs=include_doi_tabs,
        downloads_dir=downloads_dir,
        request_rg=request_rg,
        re_request=re_request,
        to=to,
        as_json=as_json,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command()
def reachout(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    non_oa_only: bool = typer.Option(
        False,
        "--non-oa-only",
        help="Keep paywalled / no_oa / license_blocked misses only.",
    ),
    lookup: bool = typer.Option(
        False,
        "--lookup",
        help="When Twenty is enabled, search People for authors still missing an email.",
    ),
    to: Path | None = typer.Option(
        None,
        "--to",
        help="Write CSV (default), TSV, or Markdown (.csv / .tsv / .md).",
    ),
    handoff: str | None = typer.Option(
        None,
        "--handoff",
        help="list (default), tabs, or walk — ResearchGate publication URLs only.",
    ),
    request_rg: bool | None = RequestRgOpt,
    re_request: bool = ReRequestOpt,
    downloads_dir: Path | None = typer.Option(
        None,
        "--downloads-dir",
        help="Directory for --handoff walk newest-PDF pickup (default ~/Downloads).",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Contact authors for missing PDFs. Never fetches. Never sends mail."""
    from paperful.reachout_cmd import run_reachout

    run_reachout(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        non_oa_only=non_oa_only,
        lookup=lookup,
        to=to,
        handoff=handoff,
        request_rg=request_rg,
        re_request=re_request,
        downloads_dir=downloads_dir,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command()
def run(
    collection: list[str] = typer.Option(
        [],
        "--collection",
        "-C",
        help="Collection path/name/key (repeatable). Subcollections included.",
    ),
    library: bool | None = LibraryOpt,
    dry_run: bool = typer.Option(
        False, "--dry-run", help="List what would be fetched; no network beyond Zotero."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    no_attach: bool | None = NoAttachOpt,
    retry_failed: bool | None = RetryFailedOpt,
    try_all: bool | None = TryAllOpt,
    sources: str | None = typer.Option(
        None,
        "--sources",
        help="Comma-separated source order override (or a preset name: oa, eoi).",
    ),
    preset: str | None = typer.Option(
        None,
        "--preset",
        help=(
            "Source preset. oa = open-access sources only (no EZProxy). "
            "eoi = OA + EZProxy, no Scholar or Sci-Hub (same as the default list)."
        ),
    ),
    scihub: bool | None = SciHubOpt,
    ezproxy_relogin: bool | None = EzproxyReloginOpt,
    browser_agent: bool | None = BrowserAgentOpt,
    camofox: bool | None = CamofoxOpt,
    upgrade_linked: bool | None = UpgradeLinkedOpt,
    upgrade_snapshot: bool | None = UpgradeSnapshotOpt,
    keep_snapshot: bool = typer.Option(
        False,
        "--keep-snapshot",
        help="With --upgrade-snapshot, leave the HTML print beside the new PDF.",
    ),
    htmlpdf_mode: str | None = typer.Option(
        None,
        "--htmlpdf",
        help="Academic HTML snapshot for this run: off, gated, or auto. Default off.",
    ),
    serpapi_max: int | None = typer.Option(
        None,
        "--serpapi-max",
        help="Cap paid SerpApi Scholar searches this run (0 = unlimited). Default \\[serpapi].max_calls.",
    ),
    strict_pdf_doi: bool | None = StrictPdfDoiOpt,
    handoff: str | None = typer.Option(
        None,
        "--handoff",
        help=(
            "After the run: list|tabs|walk|watch for soft-blocked openable PDF URLs. "
            "watch = tabs then poll the inbox.dir folder."
        ),
    ),
    include_doi_tabs: bool = typer.Option(
        False,
        "--include-doi-tabs",
        help="With --handoff tabs|watch, also open doi.org for doi_only rows.",
    ),
    downloads_dir: Path | None = typer.Option(
        None,
        "--downloads-dir",
        help="Downloads dir for --handoff walk (default ~/Downloads).",
    ),
    request_rg: bool | None = RequestRgOpt,
    re_request: bool = ReRequestOpt,
    twenty_writeback: bool | None = TwentyWritebackOpt,
    promote: str | None = typer.Option(
        None,
        "--promote",
        help="Override \\[playbooks].promote for this run: gated or auto.",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Fill PDFs into the local mirror. Copies into the library when it is reachable. --dry-run does not write."""
    from paperful.run_cmd import run_run_command

    run_run_command(
        console,
        collection=collection,
        library=library,
        dry_run=dry_run,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        no_attach=no_attach,
        retry_failed=retry_failed,
        try_all=try_all,
        sources=sources,
        preset=preset,
        scihub=scihub,
        ezproxy_relogin=ezproxy_relogin,
        browser_agent=browser_agent,
        camofox=camofox,
        upgrade_linked=upgrade_linked,
        upgrade_snapshot=upgrade_snapshot,
        keep_snapshot=keep_snapshot,
        htmlpdf_mode=htmlpdf_mode,
        serpapi_max=serpapi_max,
        strict_pdf_doi=strict_pdf_doi,
        handoff=handoff,
        include_doi_tabs=include_doi_tabs,
        downloads_dir=downloads_dir,
        request_rg=request_rg,
        re_request=re_request,
        twenty_writeback=twenty_writeback,
        promote=promote,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command()
def attach(
    item: list[str] = typer.Option(
        [], "--item", help="Attach a file to this item key."
    ),
    file: Path | None = typer.Option(
        None,
        "--file",
        help="PDF path for --item (manual download ingest).",
    ),
    config: Path | None = ConfigOpt,
    limit: int | None = typer.Option(None, "--limit", "-n"),
    allow_pdf_doi_mismatch: bool = typer.Option(
        False,
        "--allow-pdf-doi-mismatch",
        help="Also attach PDFs that --strict-pdf-doi left on disk.",
    ),
    allow_short_pdf: bool = typer.Option(
        False,
        "--allow-short-pdf",
        help="Also attach dense one-page PDFs held for admit.",
    ),
) -> None:
    """Write already-downloaded PDFs into the library. This command attaches; it is not a dry-run.

    Use ``--item KEY --file PATH`` to ingest a hand-downloaded PDF."""
    from paperful.attach_cmd import run_attach

    run_attach(
        console,
        item=item,
        file=file,
        config=config,
        limit=limit,
        allow_pdf_doi_mismatch=allow_pdf_doi_mismatch,
        allow_short_pdf=allow_short_pdf,
    )


@inbox_app.command("watch")
def inbox_watch(
    collection: list[str] = typer.Option(
        [],
        "--collection",
        "-C",
        help="Optional narrow; omit (or pass --library) to match any missing-PDF item.",
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    idle: float | None = typer.Option(
        None,
        "--idle",
        help="Stop after this many idle seconds (default: inbox.idle_seconds, 0=forever).",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    tag: list[str] = CreateTagOpt,
) -> None:
    """Long-running sidecar: poll inbox.dir and attach by PDF DOI (no FIFO).

    Defaults to the whole library so one drop folder can serve every topic.
    Pass ``-C`` only when you intentionally want a narrower DOI index."""
    from paperful.inbox_cmd import run_inbox_watch

    run_inbox_watch(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        idle=idle,
        profile=profile,
        run_config=run_config,
        config=config,
        tag=tag,
    )


@inbox_app.command("drain")
def inbox_drain(
    collection: list[str] = typer.Option(
        [],
        "--collection",
        "-C",
        help="Optional narrow; omit (or pass --library) to match any missing-PDF item.",
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    tag: list[str] = CreateTagOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """One-shot: ingest current PDFs in inbox.dir.

    Default match is DOI-only. ``\\[inbox].match`` can add title / OCR / LLM stages.
    Defaults to the whole library so one drop folder can serve every topic.
    Pass ``-C`` only when you intentionally want a narrower DOI index."""
    from paperful.inbox_cmd import run_inbox_drain

    run_inbox_drain(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        profile=profile,
        run_config=run_config,
        config=config,
        tag=tag,
        fmt=fmt,
    )


inbox_proposals_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Gated inbox create/attach proposals. Never silent parent create.",
)
inbox_app.add_typer(inbox_proposals_app, name="proposals")


@inbox_proposals_app.command("list")
def inbox_proposals_list(
    status: str = typer.Option(
        "pending", "--status", help="pending, applied, rejected, or all."
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    from paperful.inbox_cmd import run_inbox_proposals_list

    run_inbox_proposals_list(
        console,
        status=status,
        config=config,
        fmt=fmt,
    )


@inbox_proposals_app.command("apply")
def inbox_proposals_apply(
    proposal_id: str = typer.Argument(
        ..., help="Proposal id from inbox proposals list."
    ),
    tag: list[str] = CreateTagOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    from paperful.inbox_cmd import run_inbox_proposals_apply

    run_inbox_proposals_apply(
        console,
        proposal_id=proposal_id,
        tag=tag,
        config=config,
        fmt=fmt,
    )


@inbox_proposals_app.command("reject")
def inbox_proposals_reject(
    proposal_id: str = typer.Argument(
        ..., help="Proposal id from inbox proposals list."
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    from paperful.inbox_cmd import run_inbox_proposals_reject

    run_inbox_proposals_reject(
        console,
        proposal_id=proposal_id,
        config=config,
        fmt=fmt,
    )


@notes_app.command("delete")
def notes_delete(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    item: list[str] = typer.Option([], "--item", help="Parent item key (repeatable)."),
    note_type: list[str] = typer.Option(
        [],
        "--type",
        help="summary, review, attach, duplicate, linked, snowball, briefing (repeatable).",
    ),
    model: str = typer.Option("", "--model", help="Only notes from this LLM id."),
    except_model: str = typer.Option(
        "",
        "--except-model",
        help="Skip this LLM id. Without --type, only summary and review notes.",
    ),
    all_owned: bool = typer.Option(
        False,
        "--all",
        help="Every Paperful-owned note in scope. Never user notes.",
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Trash matched notes. Default is dry-run."
    ),
    yes: bool = typer.Option(
        False, "--yes", help="Skip confirm on --apply --all (needed when not a TTY)."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = typer.Option(
        [],
        "-T",
        "--item-type",
        help="Only these Zotero parent item types (repeatable or comma-separated).",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Trash Paperful-owned notes. Never parent items. Dry-run unless --apply."""
    from paperful.notes_delete_cmd import run_notes_delete

    run_notes_delete(
        console,
        collection=collection,
        library=library,
        item=item,
        note_type=note_type,
        model=model,
        except_model=except_model,
        all_owned=all_owned,
        apply=apply,
        yes=yes,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@refs_app.command("gap")
def refs_gap(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    item: list[str] = typer.Option([], "--item", help="Seed item keys (repeatable)."),
    pdf: list[Path] = typer.Option(
        [],
        "--pdf",
        help="Extra PDF paths to scan (repeatable).",
        exists=True,
        dir_okay=False,
    ),
    dedupe_scope: str = typer.Option(
        "library",
        "--dedupe-scope",
        help="Fingerprint exists against library or collection.",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Works cited inside collection PDFs that are not in the library. Never writes."""
    from paperful.refs_gap_cmd import run_refs_gap

    run_refs_gap(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        item=item,
        pdf=pdf,
        dedupe_scope=dedupe_scope,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )
