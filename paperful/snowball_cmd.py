"""``paperful snowball`` implementation (CLI parses flags only)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from .config import Config, parse_pdfs
from .library import LibraryError
from .runreport import write_command_report, write_run_report
from .store import Manifest
from . import cli_runtime as cli_mod

def _snowball_request(
    cfg: Config,
    *,
    gate: str | None,
    collection: str | None,
    fetch_pdfs: str | bool | None,
    depth: int | None,
    max_candidates: str | int | None,
    per_hop_limit: str | int | None = None,
    per_hop_rank: str | None = None,
    year_from: int | None,
    year_to: int | None,
    direction: str | None = None,
    keyword_limit: str | int | None = None,
    keyword_hop_limit: str | int | None = None,
    keyword_min_score: float | None = None,
    search_keywords: bool | None = None,
    cites_query: str | None = None,
    languages: str | None = None,
    study_designs: list[str] | str | None = None,
    min_seed_citations: int | None = None,
    note_provenance: bool | None = None,
    backends: str | None = None,
    hybrid_seeds: int | None = None,
    refine: bool | None = None,
    tags: list[str] | None = None,
    dedupe_scope: str | None = None,
    dedupe_after: str | None = None,
    author_site_preflight: bool | None = None,
    twenty_writeback: bool | None = None,
    stop_rule: str | None = None,
    stop_eps: float | None = None,
    stop_k: int | None = None,
    stop_max_screened: int | None = None,
) -> Any:
    from .snowball.command import SnowballRequest
    from .snowball.expand import parse_study_designs

    if twenty_writeback is not None:
        cfg.twenty_writeback_listings = twenty_writeback
    designs = None
    if study_designs:
        try:
            designs = parse_study_designs(study_designs)
        except ValueError as exc:
            cli_mod.console.print(f"[red]{exc}[/]")
            raise typer.Exit(2) from exc
    return SnowballRequest(
        gate=gate or cfg.snowball_gate,
        collection=(collection or cfg.snowball_target_collection or ""),
        fetch_pdfs=cfg.snowball_fetch_pdfs if fetch_pdfs is None else fetch_pdfs,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        year_from=year_from,
        year_to=year_to,
        direction=direction or cfg.snowball_direction or "refs+keywords",
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        search_keywords=search_keywords,
        cites_query=(cites_query or "").strip(),
        languages=_csv(languages) if languages else None,
        study_designs=designs,
        min_seed_citations=min_seed_citations,
        note_provenance=note_provenance,
        backends=_csv(backends) if backends else None,
        hybrid_seeds=hybrid_seeds,
        refine=refine,
        link_versions=True,
        tags=tuple(str(t).strip() for t in (tags or []) if str(t).strip()),
        dedupe_scope=(dedupe_scope or "").strip() or None,
        dedupe_after=(dedupe_after or "").strip() or None,
        author_site_preflight=author_site_preflight,
        stop_rule=(stop_rule or "").strip() or None,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
    )

def _csv(raw: str | None) -> tuple[str, ...]:
    return tuple(part.strip() for part in (raw or "").split(",") if part.strip())

def _compose_keywords(queries: list[str], *, or_mode: bool) -> str:
    from .snowball.expand import compose_keyword_query

    notices: list[str] = []
    query = compose_keyword_query(queries, op="or" if or_mode else "and", notices=notices)
    for note in notices:
        cli_mod.console.print(f"[yellow]{note}[/]")
    return query

def _doi_seeds(dois: list[str] | None, seeds_file: str | Path | None) -> list[str]:
    from .snowball.seeds import dois_from_seeds, merge_tokens, parse_seed_lines, read_seeds_text

    extra: list[str] = []
    if seeds_file is not None:
        extra = parse_seed_lines(read_seeds_text(str(seeds_file)))
    merged = merge_tokens(list(dois or []), extra)
    if not merged:
        from .snowball.command import SnowballError

        raise SnowballError("Pass one or more DOIs or --seeds-file.")
    return dois_from_seeds(merged)

def _orcid_seeds(orcids: list[str] | None, seeds_file: str | Path | None) -> list[str]:
    from .snowball.seeds import merge_tokens, orcids_from_seeds, parse_seed_lines, read_seeds_text

    extra: list[str] = []
    if seeds_file is not None:
        extra = parse_seed_lines(read_seeds_text(str(seeds_file)))
    merged = merge_tokens(list(orcids or []), extra)
    if not merged:
        from .snowball.command import SnowballError

        raise SnowballError("Pass one or more ORCID iDs or --seeds-file.")
    return orcids_from_seeds(merged)

def _profile_queries(body: dict[str, Any], queries: list[str], *, or_mode: bool) -> None:
    """Persist one ``query`` or a ``queries`` array (+ optional ``query_op``)."""
    if len(queries) == 1:
        body["query"] = queries[0]
    else:
        body["queries"] = list(queries)
    if or_mode:
        body["query_op"] = "or"

def _snowball_console(*, json_out: bool) -> Console:
    if json_out:
        # Live E2E babysits long snowball phases; keep progress on stderr.
        quiet = os.environ.get("PAPERFUL_E2E") != "1"
        return Console(file=sys.stderr, highlight=False, quiet=quiet)
    return cli_mod.console

def _run_snowball(
    cfg: Config,
    action: Any,
    *,
    json_out: bool = False,
    command: str = "snowball",
) -> None:
    from .snowball.command import SnowballError
    from .agent_ops import snowball_result_envelope

    snowball_started = time.time()
    try:
        result = action(cfg)
    except SnowballError as exc:
        if json_out:
            Console(stderr=True, highlight=False).print(f"[red]{exc}[/]")
        else:
            cli_mod.console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    cli_mod._rag_auto(cfg, snowball_started)
    # Writing gates join the run-report / witness trail (dry-run crawls stay queue-only).
    if command in {"snowball apply"}:
        summary = dict(getattr(result, "summary", None) or {})
        summary.setdefault("write_api", None)
        run_dir = getattr(result, "run_dir", None)
        write_command_report(
            cfg,
            command=command,
            scope=str(run_dir or ""),
            summary=summary,
            items=[],
            flags={"run_dir": str(run_dir or "")},
            started=snowball_started,
            extra_paths={"run": str(run_dir)} if run_dir else None,
        )
    if json_out:
        payload = snowball_result_envelope(command, result)
        cli_mod._emit_agent(payload, json_out=True, human=lambda: None)
        return
    if result.exit_code:
        raise typer.Exit(result.exit_code)


def _print_briefing(briefing: Any, *, apply: bool, collection: str, cfg: Config) -> None:
    counts = briefing.counts
    order = ("new", "exists", "deferred", "inbox")
    summary = " · ".join(f"{key} {counts[key]}" for key in order if key in counts)
    cli_mod.console.print(summary)
    cli_mod.console.print(f"Wrote [bold]{briefing.path}[/]")
    if not apply:
        return
    if not collection.strip():
        cli_mod.console.print("[red]--apply needs -C so the note has a collection.[/]")
        raise typer.Exit(1)
    backend = cli_mod._connect(cfg)
    if not backend.supports_write():
        cli_mod._exit_env("A briefing note needs library write support.", cfg)
    try:
        col = backend.resolve_collection(collection.strip())
        key = backend.create_or_update_collection_note(
            col.key, briefing.html, ["paperful:frontier-briefing"]
        )
    except LibraryError as exc:
        cli_mod.console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    cli_mod._flush(backend)
    cli_mod.console.print(f"Note [bold]{key}[/] in {col.path or collection}")


def run_snowball_search(
    console: Console,
    queries: Any,
    year_from: Any,
    year_to: Any,
    depth: Any,
    max_candidates: Any,
    per_hop_limit: Any,
    per_hop_rank: Any,
    direction: Any,
    keyword_limit: Any,
    keyword_hop_limit: Any,
    keyword_min_score: Any,
    search_keywords: Any,
    cites_query: Any,
    study_design: Any,
    or_mode: Any,
    gate: Any,
    collection: Any,
    fetch_pdfs: Any,
    languages: Any,
    min_seed_citations: Any,
    note_provenance: Any,
    backends: Any,
    refine: Any,
    tag: Any,
    dedupe_scope: Any,
    dedupe_after: Any,
    author_site_preflight: Any,
    twenty_writeback: Any,
    stop_rule: Any,
    stop_eps: Any,
    stop_k: Any,
    stop_max_screened: Any,
    config: Any,
    fmt: Any,
) -> None:
    """Search OpenAlex and write a candidate queue. Creates items only with --gate auto."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    request = _snowball_request(
        cfg,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        year_from=year_from,
        year_to=year_to,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        search_keywords=search_keywords,
        cites_query=(cites_query or "").strip(),
        languages=languages,
        study_designs=study_design,
        min_seed_citations=min_seed_citations,
        note_provenance=note_provenance,
        backends=backends,
        refine=refine,
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
    )
    from .snowball.command import run_search

    try:
        query = _compose_keywords(queries, or_mode=or_mode)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    _run_snowball(
        cfg,
        lambda c: run_search(c, query, request, console=out),
        json_out=json_out,
        command="snowball search",
    )

