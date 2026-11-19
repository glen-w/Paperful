"""``paperful ask`` implementation (CLI parses flags only)."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from .config import Config, wants_zotero
from .runreport import write_command_report


def run_ask(
    console: Console,
    cfg: Config,
    *,
    question: str | None,
    top_k: int | None,
    item: list[str],
    collection: list[str],
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    from_file: Path | None,
    focus: str | None,
    prompt: Path | None,
    force: bool,
    apply: bool,
    to_dest: str | None,
    no_stream: bool,
    show_context: bool,
    thread: str | None,
    profile: str | None,
    run_config: Path | None,
    json_out: bool,
    ask_mode: str | None = None,
    claim_check: bool = False,
    file_path: Path | None = None,
) -> None:
    from . import cli_runtime as cli_mod
    from .agent_json import batch_exit
    from .agent_ops import ask_envelope
    from .llm import LLMClientError, get_client, llm_egress_is_remote
    from .llm.preflight import validate_llm_for_ask
    from .llm.validate import LlmConfigError
    from .library import get_backend
    from .rag.mode import resolve_ask_mode
    from .rag.prompt import parse_focus
    from .rag.retrieve import scope_keys

    batch_mode = from_file is not None
    if claim_check:
        run_claim_check(
            console,
            cfg,
            item=item,
            file_path=file_path,
            collection=collection,
            year_from=year_from,
            year_to=year_to,
            item_type=item_type,
            top_k=top_k,
            question=question,
            from_file=from_file,
            apply=apply,
            thread=thread,
            json_out=json_out,
        )
        return
    if file_path is not None:
        console.print("[red]ask --file is only valid with --claim-check.[/]")
        raise typer.Exit(1)
    if json_out and question is None and not batch_mode:
        console.print("[red]ask --format json needs a question.[/]")
        raise typer.Exit(1)
    if batch_mode and thread is not None:
        console.print("[red]ask --from-file cannot use --thread.[/]")
        raise typer.Exit(1)
    if json_out:
        no_stream = True
    bound = cli_mod._bind_run(
        cfg,
        profile=profile,
        run_config=run_config,
        collection=collection,
        library=None,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
        focus=focus,
    )
    if bound.collections:
        collection = list(bound.collections)
    if bound.year_from is not None:
        year_from = bound.year_from
    if bound.year_to is not None:
        year_to = bound.year_to
    if bound.types:
        item_type = list(bound.types)
    cli_mod._rag_require(cfg)
    try:
        validate_llm_for_ask(cfg)
    except LlmConfigError as exc:
        console.print(str(exc), markup=False, style="red")
        raise typer.Exit(1) from exc
    try:
        focus_name = parse_focus(
            focus if focus is not None else (bound.focus or cfg.rag_focus)
        )
    except ValueError as exc:
        console.print(str(exc), markup=False, style="red")
        raise typer.Exit(1) from exc
    try:
        mode = resolve_ask_mode(cfg, ask_mode)
    except ValueError as exc:
        console.print(str(exc), markup=False, style="red")
        raise typer.Exit(1) from exc
    prompt_path = (
        str(prompt.expanduser().resolve())
        if prompt is not None
        else (cfg.rag_prompt or None)
    )
    types = cli_mod._resolve_types(item_type)
    embedder = cli_mod._rag_embedder(cfg)
    if llm_egress_is_remote(cfg) and not json_out:
        console.print(
            "[yellow]Remote LLM — excerpts from your PDFs leave this machine.[/]"
        )
    index, ledger = cli_mod._rag_open(cfg)
    keys = scope_keys(
        ledger,
        collections=collection,
        item_keys=item,
        year_from=year_from,
        year_to=year_to,
        item_types=types,
    )
    client = get_client(cfg)
    started = time.time()

    if batch_mode:
        from dataclasses import asdict as _asdict

        from .rag.batch import read_questions, run_batch, write_pack
        from .snowball.command import SnowballError

        try:
            questions = read_questions(str(from_file))
        except SnowballError as exc:
            console.print(str(exc), markup=False, style="red")
            raise typer.Exit(1) from exc
        if not questions:
            console.print("[red]No questions in --from-file.[/]")
            raise typer.Exit(1)
        dest = (to_dest if to_dest is not None else cfg.rag_dest) or "disk"
        if apply and dest == "disk":
            console.print(
                "[red]--apply writes a Zotero note; it conflicts with --to disk.[/]"
            )
            raise typer.Exit(1)
        if apply and wants_zotero(dest) and len(collection) != 1:
            console.print(
                "[red]ask --apply to Zotero needs exactly one -C collection.[/]"
            )
            raise typer.Exit(1)
        pack = run_batch(
            cfg,
            questions,
            keys=keys,
            focus=focus_name,
            prompt_path=prompt_path,
            k=top_k,
            force=force,
            ask_mode=mode,
            scope={
                "collections": list(collection),
                "item": list(item),
                "year_from": year_from,
                "year_to": year_to,
            },
            client=client,
            embedder=embedder,
            index=index,
            ledger=ledger,
        )
        folder = write_pack(cfg, pack)
        if apply and wants_zotero(dest):
            from .notehtml import wrap
            from .summarize import to_note_html

            backend = get_backend(cfg)
            body = (folder / "answers.md").read_text(encoding="utf-8")
            html = wrap(
                to_note_html(body),
                note_type="review",
                verb="ask",
                model=pack.model,
            )
            target = backend.resolve_collection(collection[0])
            backend.create_or_update_collection_note(
                target.key, html, "paperful-ask-batch"
            )
            if not json_out:
                console.print(
                    f"[green]Zotero collection note updated for {collection[0]}.[/]"
                )
        if not json_out:
            console.print(
                f"Batch: {pack.answered} answered, {pack.skipped} skipped, "
                f"{pack.failed} failed → {folder}"
            )
        write_command_report(
            cfg,
            command="ask",
            scope=", ".join(collection) or "index",
            summary={
                "questions": pack.questions,
                "answered": pack.answered,
                "skipped": pack.skipped,
                "failed": pack.failed,
                "pack": str(folder),
            },
            items=[_asdict(r) for r in pack.rows],
            flags={
                "top_k": top_k or cfg.rag_top_k,
                "model": pack.model,
                "focus": pack.focus,
                "ask_mode": pack.ask_mode,
                "from_file": str(from_file),
                "batch": True,
            },
            started=started,
        )
        code = batch_exit(ok=pack.answered + pack.skipped, failed=pack.failed)
        if json_out:
            payload = ask_envelope(
                items=[_asdict(r) for r in pack.rows],
                summary={
                    "questions": pack.questions,
                    "answered": pack.answered,
                    "skipped": pack.skipped,
                    "failed": pack.failed,
                    "pack": str(folder),
                },
                flags={
                    "read_only": not apply,
                    "batch": True,
                    "focus": pack.focus,
                    "ask_mode": pack.ask_mode,
                    "top_k": top_k or cfg.rag_top_k,
                },
                exit_code=code,
            )
            cli_mod._emit_agent(payload, json_out=True, human=lambda: None)
            return
        if pack.failed:
            raise typer.Exit(1)
        return

    answered: list[dict[str, Any]] = []
    failures = 0
    from .rag.thread import load_thread, new_id, rewrite_query, save_thread

    use_thread = thread is not None or (
        (not json_out) and question is None and sys.stdin.isatty()
    )
    thread_id = None
    turns: list[dict[str, str]] = []
    if use_thread:
        raw_id = (thread or "").strip()
        thread_id = new_id() if raw_id in {"", "new"} else raw_id
        loaded = load_thread(cfg.state_dir, thread_id)
        turns = list(loaded.turns)
        if use_thread and not json_out:
            console.print(f"[dim]Thread {thread_id} ({len(turns) // 2} turns)[/]")
    for asked in cli_mod._ask_questions(question):
        retrieve_as = asked
        if turns:
            retrieve_as = rewrite_query(cfg, asked, turns, client=client)
        try:
            row = cli_mod._ask_once(
                cfg,
                asked,
                stream=not no_stream,
                show_context=show_context and not json_out,
                history=turns,
                retrieve_as=retrieve_as,
                k=top_k,
                keys=keys,
                focus=focus_name,
                prompt_path=prompt_path,
                client=client,
                embedder=embedder,
                index=index,
                ledger=ledger,
                quiet=json_out,
                ask_mode=mode,
            )
            row["retrieve_as"] = retrieve_as
            row["focus"] = focus_name
            row["ask_mode"] = mode
            answered.append(row)
            if use_thread:
                turns.append({"role": "user", "content": asked})
                turns.append({"role": "assistant", "content": row.get("answer") or ""})
                from .rag.thread import Thread

                save_thread(
                    cfg.state_dir,
                    Thread(thread_id=thread_id, turns=turns, last_query=retrieve_as),
                )
        except KeyboardInterrupt:
            if not json_out:
                console.print("\n[yellow]Cancelled.[/]")
            failures += 1
        except LLMClientError as exc:
            if not json_out:
                console.print()
                console.print(str(exc), markup=False, style="red")
            failures += 1
        if question is None and not json_out:
            console.print()
    if answered or failures:
        write_command_report(
            cfg,
            command="ask",
            scope=", ".join(collection) or "index",
            summary={
                "questions": len(answered) + failures,
                "answered": len(answered),
                **({"thread": thread_id} if thread_id else {}),
            },
            items=answered,
            flags={
                "top_k": top_k or cfg.rag_top_k,
                "model": cfg.rag_model or cfg.llm_model,
                "embed_model": cfg.rag_embed_model,
                "focus": focus_name,
                "ask_mode": mode,
                **({"thread": thread_id} if thread_id else {}),
            },
            started=started,
        )
    code = batch_exit(ok=len(answered), failed=failures)
    if json_out:
        first = (question or "").strip()
        summary = {
            "questions": len(answered) + failures,
            "answered": len(answered),
        }
        if first:
            summary["question"] = first
        if thread_id:
            summary["thread"] = thread_id
        payload = ask_envelope(
            items=answered,
            summary=summary,
            flags={
                "read_only": True,
                "top_k": top_k or cfg.rag_top_k,
                "focus": focus_name,
                "ask_mode": mode,
                **({"thread": thread_id} if thread_id else {}),
            },
            exit_code=code,
        )
        cli_mod._emit_agent(payload, json_out=True, human=lambda: None)
        return
    if question is not None and failures:
        raise typer.Exit(1)


def run_claim_check(
    console: Console,
    cfg: Config,
    *,
    item: list[str],
    file_path: Path | None,
    collection: list[str],
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    top_k: int | None,
    question: str | None,
    from_file: Path | None,
    apply: bool,
    thread: str | None,
    json_out: bool,
) -> None:
    """Stage-1 Ask claim-check: pack only, no LLM, no --apply."""
    from rich.markup import escape
    from rich.table import Table

    from . import cli_runtime as cli_mod
    from .agent_json import envelope
    from .claim_check import (
        HONESTY_BANNER,
        claim_check_id,
        collect_claim_check,
        pack_payload,
        resolve_claim_check_k,
        write_pack,
    )
    from .critique_extract import SUPPORTED, ExtractError, extract_path
    from .lint import resolve_pdf_path
    from .rag.retrieve import scope_keys
    from .store import Manifest

    if apply:
        console.print(
            "[red]ask --claim-check does not write notes (--apply is later).[/]"
        )
        raise typer.Exit(1)
    if from_file is not None:
        console.print(
            "[red]ask --claim-check cannot use --from-file (that is questions).[/]"
        )
        raise typer.Exit(1)
    if thread is not None:
        console.print("[red]ask --claim-check cannot use --thread.[/]")
        raise typer.Exit(1)
    if question is not None and str(question).strip():
        console.print(
            "[red]ask --claim-check takes --file or --item, not a question.[/]"
        )
        raise typer.Exit(1)

    item_keys = [tok.strip() for tok in item if tok and str(tok).strip()]
    if bool(item_keys) == bool(file_path):
        console.print(
            "[red]ask --claim-check needs exactly one of --item KEY or --file PATH.[/]"
        )
        raise typer.Exit(1)
    if item_keys and len(item_keys) != 1:
        console.print("[red]ask --claim-check --item takes one manuscript key.[/]")
        raise typer.Exit(1)
    if file_path is not None and file_path.suffix.lower() not in SUPPORTED:
        console.print(
            "[red]Unsupported format. Save as pdf, txt, md, html, rtf, docx, "
            "odt, pptx (legacy .doc needs antiword, catdoc, or LibreOffice).[/]"
        )
        raise typer.Exit(1)

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
            library=False,
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
        collections=collections or None,
        year_from=year_from,
        year_to=year_to,
        item_types=types,
    )
    scope = ", ".join(collections) if collections else "index"
    cid = claim_check_id(
        kind=kind,
        item_key=item_key,
        original_name=file_path.name if file_path is not None else "",
    )
    per_k = resolve_claim_check_k(cfg, top_k)
    started = time.time()
    t0 = time.perf_counter()

    def _on_status(msg: str) -> None:
        elapsed = time.perf_counter() - t0
        console.print(f"[dim]{elapsed:5.0f}s[/] {escape(msg)}")

    try:
        with cli_mod._spinner("Claim-check", json_out=json_out) as spin:

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

            rows, skips = collect_claim_check(
                cfg,
                doc,
                k=per_k,
                keys=keys,
                exclude_key=item_key,
                search_fn=search_fn,
                on_status=on_status,
            )
    except ExtractError as exc:
        console.print(f"[red]{escape(str(exc))}[/]")
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
        k=per_k,
        inp=inp,
        rows=rows,
        skips=skips,
    )
    folder = write_pack(cfg, payload)
    payload["pack_dir"] = str(folder)
    counts = payload.get("counts") or {}
    write_command_report(
        cfg,
        command="ask",
        scope=scope,
        summary={
            "claim_check": True,
            "units": counts.get("units", 0),
            "supported": counts.get("supported", 0),
            "mixed": counts.get("mixed", 0),
            "unsupported": counts.get("unsupported", 0),
            "skips": counts.get("skips", 0),
            "pack_dir": str(folder),
        },
        items=[
            {
                "quote": row.quote[:200],
                "status": row.status,
                "loc": row.loc,
            }
            for row in rows[:200]
        ],
        flags={"claim_check": True, "k": per_k, "read_only": True},
        started=started,
    )
    envelope_payload = envelope(
        command="ask",
        summary={
            "claim_check": True,
            "units": counts.get("units", 0),
            "supported": counts.get("supported", 0),
            "mixed": counts.get("mixed", 0),
            "unsupported": counts.get("unsupported", 0),
            "skips": counts.get("skips", 0),
            "pack_dir": str(folder),
            "claim_check_id": cid,
        },
        items=[
            {
                "quote": row.quote[:200],
                "status": row.status,
                "loc": row.loc,
                "hits": [
                    {"item_key": hit.item_key, "pages": hit.pages, "quote": hit.quote}
                    for hit in row.hits
                ],
            }
            for row in rows[:50]
        ],
        paths={"pack": str(folder)},
        flags={"claim_check": True, "read_only": True, "k": per_k},
    )

    def _human() -> None:
        table = Table(title="claim-check")
        table.add_column("Status")
        table.add_column("Sentence")
        table.add_column("Hits")
        for row in rows[:20]:
            clip = row.quote if len(row.quote) <= 60 else row.quote[:59] + "…"
            hit_s = ", ".join(h.item_key for h in row.hits[:3]) or "—"
            table.add_row(row.status, clip, hit_s)
        console.print(table)
        console.print(HONESTY_BANNER)
        console.print(f"[green]Pack → {folder}[/]")

    cli_mod._emit_agent(envelope_payload, json_out=json_out, human=_human)
