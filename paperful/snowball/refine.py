"""Optional query suggestions. They never start a crawl or create items."""

from __future__ import annotations

from typing import Any, Callable

Suggester = Callable[[str], list[str]]


def suggestions_for(query: str, suggester: Suggester) -> tuple[list[str], str | None]:
    text = (query or "").strip()
    if not text:
        return [], "no query"
    try:
        raw = suggester(text)
    except Exception as exc:
        return [], str(exc)
    out: list[str] = []
    for item in raw:
        line = str(item).strip()
        if line and line not in out:
            out.append(line)
        if len(out) >= 5:
            break
    return out, None


def llm_suggester(cfg: Any) -> Suggester:
    from ..llm import CompletionRequest, LLMClientError, get_client
    from ..llm.client import ctx_tokens_for

    client = get_client(cfg)

    def suggest(query: str) -> list[str]:
        prompt = (
            "Suggest up to 5 short scholarly search queries that refine this seed. "
            "Return a JSON object {\"queries\": [\"...\"]}. Seed: "
            f"{query}"
        )
        try:
            payload = client.complete_json(
                CompletionRequest(
                    model=cfg.llm_model,
                    prompt=prompt,
                    json_mode=True,
                    num_ctx=ctx_tokens_for(prompt, max_num_ctx=cfg.llm_max_num_ctx),
                )
            )
        except LLMClientError as exc:
            raise RuntimeError(str(exc)) from exc
        queries = payload.get("queries") if isinstance(payload, dict) else None
        if not isinstance(queries, list):
            return []
        return [str(item) for item in queries]

    return suggest