def run_snowball_hybrid(
    console: Console,
    queries: Any,
    year_from: Any,
    year_to: Any,
    max_candidates: Any,
    per_hop_limit: Any,
    per_hop_rank: Any,
    hybrid_seeds: Any,
    direction: Any,
    keyword_limit: Any,
    keyword_hop_limit: Any,
    keyword_min_score: Any,
    search_keywords: Any,
    cites_query: Any,
    study_design: Any,
    or_mode: Any,
    gate: Any,
    collection: Any,
    fetch_pdfs: Any,
    languages: Any,
    min_seed_citations: Any,
    refine: Any,
    tag: Any,
    dedupe_scope: Any,
    dedupe_after: Any,
    author_site_preflight: Any,
    twenty_writeback: Any,
    stop_rule: Any,
    stop_eps: Any,
    stop_k: Any,
    stop_max_screened: Any,
    config: Any,
    fmt: Any,
) -> None:
    """Keyword hits, then one hop from the top DOIs. Not a separate harvest command."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    request = _snowball_request(
        cfg,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        depth=None,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        year_from=year_from,
        year_to=year_to,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        search_keywords=search_keywords,
        cites_query=(cites_query or "").strip(),
        languages=languages,
        study_designs=study_design,
        min_seed_citations=min_seed_citations,
        hybrid_seeds=hybrid_seeds,
        refine=refine,
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
    )
    from .snowball.command import run_hybrid

    try:
        query = _compose_keywords(queries, or_mode=or_mode)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    _run_snowball(
        cfg,
        lambda c: run_hybrid(c, query, request, console=out),
        json_out=json_out,
        command="snowball hybrid",
    )

def run_snowball_doi(
    console: Console,
    dois: Any,
    year_from: Any,
    year_to: Any,
    depth: Any,
    max_candidates: Any,
    per_hop_limit: Any,
    per_hop_rank: Any,
    direction: Any,
    keyword_limit: Any,
    keyword_hop_limit: Any,
    keyword_min_score: Any,
    cites_query: Any,
    study_design: Any,
    gate: Any,
    collection: Any,
    fetch_pdfs: Any,
    tag: Any,
    dedupe_scope: Any,
    dedupe_after: Any,
    author_site_preflight: Any,
    twenty_writeback: Any,
    stop_rule: Any,
    stop_eps: Any,
    stop_k: Any,
    stop_max_screened: Any,
    seeds_file: Any,
    config: Any,
    fmt: Any,
) -> None:
    """Bibliography and/or citing works of each DOI. Creates items only with --gate auto."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    request = _snowball_request(
        cfg,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        year_from=year_from,
        year_to=year_to,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        cites_query=(cites_query or "").strip(),
        study_designs=study_design,
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
    )
    from .snowball.command import SnowballError, run_doi

    try:
        seeds = _doi_seeds(dois, seeds_file)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    _run_snowball(
        cfg,
        lambda c: run_doi(c, seeds, request, console=out),
        json_out=json_out,
        command="snowball doi",
    )

