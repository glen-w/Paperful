"""``paperful precedent`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from .runreport import write_command_report


def _seed_doi_from_items(items: list[Any], explicit: str) -> str:
    from .resolve import normalize_doi

    if explicit.strip():
        return normalize_doi(explicit) or explicit.strip()
    for item in items:
        doi = normalize_doi(getattr(item, "doi", None) or "") or ""
        if doi:
            return doi
    return ""


def run_precedent(
    console: Console,
    *,
    query: str,
    collection: list[str],
    library: bool | None,
    year_from: int | None,
    year_to: int | None,
    item: list[str],
    seed_doi: str,
    held_k: int | None,
    public_k: int | None,
    dedupe_scope: str,
    profile: str | None,
    run_config: Path | None,
    config: Path | None,
    fmt: str,
) -> None:
    """Held passages plus OpenAlex works for a phrase. Always dry-run."""
    from . import cli_runtime as cli_mod

    from .identity import LibraryFingerprint
    from .precedent import HONESTY_BANNER, collect_pack, write_pack

    phrase = (query or "").strip()
    if not phrase:
        console.print("[red]Pass a methods or hypothesis phrase.[/]")
        raise typer.Exit(1)
    if cli_mod._scope_unset(collection, library, profile, run_config) and not item:
        cli_mod._refuse_missing_scope()
    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    bound = cli_mod._bind_run(
        cfg,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
    )
    collection, library, year_from, year_to, _item_type = cli_mod._take_scope(bound)
    backend = cli_mod._connect(cfg, quiet=json_out)
    loaded = cli_mod._load_scope(
        backend,
        json_out=json_out,
        collection=collection,
        library=bool(library) or not collection,
        year_from=year_from,
        year_to=year_to,
    )
    items = loaded.items
    scope = loaded.label
    if item:
        want = set(item)
        items = [it for it in items if it.key in want]
        if not items:
            console.print("[red]No matching --item keys in scope.[/]")
            raise typer.Exit(1)
        scope = f"{len(items)} item(s)"
    fingerprint = LibraryFingerprint.from_items(
        list(backend.items_in_scope(None))
        if hasattr(backend, "items_in_scope")
        else items,
        scope=dedupe_scope,
        collection=collection[0] if collection else "",
    )
    seed = _seed_doi_from_items(items if item else [], seed_doi)
    rows, findings, counts, partial = collect_pack(
        cfg,
        phrase,
        fingerprint,
        collections=None if library else collection,
        item_keys=item or None,
        year_from=year_from,
        year_to=year_to,
        held_k=held_k,
        public_k=public_k,
        seed_doi=seed,
    )
    folder = write_pack(cfg.state_dir, scope, phrase, rows, findings, counts)
    write_command_report(
        cfg,
        command="precedent",
        scope=scope,
        summary={
            "held": counts["held"],
            "public_metadata_only": counts["public_metadata_only"],
            "openalex_fetched": counts["openalex_fetched"],
            "write_api": None,
        },
        items=[
            {
                "doi": r.doi,
                "title": r.title,
                "evidence": r.evidence,
                "suggested_action": r.suggested_action,
            }
            for r in rows[:200]
        ],
        flags={"dry_run": True, "dedupe_scope": dedupe_scope, "partial": partial},
        extra_paths={"pack": str(folder)},
        bound=bound,
    )
    from .agent_ops import precedent_envelope

    payload = precedent_envelope(
        rows=rows,
        findings=findings,
        counts=counts,
        folder=folder,
        flags={"dedupe_scope": dedupe_scope},
        partial=partial,
    )

    def _human() -> None:
        table = Table(title="precedent")
        table.add_column("Evidence")
        table.add_column("DOI")
        table.add_column("Title")
        table.add_column("Action")
        public = [r for r in rows if r.evidence == "public-metadata-only"]
        held = [r for r in rows if r.evidence == "held"]
        shown = public[:20] + held[:10]
        for row in shown:
            table.add_row(
                row.evidence,
                row.doi or "",
                (row.title or "")[:50],
                row.suggested_action,
            )
        console.print(table)
        extra = ""
        if partial:
            extra = " · budget partial"
        console.print(
            f"held {counts['held']} · public-metadata-only "
            f"{counts['public_metadata_only']}{extra}"
        )
        if findings:
            console.print("Findings: " + ", ".join(findings))
        console.print(HONESTY_BANNER)
        console.print(f"Pack: {folder}")
        console.print(
            f"Next: paperful ingest-dois --from-file {folder / 'dois.txt'} "
            "-C <collection> --dry-run"
        )

    cli_mod._emit_agent(payload, json_out=json_out, human=_human)
