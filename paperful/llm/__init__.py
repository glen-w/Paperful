"""Local-first LLM client factory."""

from __future__ import annotations

from ..config import Config
from .client import (
    ChatRequest,
    CompletionRequest,
    LiteLLMClient,
    LLMClient,
    LLMClientError,
    NullLLMClient,
    OllamaClient,
    chat,
    ctx_tokens_for,
    get_client_impl,
)
from .embed import (
    EmbedError,
    Embedder,
    embed_fingerprint,
    get_embedder,
    task_prefixes,
)
from .preflight import (
    validate_embedder,
    validate_llm_for_ask,
    validate_llm_for_recover,
    validate_llm_for_verb,
)
from .validate import (
    LlmConfigError,
    LlmExtraMissingError,
    embed_egress_is_remote,
    llm_egress_is_remote,
    reject_litellm_ollama_model,
    resolve_ollama_base_url,
)

__all__ = [
    "ChatRequest",
    "CompletionRequest",
    "EmbedError",
    "Embedder",
    "chat",
    "ctx_tokens_for",
    "embed_egress_is_remote",
    "embed_fingerprint",
    "get_embedder",
    "task_prefixes",
    "validate_embedder",
    "validate_llm_for_ask",
    "LLMClient",
    "LLMClientError",
    "LiteLLMClient",
    "LlmConfigError",
    "LlmExtraMissingError",
    "NullLLMClient",
    "OllamaClient",
    "get_client",
    "llm_egress_is_remote",
    "agent_model_uses_litellm",
    "llm_model_for_agent",
    "reject_litellm_ollama_model",
    "resolve_ollama_base_url",
    "validate_llm_for_recover",
    "validate_llm_for_verb",
]


def get_client(cfg: Config) -> LLMClient:
    return get_client_impl(cfg)


def llm_model_for_agent(cfg: Config, *, fallback: bool = False) -> str:
    if fallback:
        return cfg.browser_agent_fallback_model.strip()
    return (cfg.browser_agent_model or cfg.llm_model).strip()


def agent_model_uses_litellm(cfg: Config, model: str) -> bool:
    """True when browser-use should use ChatLiteLLM for this model tag."""
    if cfg.llm_provider == "litellm":
        return True
    return "/" in (model or "")