def run_snowball_orcid(
    console: Console,
    orcids: Any,
    year_from: Any,
    year_to: Any,
    depth: Any,
    max_candidates: Any,
    per_hop_limit: Any,
    per_hop_rank: Any,
    direction: Any,
    keyword_limit: Any,
    keyword_hop_limit: Any,
    keyword_min_score: Any,
    cites_query: Any,
    study_design: Any,
    gate: Any,
    collection: Any,
    fetch_pdfs: Any,
    tag: Any,
    dedupe_scope: Any,
    dedupe_after: Any,
    author_site_preflight: Any,
    twenty_writeback: Any,
    stop_rule: Any,
    stop_eps: Any,
    stop_k: Any,
    stop_max_screened: Any,
    seeds_file: Any,
    config: Any,
    fmt: Any,
) -> None:
    """People's works (ORCID + OpenAlex), then references/citations those works expand to."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    request = _snowball_request(
        cfg,
        gate=gate,
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        year_from=year_from,
        year_to=year_to,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        cites_query=(cites_query or "").strip(),
        study_designs=study_design,
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
    )
    from .snowball.command import SnowballError, run_orcid

    try:
        seeds = _orcid_seeds(orcids, seeds_file)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    _run_snowball(
        cfg, lambda c: run_orcid(c, seeds, request, console=out), json_out=json_out, command="snowball orcid"
    )

def run_snowball_collection(
    console: Console,
    seed_collection: Any,
    year_from: Any,
    year_to: Any,
    depth: Any,
    max_candidates: Any,
    per_hop_limit: Any,
    per_hop_rank: Any,
    direction: Any,
    keyword_limit: Any,
    keyword_hop_limit: Any,
    keyword_min_score: Any,
    cites_query: Any,
    study_design: Any,
    gate: Any,
    collection: Any,
    fetch_pdfs: Any,
    tag: Any,
    dedupe_scope: Any,
    dedupe_after: Any,
    author_site_preflight: Any,
    twenty_writeback: Any,
    stop_rule: Any,
    stop_eps: Any,
    stop_k: Any,
    stop_max_screened: Any,
    config: Any,
    fmt: Any,
) -> None:
    """Expand DOIs already in a collection. Creates items only with --gate auto."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    target = collection or seed_collection
    request = _snowball_request(
        cfg,
        gate=gate,
        collection=target,
        fetch_pdfs=fetch_pdfs,
        depth=depth,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        per_hop_rank=per_hop_rank,
        year_from=year_from,
        year_to=year_to,
        direction=direction,
        keyword_limit=keyword_limit,
        keyword_hop_limit=keyword_hop_limit,
        keyword_min_score=keyword_min_score,
        cites_query=(cites_query or "").strip(),
        study_designs=study_design,
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
        author_site_preflight=author_site_preflight,
        twenty_writeback=twenty_writeback,
        stop_rule=stop_rule,
        stop_eps=stop_eps,
        stop_k=stop_k,
        stop_max_screened=stop_max_screened,
    )
    from .snowball.command import run_collection

    _run_snowball(
        cfg,
        lambda c: run_collection(c, seed_collection, request, console=out),
        json_out=json_out,
        command="snowball collection",
    )

