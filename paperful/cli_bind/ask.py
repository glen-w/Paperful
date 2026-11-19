"""Signatures: rag, ask, summarize, synthesize, all, playbooks, profile."""

from __future__ import annotations

from pathlib import Path

import typer

from paperful.cli import (
    _agent_json,
    _typer_enum_value,
    _typer_opt,
    app,
    console,
    playbooks_app,
    profile_app,
    rag_app,
)
from paperful.cli_bind._shared import (
    AgentFormatOpt,
    ApplyOpt,
    BrowserAgentOpt,
    CamofoxOpt,
    ConfigOpt,
    EzproxyReloginOpt,
    ItemTypeOpt,
    LibraryOpt,
    NoAttachOpt,
    OverwriteOpt,
    ProfileOpt,
    ReRequestOpt,
    RequestRgOpt,
    RetryFailedOpt,
    RunConfigFileOpt,
    SciHubOpt,
    SkipOpt,
    StepsOpt,
    StrictPdfDoiOpt,
    SummarizeOrder,
    TryAllOpt,
    TwentyWritebackOpt,
    UpgradeLinkedOpt,
    UpgradeSnapshotOpt,
    WriteDest,
    YearFromOpt,
    YearToOpt,
    _cfg,
)


# ---- library index: `paperful rag` and `paperful ask` -------------------------
# These read out_dir and state_dir only. None of them opens the reference manager.


