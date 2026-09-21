"""LLM transport: Ollama (httpx) and optional LiteLLM."""

from __future__ import annotations

import json
from dataclasses import dataclass
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
        if request.json_mode:
            options["format"] = "json"
        payload: dict[str, Any] = {
            "model": request.model,
            "prompt": request.prompt,
            "stream": False,
            "options": options,
        }
        with httpx.Client(timeout=request.timeout_seconds) as client:
            resp = client.post(f"{self._api_root()}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
        if data.get("error"):
            raise LLMClientError(str(data["error"]))
        return str(data.get("response") or "")

    def complete_json(self, request: CompletionRequest) -> dict[str, Any]:
        text = self.complete(
            CompletionRequest(
                model=request.model,
                prompt=request.prompt,
                timeout_seconds=request.timeout_seconds,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                json_mode=True,
            )
        )
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
        resp = litellm.completion(**kwargs)
        choice = (resp.choices or [None])[0]
        if choice is None:
            return ""
        msg = choice.message
        return str(getattr(msg, "content", None) or "")

    def complete_json(self, request: CompletionRequest) -> dict[str, Any]:
        return _parse_json_object(
            self.complete(
                CompletionRequest(
                    model=request.model,
                    prompt=request.prompt,
                    timeout_seconds=request.timeout_seconds,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    json_mode=True,
                )
            )
        )


def get_client_impl(cfg) -> LLMClient:
    from ..config import Config

    if not isinstance(cfg, Config):
        raise TypeError("cfg must be Config")
    if not cfg.llm_enabled:
        return NullLLMClient()
    if cfg.llm_provider == "litellm":
        return LiteLLMClient(api_base=cfg.llm_api_base or None)
    return OllamaClient(base_url=cfg.llm_base_url, allow_remote=cfg.llm_allow_remote)


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