def run_snowball_trends(
    console: Console,
    query: Any,
    profile: Any,
    year_from: Any,
    year_to: Any,
    config: Any,
    fmt: Any,
) -> None:
    """Publication-year counts for a query or saved search/hybrid profile. Read-only."""
    from . import cli_runtime as cli_mod

    from .snowball.trends_cmd import run_trends

    run_trends(
        console,
        query=query,
        profile=profile,
        year_from=year_from,
        year_to=year_to,
        config=config,
        fmt=fmt,
    )

def run_snowball_briefing(
    console: Console,
    run_id: Any,
    apply: Any,
    collection: Any,
    config: Any,
) -> None:
    """Write markdown for a saved snowball queue. Does not create items."""
    from . import cli_runtime as cli_mod

    from .snowball.briefing import write_run_briefing
    from .snowball.command import SnowballError

    cfg = cli_mod._cfg(config)
    try:
        briefing = write_run_briefing(cfg, run_id)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    _print_briefing(briefing, apply=apply, collection=collection, cfg=cfg)

def run_snowball_digest(
    console: Console,
    run_id: Any,
    apply: Any,
    collection: Any,
    config: Any,
) -> None:
    """Write a ranked frontier digest for a saved queue. Does not create items."""
    from . import cli_runtime as cli_mod

    from .snowball.command import SnowballError
    from .snowball.digest import write_run_digest

    cfg = cli_mod._cfg(config)
    try:
        digest = write_run_digest(cfg, run_id)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    _print_briefing(digest, apply=apply, collection=collection, cfg=cfg)