@rag_app.command("ingest")
def rag_ingest(
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    collection: list[str] = typer.Option(
        [],
        "--collection",
        "-C",
        help="Collection path under the mirror (repeatable).",
    ),
    library: bool | None = LibraryOpt,
    force: bool = typer.Option(
        False, "--force", help="Re-index items even when nothing changed."
    ),
    retry_failed: bool = typer.Option(
        False,
        "--retry-failed",
        help="Try again the PDFs that failed on an earlier run.",
    ),
    no_ocr: bool = typer.Option(
        False, "--no-ocr", help="Do not run OCR on scans this run."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be indexed. Writes nothing."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(
        None, "--limit", "-n", help="Index at most this many items this run."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Index PDFs and abstracts from the mirror. Scans get OCR first; text PDFs do not."""
    from paperful.rag_cmd import run_rag_ingest

    run_rag_ingest(
        console,
        item=item,
        collection=collection,
        library=library,
        force=force,
        retry_failed=retry_failed,
        no_ocr=no_ocr,
        dry_run=dry_run,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        profile=profile,
        run_config=run_config,
        config=config,
    )


@rag_app.command("status")
def rag_status(
    json_out: bool = typer.Option(False, "--json", help="Print JSON."),
    config: Path | None = ConfigOpt,
) -> None:
    """What the index holds and how far it is behind the mirror."""
    from paperful.rag_cmd import run_rag_status

    run_rag_status(
        console,
        json_out=json_out,
        config=config,
    )


@rag_app.command("search")
def rag_search(
    query: str = typer.Argument(..., help="What to look for."),
    top_k: int | None = typer.Option(None, "-k", "--top-k", help="Passages to show."),
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path under the mirror (repeatable)."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    json_out: bool = typer.Option(False, "--json", help="Print JSON."),
    config: Path | None = ConfigOpt,
) -> None:
    """Show the indexed passages closest to a query. No chat model is used."""
    from paperful.rag_cmd import run_rag_search

    run_rag_search(
        console,
        query=query,
        top_k=top_k,
        item=item,
        collection=collection,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        json_out=json_out,
        config=config,
    )


@rag_app.command("questions")
def rag_questions(
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path under the mirror (repeatable)."
    ),
    library: bool = typer.Option(False, "--library", help="Every indexed item."),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    llm: bool | None = typer.Option(
        None,
        "--llm/--no-llm",
        help="Also run the grounded LLM extract lane. Default is \\[rag].extract_questions_llm.",
    ),
    limit: int | None = typer.Option(None, "--limit", help="Max items this run."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print counts; do not write state/rag/questions/."
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Extract research questions from indexed papers (rules; optional LLM)."""
    from paperful.rag_cmd import run_rag_questions

    run_rag_questions(
        console,
        item=item,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        llm=llm,
        limit=limit,
        dry_run=dry_run,
        config=config,
        fmt=fmt,
    )


@rag_app.command("answered")
def rag_answered(
    from_file: Path | None = typer.Option(
        None, "--from-file", help="Questions file (one per line) or '-'."
    ),
    from_extract: bool = typer.Option(
        False,
        "--from-extract",
        help="Use questions under state/rag/questions/.",
    ),
    after_item: str | None = typer.Option(
        None,
        "--after-item",
        help="Only search items newer than this paper's year; exclude the asker.",
    ),
    item: list[str] = typer.Option(
        [],
        "--item",
        help="With --from-extract: only these asking items. Else: scope keys.",
    ),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path under the mirror (repeatable)."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    top_k: int | None = typer.Option(
        None, "-k", "--top-k", help="Passages per question."
    ),
    ask_mode: str | None = typer.Option(
        None,
        "--ask-mode",
        help="simple or advanced. Default is \\[rag].ask_mode.",
    ),
    force: bool = typer.Option(False, "--force", help="Ignore batch answer cache."),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Ask whether the corpus already answers research questions."""
    from paperful.rag_cmd import run_rag_answered

    run_rag_answered(
        console,
        from_file=from_file,
        from_extract=from_extract,
        after_item=after_item,
        item=item,
        collection=collection,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        top_k=top_k,
        ask_mode=ask_mode,
        force=force,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command()
def ask(
    question: str | None = typer.Argument(
        None, help="The question. Leave out to be prompted for several."
    ),
    top_k: int | None = typer.Option(
        None, "-k", "--top-k", help="Passages sent to the model."
    ),
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path under the mirror (repeatable)."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    from_file: Path | None = typer.Option(
        None,
        "--from-file",
        help="Batch: one question per line (file or '-'). Writes state/ask-batch/.",
    ),
    claim_check: bool = typer.Option(
        False,
        "--claim-check",
        help="Label each sentence against the local index (no LLM). Needs --file or --item.",
    ),
    file_path: Path | None = typer.Option(
        None,
        "--file",
        help="With --claim-check: manuscript path (xor --item).",
    ),
    focus: str | None = typer.Option(
        None,
        "--focus",
        help="Prompt preset: default, questions, gaps, methods, answered, conflict.",
    ),
    prompt: Path | None = typer.Option(
        None, "--prompt", help="Override system prompt file for this run."
    ),
    ask_mode: str | None = typer.Option(
        None,
        "--ask-mode",
        help="simple (raw excerpts) or advanced (score then answer). Default is \\[rag].ask_mode.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Batch: re-answer even when a cached row matches."
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Batch: write a Zotero collection note when --to includes zotero.",
    ),
    to: WriteDest | None = typer.Option(
        None,
        "--to",
        help="Batch note destination: disk, zotero, or both. Default is \\[rag].dest.",
    ),
    no_stream: bool = typer.Option(
        False, "--no-stream", help="Print the answer when it is complete."
    ),
    show_context: bool = typer.Option(
        False, "--show-context", help="List the passages the answer is built from."
    ),
    thread: str | None = typer.Option(
        None,
        "--thread",
        help="Follow-up thread under state/rag/threads/. 'new' starts one; omit for a one-shot.",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Answer a question from the indexed library, with sources. Needs `rag ingest` first."""
    cfg = _cfg(config)
    json_out = _agent_json(fmt)
    from paperful.ask_cmd import run_ask

    run_ask(
        console,
        cfg,
        question=question,
        top_k=top_k,
        item=item,
        collection=collection,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        from_file=from_file,
        focus=focus,
        prompt=prompt,
        force=force,
        apply=apply,
        to_dest=_typer_enum_value(to),
        no_stream=no_stream,
        show_context=show_context,
        thread=thread,
        profile=profile,
        run_config=run_config,
        json_out=json_out,
        ask_mode=ask_mode,
        claim_check=claim_check,
        file_path=file_path,
    )


@app.command()
def summarize(
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection scope (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    apply: bool | None = typer.Option(
        None,
        "--apply/--no-apply",
        help="Require a Zotero child note (conflicts with --to disk). Default dest already includes Zotero.",
    ),
    to: WriteDest | None = typer.Option(
        None,
        "--to",
        help="Where to write: disk, zotero, or both. Default is config, or both.",
    ),
    prompt: Path | None = typer.Option(
        None, "--prompt", help="Override summary prompt file for this run."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Regenerate even when a summary already exists, and summarize when "
            "the gated PDF identity check flags the item."
        ),
    ),
    order: SummarizeOrder | None = typer.Option(
        None,
        "--order",
        help=(
            "Queue order before --limit: newest, oldest, or library (manager "
            "order). Default is summarize.order in config, or library."
        ),
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n"),
    max_new: int | None = typer.Option(
        None,
        "--max-new",
        min=1,
        help="Stop after this many new model summaries (skips do not count).",
    ),
    max_minutes: float | None = typer.Option(
        None,
        "--max-minutes",
        min=0,
        help="Stop after this many minutes (finishes the paper in hand).",
    ),
    collections_file: Path | None = typer.Option(
        None,
        "--collections-file",
        exists=True,
        dir_okay=False,
        help="Text file: one collection path per line (appended to --collection).",
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Grounded LLM summary from local PDF text. Default writes disk and a Zotero note."""
    from paperful.completeness_cmd import run_summarize

    run_summarize(
        console,
        item=item,
        collection=collection,
        library=library,
        apply=apply,
        to_dest=_typer_enum_value(to),
        prompt=prompt,
        force=force,
        order_value=_typer_enum_value(order),
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        max_new=_typer_opt(max_new),
        max_minutes=_typer_opt(max_minutes),
        collections_file=collections_file,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command("extract-sections")
def extract_sections(
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path under the mirror (repeatable)."
    ),
    library: bool = typer.Option(False, "--library", help="Every item in the mirror."),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    llm: bool | None = typer.Option(
        None,
        "--llm/--no-llm",
        help="Fill missing MVP fields with a grounded LLM pass. Default is \\[extract_sections].llm.",
    ),
    limit: int | None = typer.Option(None, "--limit", help="Max items this run."),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print counts; do not write state/sections/.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-extract even when state/sections/<key>.json already exists.",
    ),
    grobid: bool | None = typer.Option(
        None,
        "--grobid/--no-grobid",
        help="Use the GROBID sidecar when available. Default is \\[grobid].enabled.",
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Extract IMRaD-style sections to disk (rules; optional GROBID / LLM)."""
    from paperful.sections_cmd import run_extract_sections

    run_extract_sections(
        console,
        item=item,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        llm=llm,
        limit=limit,
        dry_run=dry_run,
        force=force,
        grobid=grobid,
        config=config,
        fmt=fmt,
    )


@app.command()
def synthesize(
    item: list[str] = typer.Option([], "--item", help="Item key (repeatable)."),
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection scope (repeatable)."
    ),
    library: bool | None = LibraryOpt,
    to: WriteDest | None = typer.Option(
        None,
        "--to",
        help="Where to write the report: disk, zotero, or both. Default is config, or both.",
    ),
    report_collection: str | None = typer.Option(
        None,
        "--report-collection",
        help="Collection that receives the Zotero report note. Defaults to each -C root.",
    ),
    prompt: Path | None = typer.Option(
        None, "--prompt", help="Override the report prompt file for this run."
    ),
    layout: str | None = typer.Option(
        None,
        "--layout",
        help="Report shape: default, conflict, or review. Default \\[synthesize].layout. Ignored when --prompt is set.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show source counts and the chunk plan. No model call."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Regenerate even when the saved report used the same summary notes.",
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n"),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Literature review from summary notes already saved by summarize."""
    from paperful.completeness_cmd import run_synthesize

    run_synthesize(
        console,
        item=item,
        collection=collection,
        library=library,
        to_dest=_typer_enum_value(to),
        report_collection=report_collection,
        prompt=prompt,
        layout=layout,
        dry_run=dry_run,
        force=force,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
    )


@app.command("all")
def all_cmd(
    collection: list[str] = typer.Option(
        [],
        "--collection",
        "-C",
        help="Collection path/name/key (repeatable). Subcollections included.",
    ),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(
        None, "--limit", "-n", help="Stop after N items in each step."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="gaps, run --dry-run, lint, and fix-metadata without --apply. Skips summarize.",
    ),
    try_all: bool | None = TryAllOpt,
    retry_failed: bool | None = RetryFailedOpt,
    upgrade_linked: bool | None = UpgradeLinkedOpt,
    no_attach: bool | None = NoAttachOpt,
    strict_pdf_doi: bool | None = StrictPdfDoiOpt,
    scihub: bool | None = SciHubOpt,
    browser_agent: bool | None = BrowserAgentOpt,
    camofox: bool | None = CamofoxOpt,
    sources: str | None = typer.Option(
        None,
        "--sources",
        help="Comma-separated source order override for the run step.",
    ),
    preset: str | None = typer.Option(
        None, "--preset", help="Named source preset for the run step (eoi)."
    ),
    apply: bool | None = ApplyOpt,
    overwrite: bool | None = OverwriteOpt,
    steps: str | None = StepsOpt,
    skip: list[str] = SkipOpt,
    require_summarize: bool | None = typer.Option(
        None,
        "--require-summarize/--no-require-summarize",
        help="Exit 1 instead of skipping summarize when llm.enabled is false.",
    ),
    serpapi_max: int | None = typer.Option(
        None,
        "--serpapi-max",
        help="Cap paid SerpApi Scholar searches on the run step (0 = unlimited).",
    ),
    upgrade_snapshot: bool | None = UpgradeSnapshotOpt,
    keep_snapshot: bool = typer.Option(
        False,
        "--keep-snapshot",
        help="With --upgrade-snapshot on the run step, leave the HTML print beside the new PDF.",
    ),
    htmlpdf: str | None = typer.Option(
        None,
        "--htmlpdf",
        help="Academic HTML snapshot on the run step: off, gated, or auto.",
    ),
    handoff: str | None = typer.Option(
        None,
        "--handoff",
        help=(
            "After the run step: list|tabs|walk|watch for soft-blocked openable PDF URLs. "
            "watch = tabs then poll the inbox.dir folder."
        ),
    ),
    gaps_handoff: str | None = typer.Option(
        None,
        "--gaps-handoff",
        help=(
            "Handoff mode for the optional gaps_handoff step (defaults to --handoff). "
            "list|tabs|walk|watch."
        ),
    ),
    include_doi_tabs: bool = typer.Option(
        False,
        "--include-doi-tabs",
        help="With run or gaps_handoff handoff tabs|watch, also open doi.org for doi_only rows.",
    ),
    downloads_dir: Path | None = typer.Option(
        None,
        "--downloads-dir",
        help="Downloads dir for run/gaps_handoff --handoff walk (default ~/Downloads).",
    ),
    ezproxy_relogin: bool | None = EzproxyReloginOpt,
    twenty_writeback: bool | None = TwentyWritebackOpt,
    request_rg: bool | None = RequestRgOpt,
    re_request: bool = ReRequestOpt,
    promote: str | None = typer.Option(
        None,
        "--promote",
        help="Override \\[playbooks].promote on the run step: gated or auto.",
    ),
    after_handoff_gaps: bool = typer.Option(
        False,
        "--after-handoff-gaps",
        help=(
            "Append a gaps_handoff step after the chain when --handoff or --gaps-handoff is set: "
            "gaps --list-missing with the same handoff options."
        ),
    ),
    label: str | None = typer.Option(
        None, "--label", help="Pack label when this command opens a pack."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Run gaps, then fetch, lint, fix-metadata --apply, and summarize --apply.

    Stops on the first failing step, same as chaining the commands with ``&&``.
    """
    from paperful.all_cmd import run_all

    run_all(
        console,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        dry_run=dry_run,
        try_all=try_all,
        retry_failed=retry_failed,
        upgrade_linked=upgrade_linked,
        no_attach=no_attach,
        strict_pdf_doi=strict_pdf_doi,
        scihub=scihub,
        browser_agent=browser_agent,
        camofox=camofox,
        sources=sources,
        preset=preset,
        apply=apply,
        overwrite=overwrite,
        steps=steps,
        skip=skip,
        require_summarize=require_summarize,
        serpapi_max=serpapi_max,
        label=label,
        profile=profile,
        run_config=run_config,
        config=config,
        fmt=fmt,
        handoff=_typer_opt(handoff),
        gaps_handoff=_typer_opt(gaps_handoff),
        include_doi_tabs=include_doi_tabs,
        downloads_dir=_typer_opt(downloads_dir),
        promote=_typer_opt(promote),
        htmlpdf=_typer_opt(htmlpdf),
        keep_snapshot=keep_snapshot,
        ezproxy_relogin=_typer_opt(ezproxy_relogin),
        twenty_writeback=_typer_opt(twenty_writeback),
        request_rg=_typer_opt(request_rg),
        re_request=re_request,
        after_handoff_gaps=after_handoff_gaps,
    )


def _dispatch_all_step(*args, **kwargs):
    from paperful.all_cmd import _dispatch_all_step as _impl

    return _impl(*args, **kwargs)


@playbooks_app.command("probe")
def playbooks_probe(
    corpus: Path = typer.Option(
        ...,
        "--corpus",
        help="TOML file of \\[\\[targets]] (playbook, url or extra, note).",
        exists=True,
        dir_okay=False,
    ),
    config: Path | None = ConfigOpt,
    examples: bool = typer.Option(
        True,
        "--examples/--no-examples",
        help="Merge paperful/data/grey_playbooks_examples/ under the config playbooks.",
    ),
    check: int = typer.Option(
        3, "--check", help="How many extracted links to download per landing."
    ),
    min_bytes: int = typer.Option(
        10_000, "--min-bytes", help="Smallest body that counts as a PDF."
    ),
    delay: float = typer.Option(
        0.4, "--delay", help="Seconds to wait between targets."
    ),
    save: Path | None = typer.Option(
        None,
        "--save",
        help="Write one JSON per target plus index.json. Pass rows include the links needed to replay offline.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the rows as JSON."),
) -> None:
    """Fetch each corpus landing and require the first candidate to be a PDF.

    Exit 0 when every target passes. A pass is a %PDF body of at least
    --min-bytes. It does not prove the file is the record a listing page
    describes. This command talks to the network.
    """
    from paperful.playbooks_cmd import run_playbooks_probe

    run_playbooks_probe(
        console,
        corpus=corpus,
        config=config,
        examples=examples,
        check=check,
        min_bytes=min_bytes,
        delay=delay,
        save=save,
        as_json=as_json,
    )


@playbooks_app.command("propose")
def playbooks_propose(
    config: Path | None = ConfigOpt,
    to: Path | None = typer.Option(
        None,
        "--to",
        help="Write the draft TOML here (default: state/playbooks-proposed.toml).",
    ),
    min_hits: int = typer.Option(
        1, "--min-hits", help="Cluster size required in the draft (default 1)."
    ),
) -> None:
    """Draft learned playbooks from state/fetch-wins.jsonl. Does not install them."""
    from paperful.playbooks_cmd import run_playbooks_propose

    run_playbooks_propose(
        console,
        config=config,
        to=to,
        min_hits=min_hits,
    )


@playbooks_app.command("promote")
def playbooks_promote(
    config: Path | None = ConfigOpt,
    source: Path | None = typer.Option(
        None,
        "--from",
        help="Proposed TOML (default: state/playbooks-proposed.toml).",
    ),
) -> None:
    """Install proposed learned playbooks into grey_playbooks_dir/learned.toml."""
    from paperful.playbooks_cmd import run_playbooks_promote

    run_playbooks_promote(
        console,
        config=config,
        source=source,
    )


@profile_app.command("list")
def profile_list(config: Path | None = ConfigOpt) -> None:
    """List saved run configs. The builtin ``all`` policy is not a named profile."""
    from paperful.profile_cmd import run_profile_list

    run_profile_list(
        console,
        config=config,
    )


@profile_app.command("show")
def profile_show(
    name: str | None = typer.Argument(
        None, help="Profile name. Omit to show builtin all defaults."
    ),
    collection: list[str] = typer.Option([], "--collection", "-C"),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Note that summarize would be skipped."
    ),
    try_all: bool | None = TryAllOpt,
    retry_failed: bool | None = RetryFailedOpt,
    upgrade_linked: bool | None = UpgradeLinkedOpt,
    no_attach: bool | None = NoAttachOpt,
    strict_pdf_doi: bool | None = StrictPdfDoiOpt,
    scihub: bool | None = SciHubOpt,
    sources: str | None = typer.Option(None, "--sources"),
    preset: str | None = typer.Option(None, "--preset"),
    apply: bool | None = ApplyOpt,
    overwrite: bool | None = OverwriteOpt,
    steps: str | None = StepsOpt,
    skip: list[str] = SkipOpt,
    require_summarize: bool | None = typer.Option(
        None, "--require-summarize/--no-require-summarize"
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Print the effective ``paperful all`` config after profile and flag merge."""
    from paperful.profile_cmd import run_profile_show

    run_profile_show(
        console,
        name=name,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        dry_run=dry_run,
        try_all=try_all,
        retry_failed=retry_failed,
        upgrade_linked=upgrade_linked,
        no_attach=no_attach,
        strict_pdf_doi=strict_pdf_doi,
        scihub=scihub,
        sources=sources,
        preset=preset,
        apply=apply,
        overwrite=overwrite,
        steps=steps,
        skip=skip,
        require_summarize=require_summarize,
        profile=profile,
        run_config=run_config,
        config=config,
    )


@profile_app.command("save")
def profile_save(
    name: str = typer.Argument(
        ..., help="Profile name. Written to profiles/<name>.toml."
    ),
    collection: list[str] = typer.Option([], "--collection", "-C"),
    library: bool | None = LibraryOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    item_type: list[str] = ItemTypeOpt,
    limit: int | None = typer.Option(None, "--limit", "-n"),
    try_all: bool | None = TryAllOpt,
    retry_failed: bool | None = RetryFailedOpt,
    upgrade_linked: bool | None = UpgradeLinkedOpt,
    no_attach: bool | None = NoAttachOpt,
    strict_pdf_doi: bool | None = StrictPdfDoiOpt,
    scihub: bool | None = SciHubOpt,
    sources: str | None = typer.Option(None, "--sources"),
    preset: str | None = typer.Option(None, "--preset"),
    apply: bool | None = ApplyOpt,
    overwrite: bool | None = OverwriteOpt,
    steps: str | None = StepsOpt,
    skip: list[str] = SkipOpt,
    require_summarize: bool | None = typer.Option(
        None, "--require-summarize/--no-require-summarize"
    ),
    description: str | None = typer.Option(
        None, "--description", help="One-line note stored in the file."
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite an existing profile file."
    ),
    profile: str | None = ProfileOpt,
    run_config: Path | None = RunConfigFileOpt,
    config: Path | None = ConfigOpt,
) -> None:
    """Write profiles/<name>.toml beside config.toml. Does not edit config.toml."""
    from paperful.profile_cmd import run_profile_save

    run_profile_save(
        console,
        name=name,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        limit=limit,
        try_all=try_all,
        retry_failed=retry_failed,
        upgrade_linked=upgrade_linked,
        no_attach=no_attach,
        strict_pdf_doi=strict_pdf_doi,
        scihub=scihub,
        sources=sources,
        preset=preset,
        apply=apply,
        overwrite=overwrite,
        steps=steps,
        skip=skip,
        require_summarize=require_summarize,
        description=description,
        force=force,
        profile=profile,
        run_config=run_config,
        config=config,
    )
