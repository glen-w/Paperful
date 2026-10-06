"""One cited Ask turn for CLI and the workbench (no Typer)."""

from __future__ import annotations

from typing import Any

from ..config import Config
from ..llm import get_client, validate_embedder, validate_llm_for_ask
from .answer import answer
from .index import Index, IndexMismatch, IndexMissing, RagUnavailable, ledger_path
from .ledger import Ledger
from .prompt import parse_focus
from .retrieve import scope_keys
from .thread import Thread, load_thread, new_id, rewrite_query, save_thread


def run_ask_turn(
    cfg: Config,
    *,
    question: str,
    thread_id: str | None,
    collection: str,
    year_from: int | None,
    year_to: int | None,
    focus: str | None,
    top_k: int | None = None,
) -> dict[str, Any]:
    """Answer one question, append to a thread, and return a GUI/CLI row."""
    q = (question or "").strip()
    if not q:
        raise ValueError("question is required")
    if not cfg.rag_enabled:
        raise ValueError("rag.enabled is false")
    validate_llm_for_ask(cfg)
    embedder = validate_embedder(cfg)
    focus_name = parse_focus(focus if focus is not None else cfg.rag_focus)
    try:
        index = Index.open(cfg)
        ledger = Ledger(ledger_path(cfg))
    except (RagUnavailable, IndexMissing, IndexMismatch) as exc:
        raise ValueError(str(exc)) from exc
    coll = (collection or "").strip()
    keys = scope_keys(
        ledger,
        collections=[coll] if coll else [],
        year_from=year_from,
        year_to=year_to,
    )
    raw_id = (thread_id or "").strip()
    tid = new_id() if raw_id in {"", "new"} else raw_id
    loaded = load_thread(cfg.state_dir, tid)
    turns = list(loaded.turns)
    retrieve_as = rewrite_query(cfg, q, turns, client=get_client(cfg)) if turns else q
    reply = answer(
        cfg,
        q,
        history=turns,
        retrieve_as=retrieve_as,
        k=top_k,
        keys=keys,
        focus=focus_name,
        prompt_path=cfg.rag_prompt or None,
        client=get_client(cfg),
        embedder=embedder,
        index=index,
        ledger=ledger,
    )
    reply.read()
    cited = reply.cited()
    sources = [
        {
            "marker": s.marker,
            "itemKey": s.item_key,
            "title": s.title,
            "pages": s.pages,
            "citation": s.citation,
        }
        for s in reply.sources
    ]
    turns.append({"role": "user", "content": q})
    turns.append({"role": "assistant", "content": reply.text})
    save_thread(
        cfg.state_dir,
        Thread(thread_id=tid, turns=turns, last_query=retrieve_as),
    )
    return {
        "thread_id": tid,
        "question": q,
        "retrieve_as": retrieve_as,
        "answer": reply.text,
        "cited": [s.marker for s in cited],
        "sources": sources,
        "focus": focus_name,
    }