def run_snowball_resume(
    console: Console,
    run_id: Any,
    collection: Any,
    gate: Any,
    tag: Any,
    dedupe_scope: Any,
    dedupe_after: Any,
    config: Any,
    fmt: Any,
) -> None:
    """Continue OpenAlex work saved when the daily budget was spent. Same API key."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    request = _snowball_request(
        cfg,
        gate=gate,
        collection=collection,
        fetch_pdfs=None,
        depth=None,
        max_candidates=None,
        year_from=None,
        year_to=None,
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
    )
    from .snowball.command import run_resume

    _run_snowball(
        cfg,
        lambda c: run_resume(c, run_id, request, console=out),
        json_out=json_out,
        command="snowball resume",
    )

def run_snowball_continue(
    console: Console,
    run_id: Any,
    gate: Any,
    config: Any,
    fmt: Any,
) -> None:
    """Score Keep/Skip on the latest hop, then walk one more hop unless a stopping rule fires."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    from .snowball.command import run_continue

    _run_snowball(
        cfg,
        lambda c: run_continue(c, run_id, console=out, gate=gate),
        json_out=json_out,
        command="snowball continue",
    )

def run_snowball_apply(
    console: Console,
    run_id: Any,
    collection: Any,
    fetch_pdfs: Any,
    tag: Any,
    dedupe_scope: Any,
    dedupe_after: Any,
    config: Any,
    fmt: Any,
) -> None:
    """Create keep=true rows from a prior queue (approve-batch or edited dry-run)."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    request = _snowball_request(
        cfg,
        gate="auto",
        collection=collection,
        fetch_pdfs=fetch_pdfs,
        depth=None,
        max_candidates=None,
        year_from=None,
        year_to=None,
        tags=tag,
        dedupe_scope=dedupe_scope,
        dedupe_after=dedupe_after,
    )
    from .snowball.command import run_apply

    _run_snowball(
        cfg,
        lambda c: run_apply(c, run_id, request, console=out),
        json_out=json_out,
        command="snowball apply",
    )

def run_snowball_run(
    console: Console,
    profile: Any,
    direction: Any,
    keyword_limit: Any,
    keyword_hop_limit: Any,
    keyword_min_score: Any,
    cites_query: Any,
    tag: Any,
    dedupe_scope: Any,
    dedupe_after: Any,
    author_site_preflight: Any,
    twenty_writeback: Any,
    stop_rule: Any,
    stop_eps: Any,
    stop_k: Any,
    stop_max_screened: Any,
    config: Any,
    fmt: Any,
) -> None:
    """Run a saved snowball profile (keyword, DOI, ORCID, or collection)."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    if twenty_writeback is not None:
        cfg.twenty_writeback_listings = twenty_writeback
    json_out = cli_mod._agent_json(fmt)
    out = _snowball_console(json_out=json_out)
    from .snowball.command import (
        SnowballError,
        run_collection,
        run_doi,
        run_hybrid,
        run_orcid,
        run_search,
    )
    from .snowball.profile import composed_query_from_profile, load_profile, request_from_profile

    try:
        raw = load_profile(cfg, profile)
        request = request_from_profile(raw, cfg)
        if tag:
            from .identity import merge_tags

            request.tags = tuple(merge_tags(request.tags, tag))
        if direction.strip():
            request.direction = direction.strip()
        if keyword_limit is not None:
            request.keyword_limit = keyword_limit
        if keyword_hop_limit is not None:
            request.keyword_hop_limit = keyword_hop_limit
        if keyword_min_score is not None:
            request.keyword_min_score = keyword_min_score
        if cites_query is not None and cites_query.strip():
            request.cites_query = cites_query.strip()
        if dedupe_scope:
            request.dedupe_scope = dedupe_scope.strip()
        if dedupe_after:
            request.dedupe_after = dedupe_after.strip()
        if author_site_preflight is not None:
            request.author_site_preflight = author_site_preflight
        if stop_rule:
            request.stop_rule = stop_rule.strip()
        if stop_eps is not None:
            request.stop_eps = stop_eps
        if stop_k is not None:
            request.stop_k = stop_k
        if stop_max_screened is not None:
            request.stop_max_screened = stop_max_screened
        description = str(raw.get("description") or "").strip()
        if description and not json_out:
            console.print(description)
        mode = str(raw.get("mode") or "")
        if mode == "search":
            query = composed_query_from_profile(raw)

            def action(c):
                return run_search(c, query, request, console=out)
        elif mode == "hybrid":
            query = composed_query_from_profile(raw)

            def action(c):
                return run_hybrid(c, query, request, console=out)
        elif mode == "doi":
            dois = [str(item) for item in (raw.get("dois") or [])]

            def action(c):
                return run_doi(c, dois, request, console=out)
        elif mode == "orcid":
            from .snowball.profile import orcids_from_profile

            orcids = orcids_from_profile(raw)
            if not orcids:
                raise SnowballError(f"Profile {profile!r} needs orcid or orcids.")

            def action(c):
                return run_orcid(c, orcids, request, console=out)
        elif mode == "collection":
            seed = str(
                raw.get("seed_collection") or raw.get("collection") or ""
            ).strip()
            if not seed:
                raise SnowballError(f"Profile {profile!r} needs seed_collection.")
            if not request.collection.strip():
                request.collection = seed

            def action(c):
                return run_collection(c, seed, request, console=out)
        else:
            raise SnowballError(
                f"Profile {profile!r} mode must be search, hybrid, doi, orcid, or collection."
            )
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    _run_snowball(cfg, action, json_out=json_out, command="snowball run")

