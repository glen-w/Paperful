"""Signatures: packs, ingest, sync, restore, interchange, reports, sessions, ocr."""

from __future__ import annotations

from pathlib import Path

import typer

from paperful.cli import (
    _typer_opt,
    app,
    cache_app,
    console,
    openalex_store_app,
    pack_app,
    session_app,
    twenty_app,
)
from paperful.cli_bind._shared import (
    AgentFormatOpt,
    ApplyOpt,
    ConfigOpt,
    ItemTypeOpt,
    LibraryOpt,
    ProfileOpt,
    RunConfigFileOpt,
    YearFromOpt,
    YearToOpt,
)


@app.command("coverage")
def coverage_cmd(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection to check membership against."
    ),
    from_note: str | None = typer.Option(
        None,
        "--from-note",
        help="Zotero note key, or a path to note HTML/markdown.",
    ),
    from_file: Path | None = typer.Option(
        None,
        "--from-file",
        help="Markdown / text / DOI list file.",
        exists=True,
        dir_okay=False,
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """DOIs named in a briefing/note/file that are not filed under -C. Always dry-run."""
    from paperful.coverage_cmd import run_coverage

    run_coverage(
        console,
        collection=collection,
        from_note=from_note,
        from_file=from_file,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command("since")
def since_cmd(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    since: str = typer.Option(
        "",
        "--since",
        help="Compare to the newest run report on or before this date (YYYY-MM-DD).",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-n",
        min=1,
        help="Probe at most N earlier misses (best-ranked first) and N snapshot PDFs.",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """What changed since the last run. Always dry-run: no downloads, no writes."""
    from paperful.since_cmd import run_since

    run_since(
        console,
        collection=collection,
        library=library,
        since=since,
        limit=limit,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command("precedent")
def precedent_cmd(
    query: str = typer.Argument(..., help="Methods or hypothesis phrase."),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item: list[str] = typer.Option(
        [], "--item", help="Narrow held search to these item keys (repeatable)."
    ),
    seed_doi: str = typer.Option(
        "",
        "--seed-doi",
        help="DOI whose similar neighbours join the public list.",
    ),
    held_k: int | None = typer.Option(
        None,
        "-k",
        "--held-k",
        help="Held RAG passages to keep. Default \\[precedent].held_k.",
    ),
    public_k: int | None = typer.Option(
        None,
        "--public-k",
        help="OpenAlex / similar works to keep. Default \\[precedent].public_k.",
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
    """Held passages plus OpenAlex works for a phrase. Always dry-run. Not a novelty claim."""
    from paperful.precedent_cmd import run_precedent

    run_precedent(
        console,
        query=query,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item=item,
        seed_doi=seed_doi,
        held_k=held_k,
        public_k=public_k,
        dedupe_scope=dedupe_scope,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command("stuff")
def stuff_cmd(
    item: list[str] = typer.Option(
        [], "--item", help="Library item key already in the mirror."
    ),
    file_path: Path | None = typer.Option(
        None,
        "--file",
        help="Draft on disk (pdf, txt, md, html, rtf, docx, odt, pptx; .doc if a converter is on PATH).",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path under the mirror (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    k: int | None = typer.Option(
        None,
        "-k",
        "--k",
        help="Extra sources per claim. Default \\[stuff].k, capped by \\[rag].top_k.",
    ),
    lane: str | None = typer.Option(
        None,
        "--lane",
        help="Retrieval unit: manuscript (sentences) or outline (sections). Default \\[stuff].lane.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print counts; do not write state/stuff/."
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Extra library citations per sentence or outline section. No LLM. Not a rewrite."""
    from paperful.stuff_cmd import run_stuff

    run_stuff(
        console,
        item=item,
        file_path=file_path,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        k=k,
        lane=lane,
        dry_run=dry_run,
        config=config,
        fmt=fmt,
    )


@twenty_app.command("lookup")
def twenty_lookup_cmd(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write proposed author-pack listings and state/author-contacts/. Default is dry-run.",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Match collection authors against Twenty People. Read-only unless --apply."""
    from paperful.twenty_cmd import run_twenty_lookup

    run_twenty_lookup(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        apply=apply,
        profile=profile,
        run_config=run_config,
        config=config,
    )


@twenty_app.command("sync")
def twenty_sync_cmd(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Create and enrich Twenty People. Default is dry-run.",
    ),
    limit: int = typer.Option(
        0, "--limit", "-n", help="Only the first N person authors (0 = all)."
    ),
    yes: bool = typer.Option(
        False, "--yes", help="Skip confirm when --apply would create many People."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Create or enrich Twenty People from collection authors. Dry-run unless --apply."""
    from paperful.twenty_cmd import run_twenty_sync

    run_twenty_sync(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        apply=apply,
        limit=limit,
        yes=yes,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command("ingest-dois")
def ingest_dois_cmd(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Target collection for new parents."
    ),
    from_file: Path | None = typer.Option(
        None,
        "--from-file",
        help="Text file: one DOI per line.",
        exists=True,
        dir_okay=False,
    ),
    from_pack: Path | None = typer.Option(
        None,
        "--from-pack",
        help="refs_gap, coverage, or precedent pack.json (or its parent folder).",
        exists=True,
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Create parents. Default is dry-run."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Classify only (default)."),
    tag: list[str] = typer.Option(
        [], "--tag", help="Extra tags on created parents (repeatable)."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Create metadata parents from a DOI list. Dry-run unless --apply. Then run fills PDFs."""
    from paperful.ingest_cmd import run_ingest_dois

    run_ingest_dois(
        console,
        collection=collection,
        from_file=from_file,
        from_pack=from_pack,
        apply=apply,
        dry_run=dry_run,
        tag=tag,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command()
def snapshot(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Count what would be written. Still reads Zotero."
    ),
    pdfs: str | None = typer.Option(
        None,
        "--pdfs",
        help="all (also copy library PDFs), lazy (fetched PDFs only), or none.",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Write per-item restore folders under out/. --dry-run counts and does not write."""
    from paperful.snapshot_cmd import run_snapshot_cmd

    run_snapshot_cmd(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        dry_run=dry_run,
        pdfs=pdfs,
        profile=profile,
        run_config=run_config,
        config=config,
    )


@cache_app.command("clean")
def cache_clean(
    apply: bool | None = ApplyOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Remove pdf-cache files already in the mirror (or stale vs the record MD5).

    Dry-run unless ``--apply``. Does not touch ``out/``.
    """
    from paperful.cache_cmd import run_cache_clean

    run_cache_clean(console, apply=apply, config=config, fmt=fmt)


@openalex_store_app.command("build-cites")
def openalex_store_build_cites(
    out: str = typer.Option(
        "",
        "--out",
        help=(
            "Directory for the inverted cites parquet tree. "
            "Default: directory implied by \\[openalex_store].cites_index_glob."
        ),
    ),
    timeout_s: float | None = typer.Option(
        None,
        "--timeout-s",
        help=(
            "Per-partition DuckDB timeout in seconds "
            "(default: build_timeout_s or 7200)."
        ),
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Invert works.referenced_works into a cites index for store-backed citing.

    Needs \\[openalex_store] with a works parquet_glob. Point cites_index_glob at
    ``<out>/**/*.parquet`` afterward (or use --out that matches that glob).

    Builds one works ``updated_date`` partition at a time and writes
    ``.done/<date>`` markers — safe to re-run after a crash. Full OpenAlex
    dumps can take many hours; for a remote host prefer a nohup'd build on
    that machine so a laptop disconnect does not stop the job.
    """
    from paperful.sync_cmd import run_openalex_store_build_cites

    run_openalex_store_build_cites(
        console,
        out=out,
        timeout_s=timeout_s,
        config=config,
    )


@app.command()
def sync(
    full: bool = typer.Option(
        False, "--full", help="Read the whole library, not only what changed."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Count what would change. Reads the library, writes nothing.",
    ),
    pdfs: str | None = typer.Option(
        None,
        "--pdfs",
        help="all (copy every library PDF into the mirror), lazy (on first use), or none.",
    ),
    accept_gone: bool = typer.Option(
        False,
        "--accept-gone",
        help="Proceed when most mirrored items are not in this library.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Bring out/ up to date with the library. Reads what changed since the last refresh."""
    from paperful.sync_cmd import run_sync_command

    run_sync_command(
        console,
        full=full,
        dry_run=dry_run,
        pdfs=pdfs,
        accept_gone=accept_gone,
        config=config,
    )


@app.command()
def restore(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = typer.Option(
        None,
        "--library/--no-library",
        help="Whole out/ tree instead of one collection. --no-library clears a profile.",
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(
        None, "--limit", "-n", help="Stop after N folders."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be created. Does not write the library.",
    ),
    apply: bool | None = typer.Option(
        None,
        "--apply/--no-apply",
        help="Create missing items, attach local PDFs, and add missing notes.",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Recreate missing library items from out/. Dry-run unless --apply. Never overwrites fields."""
    from paperful.restore_cmd import run_restore

    run_restore(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        dry_run=dry_run,
        apply=apply,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command("import")
def import_library(
    path: Path = typer.Argument(
        ..., exists=True, dir_okay=False, help="RIS, BibTeX, or EndNote XML file."
    ),
    fmt: str | None = typer.Option(
        None,
        "--format",
        help="ris, bibtex, endnote-xml, or json (agent envelope; file type from the suffix).",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write into the current manager. Default is a dry-run count.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Import a bibliography file. Default is a dry-run count; --apply writes the library."""
    from paperful.sync_cmd import run_import_library

    run_import_library(
        console,
        path=path,
        fmt=fmt,
        apply=apply,
        config=config,
    )


@app.command("export")
def export_library(
    dest: Path = typer.Argument(
        ..., help="Output .ris / .bib / .xml file (or a folder for EndNote XML)."
    ),
    fmt: str | None = typer.Option(
        None,
        "--format",
        help="ris, bibtex, or endnote-xml. Default: from the file suffix.",
    ),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool = typer.Option(False, "--library", help="Whole library."),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n"),
    pdfs: bool = typer.Option(
        False,
        "--pdfs/--no-pdfs",
        help="Copy PDFs next to the export (needed for EndNote XML).",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Export the scoped library to RIS, BibTeX, or EndNote XML."""
    from paperful.export_cmd import run_export_library

    run_export_library(
        console,
        dest=dest,
        fmt=fmt,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        pdfs=pdfs,
        config=config,
    )


@app.command("export-proposals")
def export_proposals(
    pack: Path = typer.Argument(
        ...,
        help=(
            "Snowball run dir, watch dir, authorwatch dir, or a candidates/inbox "
            ".jsonl file under state/."
        ),
    ),
    dest: Path = typer.Argument(..., help="Output .bib or .ris file."),
    fmt: str | None = typer.Option(
        None,
        "--format",
        help="bibtex or ris. Default: from the file suffix.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Export BibTeX or RIS from an on-disk snowball or authorwatch proposal pack."""
    from paperful.report_cmd import run_export_proposals

    run_export_proposals(
        console,
        pack=pack,
        dest=dest,
        fmt=fmt,
        config=config,
    )


@app.command("run-report-counts")
def run_report_counts_cmd(
    report_file: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        help="paperful run report JSON from state/runs/",
    ),
) -> None:
    """One-line counts summary for Nightshift index lines."""
    from paperful.report_cmd import run_report_counts

    run_report_counts(
        console,
        report_file=report_file,
    )


@app.command("run-report-new-count")
def run_report_new_count_cmd(
    report_file: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        help="paperful summarize run report JSON",
    ),
) -> None:
    """Count new model summaries in a run report (skips do not count)."""
    from paperful.report_cmd import run_report_new_count

    run_report_new_count(
        console,
        report_file=report_file,
    )


@app.command()
def report(
    config: Path | None = ConfigOpt,
    not_found: bool = typer.Option(
        False, "--not-found", help="List not_found items with DOIs."
    ),
    status: str | None = typer.Option(
        None, "--status", help="List items with this status."
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Machine-readable summary for agents."
    ),
    last_run: bool = typer.Option(
        False, "--last-run", help="Show only the latest run report summary."
    ),
) -> None:
    """Summarise the manifest and the latest auditable run report."""
    from paperful.report_cmd import run_report

    run_report(
        console,
        config=config,
        not_found=not_found,
        status=status,
        as_json=as_json,
        last_run=last_run,
    )


@pack_app.command("open")
def pack_open(
    label: str | None = typer.Option(None, "--label", help="Name stored on the pack."),
    config: Path | None = ConfigOpt,
) -> None:
    """Start a pack. Later commands append their run reports until `pack close`."""
    from paperful.pack_cmd import run_pack_open

    run_pack_open(console, label=label, config=config)


@pack_app.command("close")
def pack_close(config: Path | None = ConfigOpt) -> None:
    """Close the open pack and drop the current pointer."""
    from paperful.pack_cmd import run_pack_close

    run_pack_close(console, config=config)


@pack_app.command("show")
def pack_show(
    as_json: bool = typer.Option(
        False, "--json", help="Parent pack plus each step's summary."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Print the open pack, or the latest closed one. Does not open the library."""
    from paperful.pack_cmd import run_pack_show

    run_pack_show(console, as_json=as_json, config=config)


@app.command()
def mirrors(config: Path | None = ConfigOpt) -> None:
    """Ping the configured Sci-Hub mirrors."""
    from paperful.mirrors_cmd import run_mirrors

    run_mirrors(console, config=config)


@session_app.command("login")
def session_login(
    slot: str = typer.Argument(..., help="scholar, ezproxy, or mendeley"),
    config: Path | None = ConfigOpt,
    engine: str = typer.Option(
        "auto",
        "--engine",
        help="Browser for headed login: auto (system Chrome if present), chrome, playwright",
    ),
) -> None:
    """Open a headed browser on the local vault; log in once, reuse on run."""
    from paperful.session_cmd import run_session_login

    run_session_login(console, slot=slot, config=config, engine=engine)


@session_app.command("status")
def session_status(
    config: Path | None = ConfigOpt,
    probe: bool = typer.Option(
        False, "--probe/--no-probe", help="Hit Scholar / EZProxy session_ok (network)"
    ),
) -> None:
    """Show the vault. Default is offline file presence; --probe runs session_ok."""
    from paperful.session_cmd import run_session_status

    run_session_status(console, config=config, probe=probe)


@session_app.command("export")
def session_export(config: Path | None = ConfigOpt) -> None:
    """Refresh storage_state + Netscape from the vault (keeps session tickets)."""
    from paperful.session_cmd import run_session_export

    run_session_export(console, config=config)


@app.command("ezproxy")
def ezproxy_cmd(
    config: Path | None = ConfigOpt,
    open_browser: bool = typer.Option(
        True, "--open/--no-open", help="Open headed Chromium (or the system browser)"
    ),
) -> None:
    """Check / refresh the campus EZProxy session (wrapper for session login ezproxy)."""
    from paperful.session_cmd import run_ezproxy

    run_ezproxy(console, config=config, open_browser=open_browser)


@app.command("scholar")
def scholar_cmd(
    config: Path | None = ConfigOpt,
    open_browser: bool = typer.Option(
        True, "--open/--no-open", help="Open headed Chromium (or the system browser)"
    ),
) -> None:
    """Check / refresh Google Scholar (wrapper for session login scholar)."""
    from paperful.session_cmd import run_scholar

    run_scholar(console, config=config, open_browser=open_browser)


@app.command()
def recover(
    item: list[str] = typer.Option(
        [], "--item", help="Zotero item key to recover (repeatable)."
    ),
    from_last_run: bool = typer.Option(
        False,
        "--from-last-run",
        help="Recover items from state/last-run.json (see --from-last-run-mode).",
    ),
    from_last_run_mode: str = typer.Option(
        "browser_agent_miss",
        "--from-last-run-mode",
        help="browser_agent_miss | missing | browser_agent_not_found",
    ),
    limit: int | None = typer.Option(
        None, "--limit", "-n", help="Stop after N items (batch recover)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show start URL only; no browser agent."
    ),
    no_attach: bool = typer.Option(
        False, "--no-attach", help="Download to out/ only; do not attach in Zotero."
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Browser-agent PDF recovery for named items (also auto-fires at the end of run)."""
    from paperful.recover_cmd import run_recover

    run_recover(
        console,
        item=item,
        from_last_run=from_last_run,
        from_last_run_mode=from_last_run_mode,
        limit=limit,
        dry_run=dry_run,
        no_attach=no_attach,
        config=config,
        fmt=fmt,
    )


@app.command()
def ocr(
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection scope (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    apply: bool = typer.Option(
        False, "--apply", help="Run OCRmyPDF and replace the on-disk PDF."
    ),
    attach: bool = typer.Option(
        False,
        "--attach",
        help="After --apply, upload the text-layer PDF as a new attachment. The scan stays.",
    ),
    force_retry: bool = typer.Option(
        False,
        "--force-retry",
        help="Run OCR on items in state/ocr-ignore.jsonl (normally skipped).",
    ),
    no_auto_ignore_failures: bool = typer.Option(
        False,
        "--no-auto-ignore-failures",
        help="Do not append failed or missing items to the OCR ignore list after --apply.",
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n"),
    max_minutes: float | None = typer.Option(
        None,
        "--max-minutes",
        min=0,
        help="Stop after this many minutes (finishes the PDF in hand).",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Add a text layer to scanned PDFs on disk. Dry-run unless --apply."""
    from paperful.ocr_cmd import run_ocr

    run_ocr(
        console,
        item=item,
        collection=collection,
        library=library,
        apply=apply,
        attach=attach,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        max_minutes=_typer_opt(max_minutes),
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
        force_retry=force_retry,
        no_auto_ignore_failures=no_auto_ignore_failures,
    )


ocr_ignore_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Skip list for ``paperful ocr`` (failed or missing PDFs). Ledger: state/ocr-ignore.jsonl.",
)
app.add_typer(ocr_ignore_app, name="ocr-ignore")


@ocr_ignore_app.command("list")
def ocr_ignore_list(
    config: Path | None = ConfigOpt,
) -> None:
    """Show ignored item keys."""
    from paperful.ocr_ignore_cmd import run_ocr_ignore_list

    run_ocr_ignore_list(console, config=config)


@ocr_ignore_app.command("add")
def ocr_ignore_add(
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    reason: str = typer.Option("", "--reason", help="Why this item is ignored."),
    config: Path | None = ConfigOpt,
) -> None:
    """Add item keys to the OCR ignore list."""
    from paperful.ocr_ignore_cmd import run_ocr_ignore_add

    run_ocr_ignore_add(console, item=item, reason=reason, config=config)


@ocr_ignore_app.command("remove")
def ocr_ignore_remove(
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    config: Path | None = ConfigOpt,
) -> None:
    """Remove item keys from the OCR ignore list."""
    from paperful.ocr_ignore_cmd import run_ocr_ignore_remove

    run_ocr_ignore_remove(console, item=item, config=config)


@ocr_ignore_app.command("import-failures")
def ocr_ignore_import_failures(
    report: Path | None = typer.Option(
        None,
        "--report",
        help="OCR run report JSON (default: newest state/runs/*-ocr.json).",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Add every failed or missing row from an OCR run report to the ignore list."""
    from paperful.ocr_ignore_cmd import run_ocr_ignore_import_failures

    run_ocr_ignore_import_failures(console, report=report, config=config)
