"""Signatures: snowball and its profile, packs, and watch groups."""

from __future__ import annotations

from rich.markup import escape
from pathlib import Path
from typing import Any

import typer

from paperful.cli import (
    LibraryError,
    _connect,
    _exit_env,
    _flush,
    console,
    snowball_app,
)
from paperful.config import Config
from paperful.cli_bind._shared import (
    AgentFormatOpt,
    AuthorSitePreflightOpt,
    CitesQueryOpt,
    ConfigOpt,
    CreateTagOpt,
    DIRECTION_HELP,
    DedupeAfterOpt,
    DedupeScopeOpt,
    FetchPdfsOpt,
    KeywordHopLimitOpt,
    KeywordLimitOpt,
    KeywordMinScoreOpt,
    ListedInOpt,
    MaxCandidatesOpt,
    PerHopLimitOpt,
    PerHopRankOpt,
    ProfileOpt,
    SearchKeywordsOpt,
    SeedsFileOpt,
    StopEpsOpt,
    StopKOpt,
    StopMaxScreenedOpt,
    StopRuleOpt,
    StudyDesignOpt,
    TwentyWritebackOpt,
    YearFromOpt,
    YearToOpt,
)


@snowball_app.command("search")
def snowball_search(
    queries: list[str] = typer.Argument(..., help="One or more keyword terms."),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    depth: int | None = typer.Option(
        None, "--depth", help="0 = hits only. Expand hits when >= 1."
    ),
    max_candidates: str | None = MaxCandidatesOpt,
    per_hop_limit: str | None = PerHopLimitOpt,
    per_hop_rank: str | None = PerHopRankOpt,
    direction: str | None = typer.Option(
        None, "--direction", help=DIRECTION_HELP + " Used when depth >= 1."
    ),
    keyword_limit: str | None = KeywordLimitOpt,
    keyword_hop_limit: str | None = KeywordHopLimitOpt,
    keyword_min_score: float | None = KeywordMinScoreOpt,
    search_keywords: bool | None = SearchKeywordsOpt,
    cites_query: str | None = CitesQueryOpt,
    study_design: list[str] = StudyDesignOpt,
    listed_in: list[str] = ListedInOpt,
    or_mode: bool = typer.Option(
        False, "--or", help="Match any keyword (default: all)."
    ),
    gate: str | None = typer.Option(
        None,
        "--gate",
        help="dry-run, approve-each, approve-batch, or auto. Default: config, else dry-run.",
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Target collection for --gate auto."
    ),
    fetch_pdfs: str | None = FetchPdfsOpt,
    languages: str | None = typer.Option(
        None, "--languages", help="Comma-separated language codes."
    ),
    min_seed_citations: int | None = typer.Option(None, "--min-seed-citations"),
    note_provenance: bool | None = typer.Option(
        None, "--note-provenance/--no-note-provenance"
    ),
    backends: str | None = typer.Option(
        None, "--backends", help="Comma-separated backend names."
    ),
    refine: bool | None = typer.Option(
        None, "--refine/--no-refine", help="Ask the LLM for query suggestions."
    ),
    tag: list[str] = CreateTagOpt,
    dedupe_scope: str | None = DedupeScopeOpt,
    dedupe_after: str | None = DedupeAfterOpt,
    author_site_preflight: bool | None = AuthorSitePreflightOpt,
    twenty_writeback: bool | None = TwentyWritebackOpt,
    stop_rule: str | None = StopRuleOpt,
    stop_eps: float | None = StopEpsOpt,
    stop_k: int | None = StopKOpt,
    stop_max_screened: int | None = StopMaxScreenedOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Search OpenAlex and write a candidate queue. Creates items only with --gate auto."""
    from paperful.snowball_cmd import run_snowball_search

    run_snowball_search(
        console,
        queries=queries,
        year_from=year_from,
        year_to=year_to,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        search_keywords=search_keywords,
        cites_query=cites_query,
        study_design=study_design,
        listed_in=listed_in,
        or_mode=or_mode,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        languages=languages,
        min_seed_citations=min_seed_citations,
        note_provenance=note_provenance,
        backends=backends,
        refine=refine,
        tag=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
        config=config,
        fmt=fmt,
    )


@snowball_app.command("hybrid")
def snowball_hybrid(
    queries: list[str] = typer.Argument(
        ..., help="One or more keyword terms. Top hits then get one hop."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    max_candidates: str | None = MaxCandidatesOpt,
    per_hop_limit: str | None = PerHopLimitOpt,
    per_hop_rank: str | None = PerHopRankOpt,
    hybrid_seeds: int | None = typer.Option(
        None, "--hybrid-seeds", help="How many top DOI hits to expand."
    ),
    direction: str | None = typer.Option(None, "--direction", help=DIRECTION_HELP),
    keyword_limit: str | None = KeywordLimitOpt,
    keyword_hop_limit: str | None = KeywordHopLimitOpt,
    keyword_min_score: float | None = KeywordMinScoreOpt,
    search_keywords: bool | None = SearchKeywordsOpt,
    cites_query: str | None = CitesQueryOpt,
    study_design: list[str] = StudyDesignOpt,
    listed_in: list[str] = ListedInOpt,
    or_mode: bool = typer.Option(
        False, "--or", help="Match any keyword (default: all)."
    ),
    gate: str | None = typer.Option(
        None, "--gate", help="dry-run, approve-each, approve-batch, or auto."
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Target collection for a writing gate."
    ),
    fetch_pdfs: str | None = FetchPdfsOpt,
    languages: str | None = typer.Option(None, "--languages"),
    min_seed_citations: int | None = typer.Option(None, "--min-seed-citations"),
    refine: bool | None = typer.Option(None, "--refine/--no-refine"),
    tag: list[str] = CreateTagOpt,
    dedupe_scope: str | None = DedupeScopeOpt,
    dedupe_after: str | None = DedupeAfterOpt,
    author_site_preflight: bool | None = AuthorSitePreflightOpt,
    twenty_writeback: bool | None = TwentyWritebackOpt,
    stop_rule: str | None = StopRuleOpt,
    stop_eps: float | None = StopEpsOpt,
    stop_k: int | None = StopKOpt,
    stop_max_screened: int | None = StopMaxScreenedOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Keyword hits, then one hop from the top DOIs. Not a separate harvest command."""
    from paperful.snowball_cmd import run_snowball_hybrid

    run_snowball_hybrid(
        console,
        queries=queries,
        year_from=year_from,
        year_to=year_to,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        hybrid_seeds=hybrid_seeds,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        search_keywords=search_keywords,
        cites_query=cites_query,
        study_design=study_design,
        listed_in=listed_in,
        or_mode=or_mode,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        languages=languages,
        min_seed_citations=min_seed_citations,
        refine=refine,
        tag=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
        config=config,
        fmt=fmt,
    )


@snowball_app.command("doi")
def snowball_doi(
    dois: list[str] | None = typer.Argument(
        None, help="One or more seed DOIs. Optional when --seeds-file is set."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    depth: int | None = typer.Option(
        None, "--depth", help="Graph hops. Default: \\[snowball] depth, else 1."
    ),
    max_candidates: str | None = MaxCandidatesOpt,
    per_hop_limit: str | None = PerHopLimitOpt,
    per_hop_rank: str | None = PerHopRankOpt,
    direction: str | None = typer.Option(None, "--direction", help=DIRECTION_HELP),
    keyword_limit: str | None = KeywordLimitOpt,
    keyword_hop_limit: str | None = KeywordHopLimitOpt,
    keyword_min_score: float | None = KeywordMinScoreOpt,
    cites_query: str | None = CitesQueryOpt,
    study_design: list[str] = StudyDesignOpt,
    listed_in: list[str] = ListedInOpt,
    gate: str | None = typer.Option(
        None,
        "--gate",
        help="dry-run, approve-each, approve-batch, or auto. Default: config, else dry-run.",
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Target collection for --gate auto."
    ),
    fetch_pdfs: str | None = FetchPdfsOpt,
    tag: list[str] = CreateTagOpt,
    dedupe_scope: str | None = DedupeScopeOpt,
    dedupe_after: str | None = DedupeAfterOpt,
    author_site_preflight: bool | None = AuthorSitePreflightOpt,
    twenty_writeback: bool | None = TwentyWritebackOpt,
    stop_rule: str | None = StopRuleOpt,
    stop_eps: float | None = StopEpsOpt,
    stop_k: int | None = StopKOpt,
    stop_max_screened: int | None = StopMaxScreenedOpt,
    seeds_file: str | None = SeedsFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Bibliography and/or citing works of each DOI. Creates items only with --gate auto."""
    from paperful.snowball_cmd import run_snowball_doi

    run_snowball_doi(
        console,
        dois=dois,
        year_from=year_from,
        year_to=year_to,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        cites_query=cites_query,
        study_design=study_design,
        listed_in=listed_in,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        tag=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
        seeds_file=seeds_file,
        config=config,
        fmt=fmt,
    )


@snowball_app.command("orcid")
def snowball_orcid(
    orcids: list[str] | None = typer.Argument(
        None, help="One or more ORCID iDs. Optional when --seeds-file is set."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    depth: int | None = typer.Option(
        None, "--depth", help="Graph hops. Default: \\[snowball] depth, else 1."
    ),
    max_candidates: str | None = MaxCandidatesOpt,
    per_hop_limit: str | None = PerHopLimitOpt,
    per_hop_rank: str | None = PerHopRankOpt,
    direction: str | None = typer.Option(None, "--direction", help=DIRECTION_HELP),
    keyword_limit: str | None = KeywordLimitOpt,
    keyword_hop_limit: str | None = KeywordHopLimitOpt,
    keyword_min_score: float | None = KeywordMinScoreOpt,
    cites_query: str | None = CitesQueryOpt,
    study_design: list[str] = StudyDesignOpt,
    listed_in: list[str] = ListedInOpt,
    gate: str | None = typer.Option(
        None,
        "--gate",
        help="dry-run, approve-each, approve-batch, or auto. Default: config, else dry-run.",
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Target collection for --gate auto."
    ),
    fetch_pdfs: str | None = FetchPdfsOpt,
    tag: list[str] = CreateTagOpt,
    dedupe_scope: str | None = DedupeScopeOpt,
    dedupe_after: str | None = DedupeAfterOpt,
    author_site_preflight: bool | None = AuthorSitePreflightOpt,
    twenty_writeback: bool | None = TwentyWritebackOpt,
    stop_rule: str | None = StopRuleOpt,
    stop_eps: float | None = StopEpsOpt,
    stop_k: int | None = StopKOpt,
    stop_max_screened: int | None = StopMaxScreenedOpt,
    seeds_file: str | None = SeedsFileOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """People's works (ORCID + OpenAlex), then references/citations those works expand to."""
    from paperful.snowball_cmd import run_snowball_orcid

    run_snowball_orcid(
        console,
        orcids=orcids,
        year_from=year_from,
        year_to=year_to,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        cites_query=cites_query,
        study_design=study_design,
        listed_in=listed_in,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        tag=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
        seeds_file=seeds_file,
        config=config,
        fmt=fmt,
    )


@snowball_app.command("collection")
def snowball_collection(
    seed_collection: str = typer.Argument(
        ..., help="Existing library collection whose DOIs seed the crawl."
    ),
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    depth: int | None = typer.Option(
        None, "--depth", help="Graph hops. Default: \\[snowball] depth, else 1."
    ),
    max_candidates: str | None = MaxCandidatesOpt,
    per_hop_limit: str | None = PerHopLimitOpt,
    per_hop_rank: str | None = PerHopRankOpt,
    direction: str | None = typer.Option(None, "--direction", help=DIRECTION_HELP),
    keyword_limit: str | None = KeywordLimitOpt,
    keyword_hop_limit: str | None = KeywordHopLimitOpt,
    keyword_min_score: float | None = KeywordMinScoreOpt,
    cites_query: str | None = CitesQueryOpt,
    study_design: list[str] = StudyDesignOpt,
    listed_in: list[str] = ListedInOpt,
    gate: str | None = typer.Option(
        None,
        "--gate",
        help="dry-run, approve-each, approve-batch, or auto. Default: config, else dry-run.",
    ),
    collection: str = typer.Option(
        "",
        "--collection",
        "-C",
        help="Target collection for --gate auto (defaults to the seed collection).",
    ),
    fetch_pdfs: str | None = FetchPdfsOpt,
    tag: list[str] = CreateTagOpt,
    dedupe_scope: str | None = DedupeScopeOpt,
    dedupe_after: str | None = DedupeAfterOpt,
    author_site_preflight: bool | None = AuthorSitePreflightOpt,
    twenty_writeback: bool | None = TwentyWritebackOpt,
    stop_rule: str | None = StopRuleOpt,
    stop_eps: float | None = StopEpsOpt,
    stop_k: int | None = StopKOpt,
    stop_max_screened: int | None = StopMaxScreenedOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Expand DOIs already in a collection. Creates items only with --gate auto."""
    from paperful.snowball_cmd import run_snowball_collection

    run_snowball_collection(
        console,
        seed_collection=seed_collection,
        year_from=year_from,
        year_to=year_to,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        cites_query=cites_query,
        study_design=study_design,
        listed_in=listed_in,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        tag=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
        config=config,
        fmt=fmt,
    )


def _print_briefing(
    briefing: Any, *, apply: bool, collection: str, cfg: Config
) -> None:
    counts = briefing.counts
    order = ("new", "exists", "deferred", "inbox")
    summary = " · ".join(f"{key} {counts[key]}" for key in order if key in counts)
    console.print(summary)
    console.print(f"Wrote [bold]{briefing.path}[/]")
    if not apply:
        return
    if not collection.strip():
        console.print("[red]--apply needs -C so the note has a collection.[/]")
        raise typer.Exit(1)
    backend = _connect(cfg)
    if not backend.supports_write():
        _exit_env("A briefing note needs library write support.", cfg)
    try:
        col = backend.resolve_collection(collection.strip())
        key = backend.create_or_update_collection_note(
            col.key, briefing.html, ["paperful:frontier-briefing"]
        )
    except LibraryError as exc:
        console.print(f"[red]{escape(str(exc))}[/]")
        raise typer.Exit(2) from exc
    _flush(backend)
    console.print(f"Note [bold]{key}[/] in {col.path or collection}")


@snowball_app.command("trends")
def snowball_trends(
    query: str | None = typer.Argument(
        None, help="OpenAlex search string (or use --profile)."
    ),
    profile: str | None = ProfileOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Publication-year counts for a query or saved search/hybrid profile. Read-only."""
    from paperful.snowball_cmd import run_snowball_trends

    run_snowball_trends(
        console,
        query=query,
        profile=profile,
        year_from=year_from,
        year_to=year_to,
        config=config,
        fmt=fmt,
    )


@snowball_app.command("briefing")
def snowball_briefing(
    run_id: str = typer.Option(
        ..., "--run-id", help="Queue under state/snowball/<run-id>/."
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Also file a collection note tagged paperful:frontier-briefing. Needs -C.",
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Collection for the note when --apply."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Write markdown for a saved snowball queue. Does not create items."""
    from paperful.snowball_cmd import run_snowball_briefing

    run_snowball_briefing(
        console,
        run_id=run_id,
        apply=apply,
        collection=collection,
        config=config,
    )


@snowball_app.command("digest")
def snowball_digest(
    run_id: str = typer.Option(
        ..., "--run-id", help="Queue under state/snowball/<run-id>/."
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Also file a collection note tagged paperful:frontier-briefing. Needs -C.",
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Collection for the note when --apply."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Write a ranked frontier digest for a saved queue. Does not create items."""
    from paperful.snowball_cmd import run_snowball_digest

    run_snowball_digest(
        console,
        run_id=run_id,
        apply=apply,
        collection=collection,
        config=config,
    )


@snowball_app.command("resume")
def snowball_resume(
    run_id: str = typer.Argument(
        ..., help="Run id under state/snowball/<run-id>/ with deferred.json."
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Target collection when the saved gate is auto."
    ),
    gate: str | None = typer.Option(
        None, "--gate", help="dry-run or auto. Default: config."
    ),
    tag: list[str] = CreateTagOpt,
    dedupe_scope: str | None = DedupeScopeOpt,
    dedupe_after: str | None = DedupeAfterOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Continue OpenAlex work saved when the daily budget was spent. Same API key."""
    from paperful.snowball_cmd import run_snowball_resume

    run_snowball_resume(
        console,
        run_id=run_id,
        collection=collection,
        gate=gate,
        tag=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        config=config,
        fmt=fmt,
    )


@snowball_app.command("continue")
def snowball_continue_cmd(
    run_id: str = typer.Argument(
        ..., help="Run id under state/snowball/<run-id>/ with stop.json."
    ),
    gate: str | None = typer.Option(
        None,
        "--gate",
        help="auto marks unlabeled new rows as Keep. Default: the gate saved with the run.",
    ),
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Score Keep/Skip on the latest hop, then walk one more hop unless a stopping rule fires."""
    from paperful.snowball_cmd import run_snowball_continue

    run_snowball_continue(
        console,
        run_id=run_id,
        gate=gate,
        config=config,
        fmt=fmt,
    )


@snowball_app.command("apply")
def snowball_apply(
    run_id: str = typer.Argument(..., help="Run id under state/snowball/<run-id>/."),
    collection: str = typer.Option("", "--collection", "-C", help="Target collection."),
    fetch_pdfs: str | None = FetchPdfsOpt,
    tag: list[str] = CreateTagOpt,
    dedupe_scope: str | None = DedupeScopeOpt,
    dedupe_after: str | None = DedupeAfterOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Create keep=true rows from a prior queue (approve-batch or edited dry-run)."""
    from paperful.snowball_cmd import run_snowball_apply

    run_snowball_apply(
        console,
        run_id=run_id,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        tag=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        config=config,
        fmt=fmt,
    )


@snowball_app.command("run")
def snowball_run(
    profile: str = typer.Option(
        ..., "--profile", help="profiles/<name>.toml with kind = snowball."
    ),
    direction: str = typer.Option("", "--direction", help=DIRECTION_HELP),
    keyword_limit: str | None = KeywordLimitOpt,
    keyword_hop_limit: str | None = KeywordHopLimitOpt,
    keyword_min_score: float | None = KeywordMinScoreOpt,
    cites_query: str | None = CitesQueryOpt,
    tag: list[str] = CreateTagOpt,
    dedupe_scope: str | None = DedupeScopeOpt,
    dedupe_after: str | None = DedupeAfterOpt,
    author_site_preflight: bool | None = AuthorSitePreflightOpt,
    twenty_writeback: bool | None = TwentyWritebackOpt,
    stop_rule: str | None = StopRuleOpt,
    stop_eps: float | None = StopEpsOpt,
    stop_k: int | None = StopKOpt,
    stop_max_screened: int | None = StopMaxScreenedOpt,
    config: Path | None = ConfigOpt,
    fmt: str = AgentFormatOpt,
) -> None:
    """Run a saved snowball profile (keyword, DOI, ORCID, or collection)."""
    from paperful.snowball_cmd import run_snowball_run

    run_snowball_run(
        console,
        profile=profile,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        cites_query=cites_query,
        tag=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
        config=config,
        fmt=fmt,
    )


snowball_profile_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Save a snowball profile beside config.toml. Seeds and knobs only.",
)
snowball_app.add_typer(snowball_profile_app, name="profile")


@snowball_profile_app.command("save")
def snowball_profile_save(
    name: str = typer.Argument(..., help="Profile name (profiles/<name>.toml)."),
    query: list[str] | None = typer.Option(
        None, "--query", help="Keyword seed. Repeat for several."
    ),
    doi: list[str] | None = typer.Option(
        None, "--doi", help="DOI seed. Repeat for several."
    ),
    orcid: list[str] | None = typer.Option(
        None, "--orcid", help="ORCID seed. Repeat for several."
    ),
    seed_collection: str = typer.Option(
        "", "--seed-collection", help="Collection whose DOIs seed the crawl."
    ),
    description: str = typer.Option("", "--description"),
    gate: str = typer.Option("dry-run", "--gate"),
    collection: str = typer.Option("", "--collection", "-C", help="Target collection."),
    fetch_pdfs: str = typer.Option("", "--fetch-pdfs", help="off, fast, or full."),
    depth: int | None = typer.Option(None, "--depth"),
    max_candidates: str | None = MaxCandidatesOpt,
    per_hop_limit: str | None = PerHopLimitOpt,
    per_hop_rank: str | None = PerHopRankOpt,
    direction: str = typer.Option("", "--direction", help=DIRECTION_HELP),
    keyword_limit: str | None = KeywordLimitOpt,
    keyword_hop_limit: str | None = KeywordHopLimitOpt,
    keyword_min_score: float | None = KeywordMinScoreOpt,
    search_keywords: bool | None = SearchKeywordsOpt,
    cites_query: str | None = CitesQueryOpt,
    study_design: list[str] = StudyDesignOpt,
    listed_in: list[str] = ListedInOpt,
    year_from: int | None = YearFromOpt,
    year_to: int | None = YearToOpt,
    dedupe_scope: str = typer.Option("", "--dedupe-scope"),
    dedupe_after: str = typer.Option("", "--dedupe-after"),
    oa_only: bool = typer.Option(False, "--oa-only"),
    or_mode: bool = typer.Option(
        False, "--or", help="With several --query, match any (default: all)."
    ),
    hybrid: bool = typer.Option(
        False, "--hybrid", help="With --query, save mode = hybrid."
    ),
    languages: str = typer.Option("", "--languages"),
    min_seed_citations: int | None = typer.Option(None, "--min-seed-citations"),
    note_provenance: bool | None = typer.Option(
        None, "--note-provenance/--no-note-provenance"
    ),
    backends: str = typer.Option("", "--backends"),
    hybrid_seeds: int | None = typer.Option(None, "--hybrid-seeds"),
    refine: bool = typer.Option(False, "--refine"),
    author_site_preflight: bool = typer.Option(False, "--author-site-preflight"),
    stop_rule: str = typer.Option(
        "",
        "--stop-rule",
        help="off, marginal_yield, asymptotic_coverage, budget, or any.",
    ),
    stop_eps: float | None = StopEpsOpt,
    stop_k: int | None = StopKOpt,
    stop_max_screened: int | None = StopMaxScreenedOpt,
    seeds_file: str | None = SeedsFileOpt,
    force: bool = typer.Option(
        False, "--force", help="Overwrite, or save a writing gate."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Write seeds and knobs. Refuses API keys. A writing gate needs --force."""
    from paperful.snowball_cmd import run_snowball_profile_save

    run_snowball_profile_save(
        console,
        name=name,
        query=query,
        doi=doi,
        orcid=orcid,
        seed_collection=seed_collection,
        description=description,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        search_keywords=search_keywords,
        cites_query=cites_query,
        study_design=study_design,
        listed_in=listed_in,
        year_from=year_from,
        year_to=year_to,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        oa_only=oa_only,
        or_mode=or_mode,
        hybrid=hybrid,
        languages=languages,
        min_seed_citations=min_seed_citations,
        note_provenance=note_provenance,
        backends=backends,
        hybrid_seeds=hybrid_seeds,
        refine=refine,
        author_site_preflight=author_site_preflight,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
        seeds_file=seeds_file,
        force=force,
        config=config,
    )


snowball_packs_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Proposed field author packs from snowball preflight. Promote before fetch uses them.",
)
snowball_app.add_typer(snowball_packs_app, name="packs")


@snowball_packs_app.command("promote")
def snowball_packs_promote(
    slug: str = typer.Argument(
        ..., help="Pack slug (state/author-packs/<slug>.proposed.toml)."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Copy a proposed author pack to the promoted file used by the author_site lane."""
    from paperful.snowball_cmd import run_snowball_packs_promote

    run_snowball_packs_promote(
        console,
        slug=slug,
        config=config,
    )


snowball_watch_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Pull-only watch: re-run a snowball profile, remember seen works, "
        "propose new arrivals on disk. Never creates library items. "
        "Paperful does not schedule watches; call watch run yourself."
    ),
)
snowball_app.add_typer(snowball_watch_app, name="watch")


@snowball_watch_app.command("save")
def snowball_watch_save(
    name: str = typer.Argument(
        ..., help="Watch name under state/snowball/watches/<name>/."
    ),
    profile: str = typer.Option(
        ..., "--profile", help="Existing kind=snowball profile."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Point a watch at a saved snowball profile. No API keys."""
    from paperful.snowball_cmd import run_snowball_watch_save

    run_snowball_watch_save(
        console,
        name=name,
        profile=profile,
        config=config,
    )


@snowball_watch_app.command("run")
def snowball_watch_run(
    name: str = typer.Argument(..., help="Watch name."),
    dedupe_scope: str | None = DedupeScopeOpt,
    digest: bool = typer.Option(
        False,
        "--digest",
        help="Also write watches/<name>/digest.md after a successful run.",
    ),
    refresh: bool = typer.Option(
        False,
        "--refresh",
        help=(
            "Skip the last-run date cursor and rewrite the watch response cache "
            "from this fetch. Paperful still does not schedule watches."
        ),
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Baseline on first run; later runs write only unseen new works to the inbox."""
    from paperful.snowball_cmd import run_snowball_watch_run

    run_snowball_watch_run(
        console,
        name=name,
        dedupe_scope=dedupe_scope,
        digest=digest,
        refresh=refresh,
        config=config,
    )


@snowball_watch_app.command("rebaseline")
def snowball_watch_rebaseline(
    name: str = typer.Argument(
        "", help="Watch name. Leave empty with --all to check every watch."
    ),
    all_watches: bool = typer.Option(False, "--all", help="Every saved watch."),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write the reset. Without it this only reports what would change.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Reset even if the watch was already reset or baselined after the change.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Re-baseline keyword watches once after OpenAlex's Oct 2026 topic change.

    The next `watch run` then absorbs reassigned works as seen instead of
    proposing them as new. Does not touch the inbox or open the library.
    """
    from paperful.snowball_cmd import run_snowball_watch_rebaseline

    run_snowball_watch_rebaseline(
        console,
        name=name,
        all_watches=all_watches,
        apply=apply,
        force=force,
        config=config,
    )


@snowball_watch_app.command("show")
def snowball_watch_show(
    name: str = typer.Argument(..., help="Watch name."),
    config: Path | None = ConfigOpt,
) -> None:
    """Inbox count and latest run id. Does not open the library."""
    from paperful.snowball_cmd import run_snowball_watch_show

    run_snowball_watch_show(
        console,
        name=name,
        config=config,
    )


@snowball_watch_app.command("briefing")
def snowball_watch_briefing(
    name: str = typer.Argument(..., help="Watch name."),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Also file a collection note tagged paperful:frontier-briefing. Needs -C.",
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Collection for the note when --apply."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Write markdown for a watch inbox. Does not create items."""
    from paperful.snowball_cmd import run_snowball_watch_briefing

    run_snowball_watch_briefing(
        console,
        name=name,
        apply=apply,
        collection=collection,
        config=config,
    )


@snowball_watch_app.command("digest")
def snowball_watch_digest(
    name: str = typer.Argument(..., help="Watch name."),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Also file a collection note tagged paperful:frontier-briefing. Needs -C.",
    ),
    collection: str = typer.Option(
        "", "--collection", "-C", help="Collection for the note when --apply."
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Write a ranked frontier digest for a watch. Does not create items."""
    from paperful.snowball_cmd import run_snowball_watch_digest

    run_snowball_watch_digest(
        console,
        name=name,
        apply=apply,
        collection=collection,
        config=config,
    )


@snowball_watch_app.command("apply")
def snowball_watch_apply(
    name: str = typer.Argument(..., help="Watch name."),
    collection: str = typer.Option(
        ..., "--collection", "-C", help="Target collection path."
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Create metadata parents from the watch inbox. Default is dry-run.",
    ),
    config: Path | None = ConfigOpt,
) -> None:
    """Create parents from watches/<name>/inbox.jsonl. PDFs stay paperful run."""
    from paperful.snowball_cmd import run_snowball_watch_apply

    run_snowball_watch_apply(
        console,
        name=name,
        collection=collection,
        apply=apply,
        config=config,
    )
