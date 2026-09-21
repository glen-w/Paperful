"""Plan-time LLM config validation (no paid completions)."""

from __future__ import annotations

from urllib.parse import urlparse

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class LlmConfigError(Exception):
    """Invalid or incomplete LLM configuration."""


class LlmExtraMissingError(LlmConfigError):
    """LiteLLM path selected but paperful[llm] is not installed."""


def validate_ollama_url(url: str, allow_remote: bool) -> None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise LlmConfigError(
            f"Ollama URL scheme {parsed.scheme!r} is not supported; use http or https."
        )
    host = parsed.hostname
    if not host:
        raise LlmConfigError("Ollama URL must include a hostname.")
    if host not in LOCAL_HOSTS and not allow_remote:
        raise LlmConfigError(
            f"Ollama URL host {host!r} is not local. "
            "Set llm.allow_remote = true to permit non-loopback endpoints."
        )


def reject_litellm_ollama_model(model: str, *, context: str = "") -> None:
    low = model.strip().lower()
    if low.startswith(("ollama/", "ollama:")):
        prefix = f"{context}: " if context else ""
        raise LlmConfigError(
            f'{prefix}model {model!r} must use llm.provider = "ollama", not litellm.'
        )


def validate_llm_api_base(url: str | None) -> None:
    if not url or not str(url).strip():
        return
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in ("http", "https"):
        raise LlmConfigError("llm.api_base must use http or https.")


def llm_egress_is_remote(cfg) -> bool:
    """True when completions may leave the machine."""
    if not cfg.llm_enabled:
        return False
    if cfg.llm_provider == "litellm":
        return True
    if cfg.llm_allow_remote:
        return True
    try:
        validate_ollama_url(cfg.llm_base_url, False)
        return False
    except LlmConfigError:
        return True
