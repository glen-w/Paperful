"""Shared preflight for LLM verbs."""

from __future__ import annotations

from ..config import Config
from .client import get_client_impl
from .validate import LlmConfigError, reject_litellm_ollama_model, validate_llm_api_base, validate_ollama_url


def _agent_model(cfg: Config) -> str:
    return (cfg.browser_agent_model or cfg.llm_model).strip()


def validate_llm_for_verb(cfg: Config, *, require_enabled: bool = True) -> str:
    """Return the model name to use; raise LlmConfigError on misconfiguration."""
    if require_enabled and not cfg.llm_enabled:
        raise LlmConfigError("llm.enabled is false in config.toml")
    model = cfg.llm_model.strip()
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


def validate_llm_for_recover(cfg: Config) -> str:
    model = validate_llm_for_verb(cfg)
    agent_model = _agent_model(cfg)
    if cfg.llm_provider == "litellm":
        reject_litellm_ollama_model(agent_model, context="browser_agent")
    return agent_model
