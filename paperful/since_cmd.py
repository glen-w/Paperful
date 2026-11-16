"""``paperful since`` implementation (CLI parses flags only)."""

from __future__ import annotations

import time
from collections import Counter
from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape

from .runreport import write_command_report


def _url_rows(cfg, backend, items, urls_before, seen, url_rows) -> list[dict]:
    """Re-probe URLs the last ``urls`` report saw, with that command's client."""
    from .http import client as http_client
    from .urls import probe_target, targets_for_item

    prior, compared_to = urls_before
    known = {key for key, _url in prior}
    targets = []
    for item in items:
        if item.key not in known:
            continue
        children = backend.children(item.key) if hasattr(backend, "children") else []
        targets += targets_for_item(item, children)
    with http_client(
        follow_redirects=True, timeout=8.0, retries=0, guard=True
    ) as client:
        return url_rows(
            targets,
            {item.key: item.title for item in items},
            prior,
            lambda target: probe_target(client, target, playbooks=cfg.grey_playbooks),
            seen,
            compared_to,
        )


def run_since(
    console: Console,
    *,
    collection: list[str],
    library: bool | None,
    since: str,
    limit: int | None,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    """Diff the mirror against the last run report. Always dry-run."""

    from . import cli_runtime as cli_mod
    from . import keepup, versions
    from .agent_ops import since_envelope
    from .handoff_rank import cite_index
    from .pipeline import make_client
    from .routing import sources_for_item
    from . import screen
    from .since import (
        DEAD_URL_CODES,
        NOTHING_CHANGED,
        STATUS_CODES,
        STATUS_FRESH_S,
        find_baseline,
        healed_rows,
        in_parallel,
        prior_holdings,
        prior_urls,
        snapshot_rows,
        url_rows,
        version_rows,
        keepup_rows,
        probe_item,
        scope_matcher,
        status_rows,
        write_pack,
    )
    from .sources import Candidate, Context
    from .zot import Item

    before: date | None = None
    if since.strip():
        try:
            before = date.fromisoformat(since.strip())
        except ValueError:
            console.print("[red]--since takes a date as YYYY-MM-DD.[/]")
            raise typer.Exit(1) from None
    if cli_mod._scope_unset(collection, library, profile, run_config):
        cli_mod._refuse_missing_scope()
    started = time.time()
    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    bound = cli_mod._bind_run(
        cfg,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
    )
    collection, library, *_ = cli_mod._take_scope(bound)
    backend = cli_mod._connect(cfg, quiet=json_out)
    keys, scope = cli_mod._scope_keys(backend, collection, bool(library))
    items = backend.items_in_scope(keys)
    sources = list(bound.sources or cfg.sources or [])

    # The label is the text typed after -C; compare saved reports by collection.
    same = scope_matcher(scope)
    if keys is not None:
        same = scope_matcher(
            scope,
            frozenset(backend.resolve_collection(spec).key for spec in collection),
            lambda spec: backend.resolve_collection(spec).key,
        )

    notes: list[str] = []
    baseline = find_baseline(cfg.state_dir, same, before=before)
    seen, vs = prior_holdings(cfg.state_dir, same)
    client = make_client(cfg)
    try:
        with cli_mod._spinner("Checking retraction status…", json_out=json_out) as say:
            ctx = Context(config=cfg, client=client)

            lane_errors: Counter[str] = Counter()
            status_failed: list[str] = []

            def probe(item: Item, skip: frozenset[str]) -> Candidate | None:
                lanes = sources_for_item(item, cfg, sources)
                return probe_item(
                    item, ctx, [n for n in lanes if n not in skip], lane_errors
                )

            def status(doi: str) -> list[str]:
                codes, ok = screen.doi_status(client, cfg, doi, max_age=STATUS_FRESH_S)
                if not ok:
                    status_failed.append(doi)
                return codes

            holdings = status_rows(
                items,
                status,
                seen,
                vs.get("screen", ""),
                workers=cfg.concurrency_oa,
                on_progress=lambda done, total: say(
                    f"Checking retraction status… {done}/{total}"
                ),
            )
            if status_failed:
                notes.append(
                    f"Retraction status could not be checked for {len(status_failed)} "
                    "DOI(s) (lookup failed): the last known status was used."
                )
            say("Checking versions…")
            resolve = versions.resolver_for(client, cfg.email)
            version_failed: list[str] = []

            def link(doi: str):
                try:
                    return resolve(doi)
                except Exception:  # one bad DOI must not end the report
                    version_failed.append(doi)
                    return None

            dois = list(
                dict.fromkeys(d for item in items for d in versions._item_dois(item))
            )
            links = dict(zip(dois, in_parallel(link, dois, cfg.concurrency_oa)))
            proposals = versions.classify_versions(items, links.get)
            if version_failed:
                notes.append(
                    f"Versions could not be checked for {len(version_failed)} DOI(s) "
                    "(lookup failed)."
                )
            holdings += version_rows(proposals, seen, vs.get("versions", ""))
            urls_before = prior_urls(cfg.state_dir, same)
            if urls_before is None:
                notes.append("No prior URL report: URL health not compared.")
            else:
                say("Checking URLs…")
                holdings += _url_rows(cfg, backend, items, urls_before, seen, url_rows)
            say("Probing snapshot PDFs…")
            holdings += snapshot_rows(
                items, probe, seen, limit=limit, workers=cfg.concurrency_oa
            )
            applied: set[str] = set()
            for job in keepup.list_jobs(cfg):
                applied |= keepup.load_applied(cfg, job)
            holdings += keepup_rows(items, applied, seen)
            healed: list[dict] = []
            counts = {"healed_candidates": 0, "probed": 0}
            say("Probing earlier misses…")
            if baseline is None:
                when = f" on or before {before.isoformat()}" if before else ""
                notes.append(
                    f"No run report for this scope{when}: healed misses not compared."
                )
            else:
                healed, counts = healed_rows(
                    baseline,
                    items,
                    probe,
                    cite_index(cfg.state_dir),
                    limit=limit,
                    workers=cfg.concurrency_oa,
                )
                if counts["probed"] < counts["healed_candidates"]:
                    notes.append(
                        f"Probed {counts['probed']} of {counts['healed_candidates']} "
                        "earlier misses (--limit)."
                    )
            if lane_errors:
                lanes = ", ".join(f"{n} {c}" for n, c in sorted(lane_errors.items()))
                notes.append(
                    f"Lanes that errored while probing ({lanes}): "
                    "a copy they hold may be missing from this report."
                )
    finally:
        client.close()

    folder = write_pack(cfg.state_dir, scope, baseline, holdings, healed, counts, notes)
    write_command_report(
        cfg,
        command="since",
        scope=scope,
        summary={"holdings": len(holdings), "healed": len(healed), **counts},
        items=[*holdings, *healed][:200],
        flags={"dry_run": True, "since": since.strip(), "limit": limit},
        started=started,
        extra_paths={"pack": str(folder)},
        bound=bound,
    )
    payload = since_envelope(
        holdings=holdings, healed=healed, counts=counts, notes=notes, folder=folder
    )

    def _row(row: dict, tail: str) -> None:
        bad = row["kind"] in STATUS_CODES or row["kind"] in DEAD_URL_CODES
        title = row["title"] if len(row["title"]) <= 90 else row["title"][:89] + "…"
        console.print(
            f"  [{'red' if bad else 'cyan'}]{row['kind']}[/] {row['itemKey']} "
            f"{escape(title)}"
        )
        console.print(
            f"    [dim]{escape(tail)} · {row['verb']}, vs {escape(row['compared_to'])}"
            f" · next: {row['suggested_action']}[/]"
        )

    def _human() -> None:
        if baseline is not None:
            more = (
                f", with {baseline.reports - 1} older run(s) for items it skipped"
                if baseline.reports > 1
                else ""
            )
            console.print(
                f"Compared to run {baseline.finished_at[:10]} "
                f"(witness {baseline.witness_id or 'none'}){more}."
            )
        for note in notes:
            console.print(f"[yellow]{escape(note)}[/]")
        if not holdings and not healed:
            console.print(NOTHING_CHANGED)
        if holdings:
            console.print(f"\n[bold]Holdings that changed meaning[/] ({len(holdings)})")
            for row in holdings:
                _row(row, row.get("doi") or row.get("url") or "no DOI")
        if healed:
            console.print(f"\n[bold]Misses that healed[/] ({len(healed)})")
            for row in healed:
                _row(row, f"was {row['was']}, now {row['lane']}: {row['url']}")
        console.print(f"\nPack: {folder}")
        if healed:
            console.print("Next: open Wanted, or paperful run for this scope.")

    cli_mod._emit_agent(payload, json_out=json_out, human=_human)
