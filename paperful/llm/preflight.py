"""Shared preflight for LLM verbs."""

from __future__ import annotations

from ..config import Config
from .client import get_client_impl
from .embed import Embedder, get_embedder
from .validate import (
    LlmConfigError,
    reject_litellm_ollama_model,
    validate_llm_api_base,
    validate_ollama_url,
)


def _agent_model(cfg: Config) -> str:
    return (cfg.browser_agent_model or cfg.llm_model).strip()


def validate_llm_for_verb(
    cfg: Config, *, require_enabled: bool = True, model: str | None = None
) -> str:
    """Return the model name to use; raise LlmConfigError on misconfiguration."""
    if require_enabled and not cfg.llm_enabled:
        raise LlmConfigError("llm.enabled is false in config.toml")
    model = (model or cfg.llm_model).strip()
    if not model:
        raise LlmConfigError("llm.model is empty")
    if cfg.llm_provider == "litellm":
        reject_litellm_ollama_model(model, context="llm")
        validate_llm_api_base(cfg.llm_api_base)
    else:
        validate_ollama_url(cfg.llm_base_url, cfg.llm_allow_remote)
    client = get_client_impl(cfg)
    ok, msg = client.check_config(model)
    if not ok:
        raise LlmConfigError(msg)
    return model


def validate_llm_for_ask(cfg: Config) -> str:
    """Chat model for `paperful ask`: ``[rag].model``, else ``[llm].model``."""
    return validate_llm_for_verb(cfg, model=cfg.rag_model or None)


def validate_embedder(cfg: Config) -> Embedder:
    """Return a ready embedder; raise LlmConfigError when it cannot be used."""
    if not cfg.rag_enabled:
        raise LlmConfigError("rag.enabled is false in config.toml")
    model = cfg.rag_embed_model.strip()
    if not model:
        raise LlmConfigError("rag.embed_model is empty")
    if cfg.rag_embed_provider == "litellm":
        if model.lower().startswith(("ollama/", "ollama:")):
            raise LlmConfigError(
                f"rag.embed_model {model!r} must use "
                'rag.embed_provider = "ollama", not litellm.'
            )
        validate_llm_api_base(cfg.rag_embed_api_base or cfg.llm_api_base)
    else:
        validate_ollama_url(
            cfg.rag_embed_base_url or cfg.llm_base_url, cfg.llm_allow_remote
        )
    embedder = get_embedder(cfg)
    ok, msg = embedder.check_config()
    if not ok:
        raise LlmConfigError(msg)
    return embedder


def validate_llm_for_recover(cfg: Config) -> str:
    validate_llm_for_verb(cfg)
    agent_model = _agent_model(cfg)
    if cfg.llm_provider == "litellm":
        reject_litellm_ollama_model(agent_model, context="browser_agent")
    return agent_model
