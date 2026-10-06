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
) -> None:
    from . import cli as cli_mod
    from .agent_json import batch_exit
    from .agent_ops import ask_envelope
    from .llm import LLMClientError, get_client, llm_egress_is_remote
    from .llm.preflight import validate_llm_for_ask
    from .llm.validate import LlmConfigError
    from .library import get_backend
    from .rag.prompt import parse_focus
    from .rag.retrieve import scope_keys

    batch_mode = from_file is not None
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
    prompt_path = str(prompt.expanduser().resolve()) if prompt is not None else (
        cfg.rag_prompt or None
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
            )
            row["retrieve_as"] = retrieve_as
            row["focus"] = focus_name
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
                **({"thread": thread_id} if thread_id else {}),
            },
            exit_code=code,
        )
        cli_mod._emit_agent(payload, json_out=True, human=lambda: None)
        return
    if question is not None and failures:
        raise typer.Exit(1)
