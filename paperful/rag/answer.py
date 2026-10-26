"""Answer a question from the index. The terminal, and later a chat loop, call this."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from ..config import Config
from ..llm import ChatRequest, LLMClient, ctx_tokens_for, get_client
from ..llm.embed import Embedder
from .cites import neighbor_keys
from .evidence import expand_queries, filter_evidence, summarize_hits
from .index import Index
from .ledger import Ledger
from .mode import resolve_ask_mode
from .prompt import (
    Source,
    build_context,
    build_messages,
    cited_markers,
    resolve_system_prompt,
)
from .retrieve import Hit, search, search_fused

NO_HITS = "Nothing in the index matches that question."

_INSUFFICIENT = (
    "do not answer the question",
    "do not contain the answer",
    "excerpts do not",
    "do not contain enough",
    "cannot answer",
    "nothing in the index",
    "insufficient information",
)


class AnswerStream:
    """An answer as it arrives. Iterate for the text pieces; read the rest after.

    ``hits`` and ``sources`` are known before the first piece. ``text`` and
    ``cited()`` are complete once iteration ends.
    """

    def __init__(
        self,
        pieces: Iterable[str],
        hits: list[Hit],
        sources: list[Source],
        *,
        ask_mode: str = "simple",
        evidence: dict[str, Any] | None = None,
    ):
        self._pieces = iter(pieces)
        self.hits = hits
        self.sources = sources
        self.text = ""
        self.ask_mode = ask_mode
        self.evidence = evidence or {}

    def __iter__(self) -> Iterator[str]:
        for piece in self._pieces:
            self.text += piece
            yield piece

    def read(self) -> str:
        """Consume what is left and return the whole answer."""
        for _ in self:
            pass
        return self.text

    def cited(self) -> list[Source]:
        """Sources the answer cited, in the order it first cited them."""
        by_marker = {source.marker: source for source in self.sources}
        return [by_marker[m] for m in cited_markers(self.text) if m in by_marker]

    def turns(self, question: str) -> tuple[dict[str, str], dict[str, str]]:
        """This exchange as two history entries for a follow-up ``answer`` call."""
        return (
            {"role": "user", "content": question},
            {"role": "assistant", "content": self.text},
        )


def looks_insufficient(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered or lowered == NO_HITS.lower():
        return True
    return any(needle in lowered for needle in _INSUFFICIENT)


def answer(
    cfg: Config,
    question: str,
    *,
    history: Iterable[dict[str, str]] = (),
    retrieve_as: str | None = None,
    k: int | None = None,
    keys: set[str] | None = None,
    focus: str | None = None,
    prompt_path: str | None = None,
    prompt_text: str | None = None,
    client: LLMClient | None = None,
    embedder: Embedder | None = None,
    index: Index | None = None,
    ledger: Ledger | None = None,
    ask_mode: str | None = None,
) -> AnswerStream:
    """Retrieve passages and start a cited answer.

    ``history`` is earlier ``{"role", "content"}`` turns, oldest first; they go
    to the model ahead of this question. Retrieval uses ``retrieve_as`` when
    given (a rewritten follow-up), otherwise this question. Nothing is sent
    to the chat model when no passage matches.
    """
    mode = resolve_ask_mode(cfg, ask_mode)
    if mode == "advanced":
        return _answer_advanced(
            cfg,
            question,
            history=history,
            retrieve_as=retrieve_as,
            k=k,
            keys=keys,
            focus=focus,
            prompt_path=prompt_path,
            prompt_text=prompt_text,
            client=client,
            embedder=embedder,
            index=index,
            ledger=ledger,
        )
    return _answer_simple(
        cfg,
        question,
        history=history,
        retrieve_as=retrieve_as,
        k=k,
        keys=keys,
        focus=focus,
        prompt_path=prompt_path,
        prompt_text=prompt_text,
        client=client,
        embedder=embedder,
        index=index,
        ledger=ledger,
    )


def _system(
    cfg: Config,
    *,
    focus: str | None,
    prompt_path: str | None,
    prompt_text: str | None,
) -> str:
    path = prompt_path if prompt_path is not None else (cfg.rag_prompt or None)
    system, _, _ = resolve_system_prompt(
        focus=focus if focus is not None else cfg.rag_focus,
        prompt_path=path,
        prompt_text=prompt_text,
    )
    return system


def _stream(
    cfg: Config,
    question: str,
    hits: list[Hit],
    *,
    history: Iterable[dict[str, str]],
    system: str,
    client: LLMClient,
    extra_headers: bool,
    prefer_summary: bool,
    cite_current_only: bool,
    ask_mode: str,
    evidence: dict[str, Any],
) -> AnswerStream:
    if not hits:
        return AnswerStream(
            [NO_HITS], [], [], ask_mode=ask_mode, evidence=evidence
        )
    context, sources = build_context(
        hits,
        cfg.rag_max_context_chars,
        extra_headers=extra_headers,
        prefer_summary=prefer_summary,
    )
    used = {source.item_key for source in sources}
    messages = build_messages(
        question,
        context,
        history,
        system=system,
        cite_current_only=cite_current_only,
    )
    prompt_chars = "".join(m["content"] for m in messages)
    request = ChatRequest(
        model=(cfg.rag_model or cfg.llm_model).strip(),
        messages=messages,
        timeout_seconds=cfg.llm_timeout_s,
        num_ctx=ctx_tokens_for(prompt_chars, max_num_ctx=cfg.llm_max_num_ctx),
    )
    return AnswerStream(
        client.chat_stream(request),
        [hit for hit in hits if hit.item_key in used],
        sources,
        ask_mode=ask_mode,
        evidence=evidence,
    )


def _answer_simple(
    cfg: Config,
    question: str,
    *,
    history: Iterable[dict[str, str]],
    retrieve_as: str | None,
    k: int | None,
    keys: set[str] | None,
    focus: str | None,
    prompt_path: str | None,
    prompt_text: str | None,
    client: LLMClient | None,
    embedder: Embedder | None,
    index: Index | None,
    ledger: Ledger | None,
) -> AnswerStream:
    query = (retrieve_as if retrieve_as is not None else question) or ""
    hits = search(
        cfg, query, k=k, keys=keys, embedder=embedder, index=index, ledger=ledger
    )
    if not hits:
        return AnswerStream([NO_HITS], [], [], ask_mode="simple")
    client = client or get_client(cfg)
    return _stream(
        cfg,
        question,
        hits,
        history=history,
        system=_system(
            cfg, focus=focus, prompt_path=prompt_path, prompt_text=prompt_text
        ),
        client=client,
        extra_headers=False,
        prefer_summary=False,
        cite_current_only=False,
        ask_mode="simple",
        evidence={},
    )


def _gather(
    cfg: Config,
    query: str,
    *,
    keys: set[str] | None,
    client: LLMClient,
    embedder: Embedder | None,
    index: Index | None,
    ledger: Ledger | None,
) -> tuple[list[Hit], list[Hit], str]:
    """Retrieve, summarize, filter. Returns (kept, candidates, cite skip reason)."""
    n = cfg.rag_query_variants
    queries = [query]
    if n > 1:
        queries = expand_queries(cfg, query, client, n)
    k = cfg.rag_evidence_k
    candidates = search_fused(
        cfg,
        queries,
        k=k,
        keys=keys,
        embedder=embedder,
        index=index,
        ledger=ledger,
    )
    scored = summarize_hits(cfg, candidates, query, client) if candidates else []
    kept = filter_evidence(cfg, scored)
    skipped = ""
    if cfg.rag_cite_hops >= 1 and len({h.item_key for h in kept}) < 2:
        from .index import ledger_path as _ledger_path

        ledger = ledger or Ledger(_ledger_path(cfg))
        extra, skipped = neighbor_keys(
            cfg, {h.item_key for h in kept or candidates}, ledger
        )
        if extra:
            hop_keys = extra
            if cfg.rag_cite_scope == "scope" and keys is not None:
                hop_keys = extra & keys
            hop_keys -= {h.item_key for h in kept}
            if hop_keys:
                more = search_fused(
                    cfg,
                    [query],
                    k=k,
                    keys=hop_keys,
                    embedder=embedder,
                    index=index,
                    ledger=ledger,
                )
                new = [h for h in more if (h.item_key, h.chunk_index) not in {
                    (x.item_key, x.chunk_index) for x in scored
                }]
                if new:
                    scored.extend(summarize_hits(cfg, new, query, client))
                    kept = filter_evidence(cfg, scored)
    return kept, scored, skipped


def _answer_advanced(
    cfg: Config,
    question: str,
    *,
    history: Iterable[dict[str, str]],
    retrieve_as: str | None,
    k: int | None,
    keys: set[str] | None,
    focus: str | None,
    prompt_path: str | None,
    prompt_text: str | None,
    client: LLMClient | None,
    embedder: Embedder | None,
    index: Index | None,
    ledger: Ledger | None,
) -> AnswerStream:
    del k  # advanced uses evidence_k
    query = (retrieve_as if retrieve_as is not None else question) or ""
    client = client or get_client(cfg)
    system = _system(
        cfg, focus=focus, prompt_path=prompt_path, prompt_text=prompt_text
    )
    prior = list(history)
    kept, candidates, skipped = _gather(
        cfg,
        query,
        keys=keys,
        client=client,
        embedder=embedder,
        index=index,
        ledger=ledger,
    )
    evidence = {
        "candidates": len(candidates),
        "kept": len(kept),
        "cite_hops_skipped": skipped or None,
    }
    retries = cfg.rag_insufficient_retries
    if retries <= 0:
        return _stream(
            cfg,
            question,
            kept,
            history=prior,
            system=system,
            client=client,
            extra_headers=True,
            prefer_summary=True,
            cite_current_only=bool(prior),
            ask_mode="advanced",
            evidence=evidence,
        )
    attempt = 0
    used_query = query
    while True:
        reply = _stream(
            cfg,
            question,
            kept,
            history=prior,
            system=system,
            client=client,
            extra_headers=True,
            prefer_summary=True,
            cite_current_only=bool(prior),
            ask_mode="advanced",
            evidence=evidence,
        )
        text = reply.read()
        attempt += 1
        if attempt > retries or not looks_insufficient(text):
            return AnswerStream(
                [text],
                reply.hits,
                reply.sources,
                ask_mode="advanced",
                evidence=evidence,
            )
        from .thread import rewrite_query

        nxt = rewrite_query(cfg, question, prior, client=client)
        if nxt == used_query:
            return AnswerStream(
                [text],
                reply.hits,
                reply.sources,
                ask_mode="advanced",
                evidence=evidence,
            )
        used_query = nxt
        fresh, candidates, skipped = _gather(
            cfg,
            used_query,
            keys=keys,
            client=client,
            embedder=embedder,
            index=index,
            ledger=ledger,
        )
        if not fresh or {(h.item_key, h.chunk_index) for h in fresh} <= {
            (h.item_key, h.chunk_index) for h in kept
        }:
            return AnswerStream(
                [text],
                reply.hits,
                reply.sources,
                ask_mode="advanced",
                evidence=evidence,
            )
        kept = fresh
        evidence = {
            "candidates": len(candidates),
            "kept": len(kept),
            "cite_hops_skipped": skipped or None,
            "retried": True,
        }