def run_snowball_profile_save(
    console: Console,
    name: Any,
    query: Any,
    doi: Any,
    orcid: Any,
    seed_collection: Any,
    description: Any,
    gate: Any,
    collection: Any,
    fetch_pdfs: Any,
    depth: Any,
    max_candidates: Any,
    per_hop_limit: Any,
    per_hop_rank: Any,
    direction: Any,
    keyword_limit: Any,
    keyword_hop_limit: Any,
    keyword_min_score: Any,
    search_keywords: Any,
    cites_query: Any,
    study_design: Any,
    year_from: Any,
    year_to: Any,
    dedupe_scope: Any,
    dedupe_after: Any,
    oa_only: Any,
    or_mode: Any,
    hybrid: Any,
    languages: Any,
    min_seed_citations: Any,
    note_provenance: Any,
    backends: Any,
    hybrid_seeds: Any,
    refine: Any,
    author_site_preflight: Any,
    stop_rule: Any,
    stop_eps: Any,
    stop_k: Any,
    stop_max_screened: Any,
    seeds_file: Any,
    force: Any,
    config: Any,
) -> None:
    """Write seeds and knobs. Refuses API keys. A writing gate needs --force."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    from .snowball.command import SnowballError
    from .snowball.profile import save_profile as save_snowball_profile

    queries = [part.strip() for part in (query or []) if part and part.strip()]
    from .snowball.command import SnowballError as _SB
    from .snowball.seeds import parse_seed_lines, read_seeds_text

    file_tokens: list[str] = []
    if seeds_file:
        try:
            file_tokens = parse_seed_lines(read_seeds_text(str(seeds_file)))
        except _SB as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(exc.code) from exc
        if doi:
            doi = list(doi) + file_tokens
        elif orcid:
            orcid = list(orcid) + file_tokens
        else:
            console.print("[red]--seeds-file needs --doi or --orcid.[/]")
            raise typer.Exit(2)
    seeds = [
        bool(queries),
        bool(doi),
        bool(orcid),
        bool(seed_collection.strip()),
    ]
    if sum(seeds) != 1:
        console.print(
            "[red]Pass exactly one of --query, --doi, --orcid, or --seed-collection.[/]"
        )
        raise typer.Exit(2)
    body: dict[str, Any] = {"gate": gate}
    if queries and hybrid:
        body["mode"] = "hybrid"
        _profile_queries(body, queries, or_mode=or_mode)
    elif queries:
        body["mode"] = "search"
        _profile_queries(body, queries, or_mode=or_mode)
    elif doi:
        body["mode"] = "doi"
        body["dois"] = list(doi)
    elif orcid:
        body["mode"] = "orcid"
        body["orcids"] = list(orcid)
    else:
        body["mode"] = "collection"
        body["seed_collection"] = seed_collection.strip()
    if description.strip():
        body["description"] = description.strip()
    if collection.strip():
        body["target_collection"] = collection.strip()
    if fetch_pdfs.strip():
        from .config import parse_fetch_pdfs

        try:
            body["fetch_pdfs"] = parse_fetch_pdfs(fetch_pdfs)
        except ValueError as exc:
            raise SnowballError(str(exc)) from exc
    if depth is not None:
        body["depth"] = depth
    if max_candidates is not None:
        from .config import parse_cap

        try:
            body["max_candidates"] = parse_cap(max_candidates)
        except ValueError as exc:
            raise SnowballError(str(exc)) from exc
    if per_hop_limit is not None:
        from .config import parse_cap

        try:
            body["per_hop_limit"] = parse_cap(per_hop_limit)
        except ValueError as exc:
            raise SnowballError(str(exc)) from exc
    if per_hop_rank:
        from .config import parse_per_hop_rank

        try:
            body["per_hop_rank"] = parse_per_hop_rank(per_hop_rank)
        except ValueError as exc:
            raise SnowballError(str(exc)) from exc
    if direction.strip():
        body["direction"] = direction.strip()
    if keyword_limit is not None:
        from .snowball.expand import parse_keyword_limit

        try:
            body["keyword_limit"] = parse_keyword_limit(keyword_limit)
        except ValueError as exc:
            raise SnowballError(str(exc)) from exc
    if keyword_hop_limit is not None:
        from .snowball.expand import parse_keyword_hop_limit

        try:
            body["keyword_hop_limit"] = parse_keyword_hop_limit(keyword_hop_limit)
        except ValueError as exc:
            raise SnowballError(str(exc)) from exc
    if keyword_min_score is not None:
        body["keyword_min_score"] = keyword_min_score
    if search_keywords is not None:
        body["search_keywords"] = search_keywords
    if cites_query and cites_query.strip():
        body["cites_query"] = cites_query.strip()
    if study_design:
        from .snowball.expand import parse_study_designs

        try:
            body["study_designs"] = list(parse_study_designs(study_design))
        except ValueError as exc:
            raise SnowballError(str(exc)) from exc
    if year_from is not None:
        body["year_from"] = year_from
    if year_to is not None:
        body["year_to"] = year_to
    if dedupe_scope.strip():
        body["dedupe_scope"] = dedupe_scope.strip()
    if oa_only:
        body["oa_only"] = True
    if languages.strip():
        body["languages"] = _csv(languages)
    if min_seed_citations is not None:
        body["min_seed_citations"] = min_seed_citations
    if note_provenance is not None:
        body["note_provenance"] = note_provenance
    if backends.strip():
        body["backends"] = _csv(backends)
    if hybrid_seeds is not None:
        body["hybrid_seeds"] = hybrid_seeds
    if refine:
        body["refine"] = True
    if stop_rule.strip():
        body["stop_rule"] = stop_rule.strip()
    if stop_eps is not None:
        body["stop_eps"] = stop_eps
    if stop_k is not None:
        body["stop_k"] = stop_k
    if stop_max_screened is not None:
        body["stop_max_screened"] = stop_max_screened
    try:
        path = save_snowball_profile(cfg, name, body, force=force)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    console.print(f"Wrote [bold]{path}[/]")

def run_snowball_packs_promote(
    console: Console,
    slug: Any,
    config: Any,
) -> None:
    """Copy a proposed author pack to the promoted file used by the author_site lane."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    from .snowball.command import SnowballError
    from .snowball.preflight import promote_pack

    try:
        path = promote_pack(cfg, slug)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    console.print(f"Promoted [bold]{path}[/]")

