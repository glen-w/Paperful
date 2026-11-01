"""``paperful stuff`` implementation (CLI parses flags only)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .runreport import write_command_report


def run_stuff(
    console: Console,
    *,
    item: list[str],
    file_path: Path | None,
    collection: list[str],
    library: bool | None,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    k: int | None,
    lane: str | None,
    dry_run: bool,
    config: Path | None,
    fmt: str,
) -> None:
    from . import cli_runtime as cli_mod
    from .agent_json import envelope
    from .critique_extract import SUPPORTED, ExtractError, extract_path
    from .llm import LLMClientError
    from .lint import resolve_pdf_path
    from .rag.retrieve import scope_keys
    from .store import Manifest
    from .stuff import (
        HONESTY_BANNER,
        collect_pack,
        pack_payload,
        resolve_k,
        resolve_lane,
        stuff_id,
        write_pack,
    )

    cfg = cli_mod._cfg(config)
    json_out = cli_mod._agent_json(fmt)
    item_keys = [tok.strip() for tok in item if tok and str(tok).strip()]
    if bool(item_keys) == bool(file_path):
        console.print("[red]Pass exactly one of --item KEY or --file PATH.[/]")
        raise typer.Exit(1)
    if file_path is not None and file_path.suffix.lower() not in SUPPORTED:
        console.print(
            "[red]Unsupported format. Save as pdf, txt, md, html, rtf, docx, "
            "odt, pptx (legacy .doc needs antiword, catdoc, or LibreOffice).[/]"
        )
        raise typer.Exit(1)
    try:
        lane_id = resolve_lane(cfg, lane)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    per_k = resolve_k(cfg, k)

    cli_mod._rag_require(cfg)
    types = cli_mod._resolve_types(item_type)
    embedder = cli_mod._rag_embedder(cfg)
    index, ledger = cli_mod._rag_open(cfg)
    if int(index.count() or 0) <= 0:
        console.print("[red]RAG index is empty — paperful rag ingest[/]")
        raise typer.Exit(1)

    target = None
    src: Path | None = None
    kind = "file"
    item_key = ""
    title = ""
    if item_keys:
        kind = "item"
        cli_mod._require_manager(cfg)
        backend = cli_mod._connect(cfg, quiet=json_out)
        loaded = cli_mod._load_scope(
            backend,
            json_out=json_out,
            collection=collection,
            library=bool(library),
            year_from=year_from,
            year_to=year_to,
            item_type=item_type,
            item_keys=item_keys,
        )
        items = loaded.items
        if not items:
            console.print("[red]Item not in the mirror / scope.[/]")
            raise typer.Exit(1)
        target = items[0]
        item_key = target.key
        title = target.title or target.key
        manifest = Manifest(cfg.manifest_path)
        src = resolve_pdf_path(cfg, target, manifest)
        if src is None:
            console.print(f"[red]No PDF on disk for {item_key}.[/]")
            raise typer.Exit(1)
    else:
        assert file_path is not None
        src = file_path
        title = file_path.name

    collections = [c.strip() for c in collection if c and str(c).strip()]
    keys = scope_keys(
        ledger,
        collections=None if library else collections,
        year_from=year_from,
        year_to=year_to,
        item_types=types,
    )
    scope = (
        "library" if library else (", ".join(collections) if collections else "index")
    )
    cid = stuff_id(
        kind=kind,
        item_key=item_key,
        original_name=file_path.name if file_path is not None else "",
    )

    started = time.time()
    t0 = time.perf_counter()

    def _on_status(msg: str) -> None:
        elapsed = time.perf_counter() - t0
        console.print(f"[dim]{elapsed:5.0f}s[/] {escape(msg)}")

    try:
        with cli_mod._spinner("Stuff", json_out=json_out) as spin:

            def on_status(msg: str) -> None:
                spin(msg)
                if not json_out:
                    _on_status(msg)

            on_status(f"Extracting {src.name}…")
            doc = extract_path(src)
            on_status(
                f"Extracted {len((doc.text or '').split()):,} words "
                f"({doc.format or 'unknown'})"
            )
            from .rag.retrieve import search as rag_search

            def search_fn(query: str, *, k: int, keys: set[str] | None) -> list[Any]:
                return rag_search(
                    cfg,
                    query,
                    k=k,
                    keys=keys,
                    embedder=embedder,
                    index=index,
                    ledger=ledger,
                )

            rows, skips, outline = collect_pack(
                cfg,
                doc,
                lane=lane_id,
                k=per_k,
                keys=keys,
                exclude_key=item_key,
                search_fn=search_fn,
                on_status=on_status,
            )
    except ExtractError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    except LLMClientError as exc:
        console.print(str(exc), markup=False, style="red")
        raise typer.Exit(1) from exc

    inp = {
        "kind": kind,
        "item_key": item_key,
        "path": str(src),
        "title": title,
        "format": doc.format,
    }
    payload = pack_payload(
        cid=cid,
        scope=scope,
        lane=lane_id,
        k=per_k,
        inp=inp,
        rows=rows,
        skips=skips,
        ledger=outline,
    )
    folder: Path | None = None
    if not dry_run:
        folder = write_pack(cfg, payload)
        payload["pack_dir"] = str(folder)
    counts = payload.get("counts") or {}
    write_command_report(
        cfg,
        command="stuff",
        scope=scope,
        summary={
            "units": counts.get("units", 0),
            "hits": counts.get("hits", 0),
            "skips": counts.get("skips", 0),
            "unique_sources": counts.get("unique_sources", 0),
            "pack_dir": str(folder or ""),
        },
        items=[
            {
                "itemKey": item_key or cid,
                "title": title,
                "status": lane_id,
                "reason": f"{len(row.hits)} hit(s)",
            }
            for row in rows[:200]
        ],
        flags={
            "dry_run": dry_run,
            "lane": lane_id,
            "k": per_k,
        },
        started=started,
    )
    envelope_payload = envelope(
        command="stuff",
        summary={
            "units": counts.get("units", 0),
            "hits": counts.get("hits", 0),
            "skips": counts.get("skips", 0),
            "unique_sources": counts.get("unique_sources", 0),
            "pack_dir": str(folder or ""),
            "stuff_id": cid,
            "lane": lane_id,
        },
        items=[
            {
                "quote": row.quote[:200],
                "loc": row.loc,
                "heading": row.heading,
                "hits": [
                    {"item_key": hit.item_key, "title": hit.title, "pages": hit.pages}
                    for hit in row.hits
                ],
            }
            for row in rows[:50]
        ],
        paths={"pack": str(folder) if folder is not None else ""},
        flags={"dry_run": dry_run, "read_only": True, "lane": lane_id, "k": per_k},
    )

    def _human() -> None:
        table = Table(title="stuff")
        table.add_column("Unit")
        table.add_column("Loc")
        table.add_column("Hits")
        shown = rows[:20]
        for row in shown:
            label = row.heading or row.quote
            clip = label if len(label) <= 60 else label[:59] + "…"
            hit_s = ", ".join(h.item_key for h in row.hits[:3]) or "—"
            table.add_row(clip, row.loc, hit_s)
        console.print(table)
        console.print(
            f"units {counts.get('units', 0)} · hits {counts.get('hits', 0)} · "
            f"unique {counts.get('unique_sources', 0)} · skips {counts.get('skips', 0)}"
        )
        console.print(HONESTY_BANNER)
        if folder is not None:
            console.print(f"Pack: {folder}")
        else:
            console.print("[dim]dry-run — pack not written[/]")

    cli_mod._emit_agent(envelope_payload, json_out=json_out, human=_human)
