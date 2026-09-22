"""LLM transport: Ollama (httpx) and optional LiteLLM."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from typing import Any, Protocol

import httpx

from .validate import (
    LlmExtraMissingError,
    validate_llm_api_base,
    validate_ollama_url,
)


class LLMClientError(Exception):
    """Configuration or transport error for an LLM client."""


@dataclass(frozen=True)
class CompletionRequest:
    model: str
    prompt: str
    timeout_seconds: float = 120.0
    temperature: float = 0.2
    max_tokens: int | None = None
    json_mode: bool = False
    num_ctx: int | None = None


def ctx_tokens_for(
    prompt: str, *, max_num_ctx: int = 32_768, reply_headroom: int = 2048
) -> int:
    """Context window large enough for this prompt, capped by config.

    Ollama's default window is often 2048–4096 tokens and silently drops the
    rest of the prompt. ~3 characters per token is a conservative estimate.
    """
    raw = math.ceil(len(prompt) / 3) + reply_headroom
    rounded = max(1024, ((raw + 1023) // 1024) * 1024)
    return min(rounded, max(1024, int(max_num_ctx)))


class LLMClient(Protocol):
    provider: str

    def check_config(self, model: str) -> tuple[bool, str]: ...

    def complete(self, request: CompletionRequest) -> str: ...

    def complete_json(self, request: CompletionRequest) -> dict[str, Any]: ...


class NullLLMClient:
    provider = "null"

    def check_config(self, model: str) -> tuple[bool, str]:
        return False, "LLM is disabled"

    def complete(self, request: CompletionRequest) -> str:
        raise LLMClientError("LLM is disabled")

    def complete_json(self, request: CompletionRequest) -> dict[str, Any]:
        raise LLMClientError("LLM is disabled")


@dataclass
class OllamaClient:
    base_url: str
    allow_remote: bool
    provider: str = "ollama"

    def _api_root(self) -> str:
        root = self.base_url.rstrip("/")
        root = root.removesuffix("/v1")
        return root

    def check_config(self, model: str) -> tuple[bool, str]:
        validate_ollama_url(self._api_root(), self.allow_remote)
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(f"{self._api_root()}/api/tags")
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            return False, f"Ollama unreachable: {exc}"
        names = [m.get("name", "") for m in (data.get("models") or [])]
        if not any(model in n or n.startswith(f"{model}:") for n in names):
            return False, f"model {model!r} not in Ollama tags ({len(names)} installed)"
        return True, "ok"

    def complete(self, request: CompletionRequest) -> str:
        validate_ollama_url(self._api_root(), self.allow_remote)
        options: dict[str, Any] = {"temperature": request.temperature}
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens
        if request.num_ctx is not None:
            options["num_ctx"] = request.num_ctx
        if request.json_mode:
            options["format"] = "json"
        payload: dict[str, Any] = {
            "model": request.model,
            "prompt": request.prompt,
            "stream": True,
            "options": options,
        }
        # Stream so a long local completion (prefill + thinking) is not one
        # read against the whole answer. The timeout is the gap between chunks.
        parts: list[str] = []
        url = f"{self._api_root()}/api/generate"
        try:
            with httpx.Client(timeout=request.timeout_seconds) as client:
                with client.stream("POST", url, json=payload) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        piece = _ollama_response_piece(line)
                        if piece:
                            parts.append(piece)
        except httpx.TimeoutException as exc:
            raise LLMClientError(
                f"Ollama timed out after {request.timeout_seconds:g}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMClientError(f"Ollama request failed: {exc}") from exc
        return "".join(parts)

    def complete_json(self, request: CompletionRequest) -> dict[str, Any]:
        text = self.complete(replace(request, json_mode=True))
        return _parse_json_object(text)


@dataclass
class LiteLLMClient:
    api_base: str | None
    provider: str = "litellm"

    def check_config(self, model: str) -> tuple[bool, str]:
        try:
            import litellm  # noqa: F401
        except ImportError:
            return False, "LiteLLM not installed; pip install 'paperful[llm]'"
        validate_llm_api_base(self.api_base)
        return True, "ok"

    def complete(self, request: CompletionRequest) -> str:
        try:
            import litellm
        except ImportError:
            raise LlmExtraMissingError(
                "LiteLLM is not installed; pip install 'paperful[llm]'"
            )
        validate_llm_api_base(self.api_base)
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.prompt}],
            "temperature": request.temperature,
            "timeout": request.timeout_seconds,
        }
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens
        if request.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = litellm.completion(**kwargs)
        except Exception as exc:
            raise LLMClientError(f"LiteLLM request failed: {exc}") from exc
        choice = (resp.choices or [None])[0]
        if choice is None:
            return ""
        msg = choice.message
        return str(getattr(msg, "content", None) or "")

    def complete_json(self, request: CompletionRequest) -> dict[str, Any]:
        return _parse_json_object(self.complete(replace(request, json_mode=True)))


def get_client_impl(cfg) -> LLMClient:
    from ..config import Config

    if not isinstance(cfg, Config):
        raise TypeError("cfg must be Config")
    if not cfg.llm_enabled:
        return NullLLMClient()
    if cfg.llm_provider == "litellm":
        return LiteLLMClient(api_base=cfg.llm_api_base or None)
    return OllamaClient(base_url=cfg.llm_base_url, allow_remote=cfg.llm_allow_remote)


def _ollama_response_piece(line: str) -> str:
    """One streamed `/api/generate` line. Thinking text is not part of the answer."""
    if not line.strip():
        return ""
    try:
        chunk = json.loads(line)
    except json.JSONDecodeError as exc:
        raise LLMClientError(f"invalid Ollama stream: {exc}") from exc
    if not isinstance(chunk, dict):
        raise LLMClientError("expected JSON object from Ollama")
    if chunk.get("error"):
        raise LLMClientError(str(chunk["error"]))
    return str(chunk.get("response") or "")


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise LLMClientError("empty JSON response")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMClientError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMClientError("expected JSON object")
    return data
