"""Plan-time LLM config validation (no paid completions)."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from urllib.parse import urlparse, urlunparse

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
DOCKER_GATEWAY_HOST = "host.docker.internal"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


class LlmConfigError(Exception):
    """Invalid or incomplete LLM configuration."""


class LlmExtraMissingError(LlmConfigError):
    """LiteLLM path selected but paperful[llm] is not installed."""


def _in_docker() -> bool:
    return Path("/.dockerenv").exists()


def _replace_url_host(url: str, new_host: str) -> str:
    parsed = urlparse(url.strip())
    port = parsed.port
    # Bracket IPv6 literals in the netloc.
    host_part = f"[{new_host}]" if ":" in new_host and not new_host.startswith("[") else new_host
    netloc = f"{host_part}:{port}" if port is not None else host_part
    if parsed.username:
        user = parsed.username
        if parsed.password:
            user = f"{user}:{parsed.password}"
        netloc = f"{user}@{netloc}"
    return urlunparse(parsed._replace(netloc=netloc))


def _ipv4_literal(hostname: str) -> str | None:
    """Prefer A records so httpx does not fail on unreachable Docker Desktop AAAA."""
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return None
    if not infos:
        return None
    return infos[0][4][0]


def resolve_ollama_base_url(url: str | None = None) -> str:
    """URL to call for Ollama (Docker-aware, same idea as ``PAPERFUL_ZOTERO_HOST``).

    - Default / loopback config stays ``http://127.0.0.1:11434`` on the host.
    - Inside a container, loopback is rewritten to ``host.docker.internal`` so the
      daemon on the host is reachable (Compose sets ``extra_hosts``).
    - ``PAPERFUL_OLLAMA_HOST`` overrides the hostname. Outside Docker,
      ``host.docker.internal`` falls back to ``127.0.0.1`` (often unresolvable on
      the host).
    - Inside Docker, ``host.docker.internal`` is resolved to an IPv4 literal so
      clients do not prefer an unreachable IPv6 AAAA (Errno 101).
    """
    raw = (url or "").strip() or DEFAULT_OLLAMA_BASE_URL
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.hostname:
        return raw

    env_host = (os.environ.get("PAPERFUL_OLLAMA_HOST") or "").strip()
    docker = _in_docker()
    host = parsed.hostname
    # Env / Docker rewrites apply only to loopback targets. Never rewrite a
    # remote hostname — that would bypass allow_remote when .env sets
    # PAPERFUL_OLLAMA_HOST=host.docker.internal (loaded via paperful.cli dotenv).
    if host in LOCAL_HOSTS:
        if env_host:
            if env_host == DOCKER_GATEWAY_HOST and not docker:
                host = "127.0.0.1"
            else:
                host = env_host
        elif docker:
            host = DOCKER_GATEWAY_HOST

    if docker and host == DOCKER_GATEWAY_HOST:
        ipv4 = _ipv4_literal(DOCKER_GATEWAY_HOST)
        if ipv4:
            host = ipv4

    if host == parsed.hostname:
        return raw
    return _replace_url_host(raw, host)


def ollama_url_is_docker_bridge(url: str) -> bool:
    """True when the URL targets the Compose host gateway from inside Docker."""
    if not _in_docker():
        return False
    host = urlparse(url.strip()).hostname
    if host == DOCKER_GATEWAY_HOST:
        return True
    # resolve_ollama_base_url may have substituted the gateway's IPv4 literal.
    ipv4 = _ipv4_literal(DOCKER_GATEWAY_HOST)
    return bool(ipv4 and host == ipv4)


def validate_ollama_url(url: str, allow_remote: bool) -> None:
    resolved = resolve_ollama_base_url(url)
    parsed = urlparse(resolved)
    if parsed.scheme not in ("http", "https"):
        raise LlmConfigError(
            f"Ollama URL scheme {parsed.scheme!r} is not supported; use http or https."
        )
    host = parsed.hostname
    if not host:
        raise LlmConfigError("Ollama URL must include a hostname.")
    if host in LOCAL_HOSTS or ollama_url_is_docker_bridge(resolved):
        return
    if not allow_remote:
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


def embed_egress_is_remote(cfg) -> bool:
    """True when passages sent for embedding may leave the machine."""
    if not cfg.rag_enabled:
        return False
    if cfg.rag_embed_provider == "litellm":
        return True
    try:
        validate_ollama_url(cfg.rag_embed_base_url or cfg.llm_base_url, False)
        return False
    except LlmConfigError:
        return True


def llm_egress_is_remote(cfg) -> bool:
    """True when completions may leave the machine."""
    if not cfg.llm_enabled:
        return False
    if cfg.llm_provider == "litellm":
        return True
    # Compose → host Ollama via host.docker.internal is same-machine, not egress.
    if ollama_url_is_docker_bridge(resolve_ollama_base_url(cfg.llm_base_url)):
        return False
    if cfg.llm_allow_remote:
        return True
    try:
        validate_ollama_url(cfg.llm_base_url, False)
        return False
    except LlmConfigError:
        return True
