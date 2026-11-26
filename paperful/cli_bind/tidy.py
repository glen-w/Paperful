"""Signatures: lint, screen, peer-review, rewrite, glossary, and the repair verbs."""

from __future__ import annotations

from pathlib import Path

import typer

from paperful.cli import (
    app,
    console,
    peer_review_app,
    glossary_app,
)
from paperful.cli_bind._shared import (
    AgentFormatOpt,
    ApplyOpt,
    ConfigOpt,
    ItemTypeOpt,
    LibraryOpt,
    OverwriteOpt,
    ProfileOpt,
    RunConfigFileOpt,
    YearFromOpt,
    YearToOpt,
)


@app.command()
def lint(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    as_json: bool = typer.Option(
        False, "--json", help="Legacy findings array. Prefer --format json."
    ),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if any finding."),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Read-only check of identifiers vs APIs and PDF text on disk. Does not write to the manager."""
    from paperful.lint_cmd import run_lint

    run_lint(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        as_json=as_json,
        strict=strict,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command()
def screen(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    as_json: bool = typer.Option(
        False, "--json", help="Legacy findings array. Prefer --format json."
    ),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if any finding."),
    apply: bool = typer.Option(
        False, "--apply", help="Write parent tag and child note for flagged items."
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Bypass status cache and re-download fingerprint CSVs."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Flag items using retraction APIs, optional PubPeer, and PPS fingerprint CSVs."""
    from paperful.screen_cmd import run_screen

    run_screen(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        as_json=as_json,
        strict=strict,
        apply=apply,
        refresh=refresh,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@peer_review_app.callback(invoke_without_command=True)
def peer_review(
    ctx: typer.Context,
    item: list[str] = typer.Option(
        [], "--item", help="Library item key already in the mirror."
    ),
    file_path: Path | None = typer.Option(
        None,
        "--file",
        help="Manuscript on disk (pdf, txt, md, html, rtf, docx, odt, pptx; .doc if a converter is on PATH). csv/xlsx/xls allowed for --forensics.",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    collection: list[str] = typer.Option(
        [],
        "--collection",
        "-C",
        help="Overlap/context corpus (path/name/key). Repeatable; collections are unioned.",
    ),
    library: bool | None = LibraryOpt,
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print findings; do not write state/peer-reviews/."
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Write a child note. Needs --item (not --file)."
    ),
    llm: bool | None = typer.Option(
        None,
        "--llm/--no-llm",
        help="Alias for --lane reviewers (compat). Adds or removes that suggested review lane.",
    ),
    ai_model: bool = typer.Option(
        False,
        "--ai-model",
        help="Optional Binoculars extra (git overlay; suggested; not installed by default).",
    ),
    vale: bool = typer.Option(
        False,
        "--vale",
        help="Optional Vale house-style pass (checked lane). Needs vale on PATH and a .vale.ini.",
    ),
    discourse: bool | None = typer.Option(
        None,
        "--discourse/--no-discourse",
        help="Academic discourse hygiene (weasel/hype/chatbot). Default: \\[peer_review].discourse (on).",
    ),
    forensics: bool = typer.Option(
        False,
        "--forensics",
        help="Optional PaperGuard scan (suggested extra). Needs paperguard on PATH.",
    ),
    advanced: bool | None = typer.Option(
        None,
        "--advanced/--no-advanced",
        help="Alias for --lane marg (compat). MARG-S-style multi-agent comments.",
    ),
    lane: list[str] = typer.Option(
        [],
        "--lane",
        help="Suggested review lane (repeatable): reviewers, marg, adversary, outline, claims, verify, context, context-web.",
    ),
    grobid: bool | None = typer.Option(
        None,
        "--grobid/--no-grobid",
        help="Use the GROBID sidecar for MARG-S / claims / verify PDF chunks. Default is \\[grobid].enabled.",
    ),
    reviewer: list[str] = typer.Option(
        [],
        "--reviewer",
        help="Run a subset of peer_review.reviewers ids (repeatable). Default: all.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Run the LLM lane even when identity lint flagged the PDF.",
    ),
    show_dismissed: bool = typer.Option(
        False,
        "--show-dismissed",
        help="Include dismissed findings in the table and Markdown.",
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Local manuscript peer-review pack. Checked findings always; suggested review lanes optional. Not a grade."""
    if ctx.invoked_subcommand is not None:
        return
    from paperful.peer_review_cmd import run_peer_review

    run_peer_review(
        console,
        item=item,
        file_path=file_path,
        collection=collection,
        library=library,
        dry_run=dry_run,
        apply=apply,
        llm=llm,
        ai_model=ai_model,
        vale=vale,
        discourse=discourse,
        forensics=forensics,
        advanced=advanced,
        lane=lane,
        grobid=grobid,
        reviewer=reviewer,
        force=force,
        show_dismissed=show_dismissed,
        config=config,
        fmt=fmt,
    )


@peer_review_app.command("dismiss")
def peer_review_dismiss(
    finding_id: str = typer.Argument(
        ..., help="Finding id from pack.json / the peer-review table."
    ),
    peer_review_id: str | None = typer.Option(
        None,
        "--peer-review-id",
        help="Pack folder name (item key or file-<stem>). Default: newest.",
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Omit a finding from later pack.md (id stays in JSON). Re-runs keep the dismissal."""
    from paperful.peer_review_cmd import run_dismiss

    run_dismiss(
        console,
        finding_id=finding_id,
        peer_review_id=peer_review_id,
        config=config,
        fmt=fmt,
    )


@app.command()
def rewrite(
    pack_path: Path | None = typer.Option(
        None,
        "--pack",
        help="Existing peer-review pack.json or its folder. Never re-runs peer-review.",
        exists=True,
    ),
    item: list[str] = typer.Option(
        [],
        "--item",
        help="Library item key; uses the latest peer-review pack for that id.",
    ),
    file_path: Path | None = typer.Option(
        None,
        "--file",
        help="Draft to edit. Uses the latest pack for file-<stem> unless --pack is set.",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    area: list[str] = typer.Option(
        [],
        "--area",
        help="Rewrite area (repeatable): style, cites, structure, comments, all. Default: \\[rewrite].areas.",
    ),
    output: list[str] = typer.Option(
        [],
        "--output",
        help="Output (repeatable): edits, sidecar, tracked, odt, pdf. Default: \\[rewrite].outputs.",
    ),
    comments: str | None = typer.Option(
        None,
        "--comments",
        help="Word comments: off, substantive, or all. Default: \\[rewrite].comments.",
    ),
    sanitize: bool | None = typer.Option(
        None,
        "--sanitize/--no-sanitize",
        help="Strip hidden trackers on the copy Paperful writes. Default: \\[rewrite].sanitize.",
    ),
    sanitize_invisible: bool | None = typer.Option(
        None,
        "--sanitize-invisible/--no-sanitize-invisible",
        help="Purge zero-width / bidi / Unicode tag characters on the copy.",
    ),
    sanitize_c2pa: bool | None = typer.Option(
        None,
        "--sanitize-c2pa/--no-sanitize-c2pa",
        help="Strip C2PA provenance parts from office/PDF copies.",
    ),
    sanitize_trackers: bool | None = typer.Option(
        None,
        "--sanitize-trackers/--no-sanitize-trackers",
        help="Fold homoglyphs and perturb closed-class tokens on the copy.",
    ),
    tracker_scope: str | None = typer.Option(
        None,
        "--tracker-scope",
        help="edited (default) or all. Statistical tracker shatter scope.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the plan; do not write state/rewrites/."
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Apply a peer-review pack to a draft. Writes an edit plan and optional sidecar / Word / OpenDocument / PDF. Never overwrites the source."""
    from paperful.rewrite_cmd import run_rewrite

    run_rewrite(
        console,
        pack_path=pack_path,
        item=item,
        file_path=file_path,
        area=area,
        output=output,
        comments=comments,
        sanitize=sanitize,
        sanitize_invisible=sanitize_invisible,
        sanitize_c2pa=sanitize_c2pa,
        sanitize_trackers=sanitize_trackers,
        tracker_scope=tracker_scope,
        dry_run=dry_run,
        config=config,
        fmt=fmt,
    )


@app.command()
def acronyms(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    min_count: int = typer.Option(
        2, "--min-count", min=1, help="Items a short token must appear in."
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write state/acronyms/<scope>.json. Default prints the list only.",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Harvest all-caps tokens from mixed-case titles, abstracts, and venues.

    Frequency and shape only. Does not call a model and does not recase titles.
    ``fix-metadata`` uses the written list when it Title-Cases an ALL CAPS title.
    """
    from paperful.acronyms_cmd import run_acronyms

    run_acronyms(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        min_count=min_count,
        apply=apply,
        profile=profile,
        run_config=run_config,
        config=config,
    )


@glossary_app.command("validate")
def glossary_validate(
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Check state/glossary/*.json (paperful.glossary.v1)."""
    from paperful.glossary_cmd import run_glossary_validate

    run_glossary_validate(console, config=config, fmt=fmt)


@glossary_app.command("export-vale")
def glossary_export_vale(
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Write YAML here. Default prints a Substitution style fragment.",
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Write Vale swap rules from glossary aliases (exact forms only)."""
    from paperful.glossary_cmd import run_glossary_export_vale

    run_glossary_export_vale(console, config=config, fmt=fmt, out=out)


@app.command()
def authors(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    min_count: int = typer.Option(
        2, "--min-count", min=1, help="Items an author or org must appear in."
    ),
    max_authors: int = typer.Option(
        15,
        "--max-authors",
        min=1,
        help="Top people written into the proposed field author pack on --apply.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help=(
            "Write state/reports/<scope>-authors.json and seed "
            "state/author-packs/<slug>.proposed.toml. Default prints the tables only."
        ),
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Frequency report for creators in scope; seed a proposed field author pack.

    People are counted by name fingerprint; corporate ``name``-only creators are
    orgs. Dry-run prints tables. ``--apply`` writes the report and merges top
    people into a proposed pack (promote before ``author_site`` fetch).
    """
    from paperful.authors_cmd import run_authors

    run_authors(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        min_count=min_count,
        max_authors=max_authors,
        apply=apply,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command("fix-metadata")
def fix_metadata(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    offset: int = typer.Option(
        0,
        "--offset",
        help="Skip the first N items in library/collection order before applying --limit.",
        min=0,
    ),
    apply: bool | None = ApplyOpt,
    overwrite: bool | None = OverwriteOpt,
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Propose bibliographic patches on disk; --apply writes them through the library adapter.

    `run` never rewrites metadata. This is the only write path for DOI/title/date/venue.
    """
    from paperful.fix_metadata_cmd import run_fix_metadata

    run_fix_metadata(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        offset=offset,
        apply=apply,
        overwrite=overwrite,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command()
def dedupe(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Write the pack only. This is the default; do not combine with --apply.",
    ),
    apply: bool | None = typer.Option(
        None,
        "--apply/--no-apply",
        help="Merge high_doi extras onto the keeper, then trash them (Zotero 10+). Title+year needs --apply-medium.",
    ),
    apply_medium: bool = typer.Option(
        False,
        "--apply-medium",
        help="Also merge title+year extras. Off by default.",
    ),
    phase: str = typer.Option(
        "all",
        "--phase",
        help="high_doi, grey_id, grey_host, medium_title_year, or all (default). Apply runs high_doi and grey_id first. grey_host needs --apply-medium.",
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    as_json: bool = typer.Option(
        False, "--json", help="Legacy pack paths JSON. Prefer --format json."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Find duplicate parents and write a review pack. Merge only with --apply.

    Default is classify-only. ``--apply`` writes a plain-language line on each
    spare copy, then merges. Same-DOI groups whose titles diverge are held.
    A profile's ``apply`` flag does not merge; pass --apply on this command.
    """
    from paperful.completeness_cmd import run_dedupe

    run_dedupe(
        console,
        collection=collection,
        library=library,
        dry_run=dry_run,
        apply=apply,
        apply_medium=apply_medium,
        phase=phase,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        as_json=as_json,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command()
def attachments(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Report only. This is the default; do not combine with --apply.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Run the named surgery flags. With no flags, this still only writes the report.",
    ),
    fix_broken: bool | None = typer.Option(
        None,
        "--fix-broken/--no-fix-broken",
        help="Refill a ghost or broken link from out/ when the MD5 matches.",
    ),
    merge_files: bool | None = typer.Option(
        None,
        "--merge-files/--no-merge-files",
        help="Trash extra PDF children on the same parent that share an MD5.",
    ),
    rename: bool | None = typer.Option(
        None,
        "--rename/--no-rename",
        help="Rename attachment files under out/ to the mirror stem.",
    ),
    link: bool | None = typer.Option(
        None,
        "--link/--no-link",
        help="Turn a stored PDF into a linked file under out/. Personal library only.",
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    as_json: bool = typer.Option(False, "--json", help="Print the summary as JSON."),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Compare attachments to the out/ mirror. Surgery needs a flag and --apply.

    Zotero can repair, rename, and link. Mendeley can upload and delete cloud
    files. EndNote only writes the report. ``--link`` is Zotero only.
    Paths outside out/ are never moved or deleted.
    """
    from paperful.completeness_cmd import run_attachments

    run_attachments(
        console,
        collection=collection,
        library=library,
        dry_run=dry_run,
        apply=apply,
        fix_broken=fix_broken,
        merge_files=merge_files,
        rename=rename,
        link=link,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        as_json=as_json,
        profile=profile,
        run_config=run_config,
        config=config,
    )


@app.command()
def versions(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Write the pack only. This is the default; do not combine with --apply.",
    ),
    apply: bool | None = typer.Option(
        None,
        "--apply/--no-apply",
        help="Write the published citation onto the existing parent and keep the preprint as a version.",
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    as_json: bool = typer.Option(
        False, "--json", help="Print pack paths and counts as JSON."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Link a preprint and its published paper as one work. Write only with --apply.

    The older parent keeps the citation key. Its fields become the version of
    record and the published PDF is attached beside the preprint PDF. A later
    sibling is trashed only after that PDF is on the survivor. Title-only
    matches are listed and not applied."""
    from paperful.versions_cmd import run_versions

    run_versions(
        console,
        collection=collection,
        library=library,
        dry_run=dry_run,
        apply=apply,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        as_json=as_json,
        profile=profile,
        run_config=run_config,
        config=config,
    )
