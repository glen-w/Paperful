"""Local-first LLM client factory."""

from __future__ import annotations

from ..config import Config
from .client import (
    CompletionRequest,
    LiteLLMClient,
    LLMClient,
    LLMClientError,
    NullLLMClient,
    OllamaClient,
    get_client_impl,
)
from .preflight import validate_llm_for_recover, validate_llm_for_verb
from .validate import (
    LlmConfigError,
    LlmExtraMissingError,
    llm_egress_is_remote,
    reject_litellm_ollama_model,
)

__all__ = [
    "CompletionRequest",
    "LLMClient",
    "LLMClientError",
    "LiteLLMClient",
    "LlmConfigError",
    "LlmExtraMissingError",
    "NullLLMClient",
    "OllamaClient",
    "get_client",
    "llm_egress_is_remote",
    "llm_model_for_agent",
    "reject_litellm_ollama_model",
    "validate_llm_for_recover",
    "validate_llm_for_verb",
]


def get_client(cfg: Config) -> LLMClient:
    return get_client_impl(cfg)


def llm_model_for_agent(cfg: Config) -> str:
    return (cfg.browser_agent_model or cfg.llm_model).strip()
