"""Answer a question from the index. The terminal, and later a chat loop, call this."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from ..config import Config
from ..llm import ChatRequest, LLMClient, ctx_tokens_for, get_client
from ..llm.embed import Embedder
from .index import Index
from .ledger import Ledger
from .prompt import (
    Source,
    build_context,
    build_messages,
    cited_markers,
    resolve_system_prompt,
)
from .retrieve import Hit, search

NO_HITS = "Nothing in the index matches that question."


class AnswerStream:
    """An answer as it arrives. Iterate for the text pieces; read the rest after.

    ``hits`` and ``sources`` are known before the first piece. ``text`` and
    ``cited()`` are complete once iteration ends.
    """

    def __init__(self, pieces: Iterable[str], hits: list[Hit], sources: list[Source]):
        self._pieces = iter(pieces)
        self.hits = hits
        self.sources = sources
        self.text = ""

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
) -> AnswerStream:
    """Retrieve passages and start a cited answer.

    ``history`` is earlier ``{"role", "content"}`` turns, oldest first; they go
    to the model ahead of this question. Retrieval uses ``retrieve_as`` when
    given (a rewritten follow-up), otherwise this question. Nothing is sent
    to the chat model when no passage matches.
    """
    query = (retrieve_as if retrieve_as is not None else question) or ""
    hits = search(cfg, query, k=k, keys=keys, embedder=embedder, index=index, ledger=ledger)
    if not hits:
        return AnswerStream([NO_HITS], [], [])
    context, sources = build_context(hits, cfg.rag_max_context_chars)
    used = {source.item_key for source in sources}
    path = prompt_path if prompt_path is not None else (cfg.rag_prompt or None)
    system, _, _ = resolve_system_prompt(
        focus=focus if focus is not None else cfg.rag_focus,
        prompt_path=path,
        prompt_text=prompt_text,
    )
    messages = build_messages(question, context, history, system=system)
    prompt_chars = "".join(m["content"] for m in messages)
    request = ChatRequest(
        model=(cfg.rag_model or cfg.llm_model).strip(),
        messages=messages,
        timeout_seconds=cfg.llm_timeout_s,
        num_ctx=ctx_tokens_for(prompt_chars, max_num_ctx=cfg.llm_max_num_ctx),
    )
    client = client or get_client(cfg)
    return AnswerStream(
        client.chat_stream(request),
        [hit for hit in hits if hit.item_key in used],
        sources,
    )