def run_snowball_watch_save(
    console: Console,
    name: Any,
    profile: Any,
    config: Any,
) -> None:
    """Point a watch at a saved snowball profile. No API keys."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    from .snowball.command import SnowballError
    from .snowball.watch import save_watch

    try:
        path = save_watch(cfg, name, profile)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    console.print(f"Wrote [bold]{path}[/] · profile {profile}")

def run_snowball_watch_run(
    console: Console,
    name: Any,
    dedupe_scope: Any,
    digest: Any,
    config: Any,
) -> None:
    """Baseline on first run; later runs write only unseen new works to the inbox."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    from .snowball.digest import write_watch_digest
    from .snowball.watch import run_watch

    def _run(c: Config):
        result = run_watch(c, name, console=console, dedupe_scope=dedupe_scope)
        if digest and not result.exit_code:
            written = write_watch_digest(c, name)
            _print_briefing(written, apply=False, collection="", cfg=c)
        return result

    _run_snowball(cfg, _run)

def run_snowball_watch_rebaseline(
    console: Console,
    name: Any,
    all_watches: Any,
    apply: Any,
    force: Any,
    config: Any,
) -> None:
    """Re-baseline keyword watches once after OpenAlex's Oct 2026 topic change.

    The next `watch run` then absorbs reassigned works as seen instead of
    proposing them as new. Does not touch the inbox or open the library.
    """
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    from .snowball.command import SnowballError
    from .snowball.watch import list_watch_names, rebaseline_watch

    if bool(name) == all_watches:
        console.print("[red]Pass a watch name or --all (not both).[/]")
        raise typer.Exit(1)
    names = list_watch_names(cfg) if all_watches else [name]
    try:
        for n in names:
            res = rebaseline_watch(cfg, n, apply=apply, force=force)
            verb = "reset" if res["applied"] else ("would reset" if res["action"] == "rebaseline" else "skip")
            console.print(f"{n}: {verb} · {res['reason']}")
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    if not apply and any(True for _ in names):
        console.print("[dim]Dry run. Pass --apply to write.[/]")

def run_snowball_watch_show(
    console: Console,
    name: Any,
    config: Any,
) -> None:
    """Inbox count and latest run id. Does not open the library."""
    from . import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    from .snowball.command import SnowballError
    from .snowball.watch import show_watch

    try:
        show_watch(cfg, name, console=console)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc

def run_snowball_watch_briefing(
    console: Console,
    name: Any,
    apply: Any,
    collection: Any,
    config: Any,
) -> None:
    """Write markdown for a watch inbox. Does not create items."""
    from . import cli_runtime as cli_mod

    from .snowball.briefing import write_watch_briefing
    from .snowball.command import SnowballError

    cfg = cli_mod._cfg(config)
    try:
        briefing = write_watch_briefing(cfg, name)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    _print_briefing(briefing, apply=apply, collection=collection, cfg=cfg)

def run_snowball_watch_digest(
    console: Console,
    name: Any,
    apply: Any,
    collection: Any,
    config: Any,
) -> None:
    """Write a ranked frontier digest for a watch. Does not create items."""
    from . import cli_runtime as cli_mod

    from .snowball.command import SnowballError
    from .snowball.digest import write_watch_digest

    cfg = cli_mod._cfg(config)
    try:
        digest = write_watch_digest(cfg, name)
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    _print_briefing(digest, apply=apply, collection=collection, cfg=cfg)

def run_snowball_watch_apply(
    console: Console,
    name: Any,
    collection: Any,
    apply: Any,
    config: Any,
) -> None:
    """Create parents from watches/<name>/inbox.jsonl. PDFs stay paperful run."""
    from . import cli_runtime as cli_mod

    from .snowball.command import SnowballError
    from .snowball.watch import apply_watch

    cfg = cli_mod._cfg(config)
    backend = None
    if apply:
        cli_mod._require_manager(cfg)
        backend = cli_mod._connect(cfg)
        if not backend.supports_write():
            cli_mod._exit_env(cli_mod._no_write(backend), cfg)

    def _go():
        return apply_watch(
            cfg,
            name,
            collection,
            console=console,
            apply=apply,
            backend=backend,
        )

    try:
        result = _go()
    except SnowballError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    if result.failed and result.created:
        raise typer.Exit(3)

