"""Embeddings for the library index: Ollama (httpx) and optional LiteLLM."""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

import httpx

from .client import LLMClientError
from .validate import LlmExtraMissingError, validate_llm_api_base, validate_ollama_url

T = TypeVar("T")

# (document prefix, query prefix) by base model name. Some embedding models are
# trained with a task instruction in front of the text; leaving it out puts
# queries and passages in slightly different spaces. Models not listed here
# (bge-m3, mxbai-embed-large, text-embedding-3-*) take no prefix.
_TASK_PREFIXES: dict[str, tuple[str, str]] = {
    "nomic-embed-text": ("search_document: ", "search_query: "),
}

_MAX_ATTEMPTS = 3
_RETRY_BASE_DELAY_S = 1.0
# LiteLLM exception class names worth a second try. Matched by name so the
# optional package is not imported at module load.
_LITELLM_TRANSIENT = frozenset(
    {"APIConnectionError", "InternalServerError", "ServiceUnavailableError"}
)


class EmbedError(LLMClientError):
    """Configuration or transport error for an embedder."""


class _Retriable(Exception):
    """A transient failure. The cause is re-raised as EmbedError after the last try."""


def model_base_name(model: str) -> str:
    """``openai/text-embedding-3-small`` or ``nomic-embed-text:latest`` → bare name."""
    name = model.strip().lower().rsplit("/", 1)[-1]
    return name.split(":", 1)[0]


def task_prefixes(model: str) -> tuple[str, str]:
    """Return the ``(document, query)`` prefixes this model expects."""
    return _TASK_PREFIXES.get(model_base_name(model), ("", ""))


def embed_fingerprint(provider: str, model: str) -> str:
    """Folder-safe name for one embedding model. A new model is a new index."""
    name = model.strip().lower().removesuffix(":latest")
    slug = re.sub(r"[^a-z0-9._-]+", "-", name).strip("-") or "model"
    return f"{provider.strip().lower()}__{slug}"


def _with_retries(
    op: Callable[[], T],
    *,
    attempts: int = _MAX_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run ``op``; try again after a connection drop or a 5xx. Timeouts are not retried."""
    for attempt in range(attempts):
        try:
            return op()
        except _Retriable as exc:
            if attempt + 1 >= attempts:
                raise EmbedError(str(exc)) from exc.__cause__
            sleep(_RETRY_BASE_DELAY_S * (2**attempt))
    raise EmbedError("no attempts made")  # pragma: no cover


def _unit(vector: list[float]) -> list[float]:
    """L2-normalise so the index's default L2 ranking equals cosine ranking."""
    norm = math.sqrt(sum(x * x for x in vector))
    if not norm or not math.isfinite(norm):
        raise EmbedError("embedding model returned an empty or non-finite vector")
    return [x / norm for x in vector]


class Embedder(Protocol):
    provider: str
    model: str

    def check_config(self) -> tuple[bool, str]: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class NullEmbedder:
    provider = "null"
    model = ""

    def check_config(self) -> tuple[bool, str]:
        return False, "rag.enabled is false in config.toml"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise EmbedError("rag.enabled is false in config.toml")

    def embed_query(self, text: str) -> list[float]:
        raise EmbedError("rag.enabled is false in config.toml")


@dataclass
class _BatchingEmbedder:
    """Prefixes, batching, and the count / width checks shared by both providers."""

    model: str
    batch_size: int = 32
    timeout_s: float = 120.0
    dim: int | None = field(default=None, init=False)

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def _embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        size = max(1, self.batch_size)
        for start in range(0, len(texts), size):
            batch = texts[start : start + size]
            vectors = self._embed_batch(batch)
            if len(vectors) != len(batch):
                raise EmbedError(
                    f"{self.model} returned {len(vectors)} vectors for {len(batch)} texts"
                )
            for vector in vectors:
                if self.dim is None:
                    self.dim = len(vector)
                if len(vector) != self.dim:
                    raise EmbedError(
                        f"{self.model} returned a {len(vector)}-dim vector; "
                        f"expected {self.dim}"
                    )
                out.append(_unit([float(x) for x in vector]))
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        prefix = task_prefixes(self.model)[0]
        return self._embed([f"{prefix}{text}" for text in texts])

    def embed_query(self, text: str) -> list[float]:
        prefix = task_prefixes(self.model)[1]
        return self._embed([f"{prefix}{text}"])[0]


@dataclass
class OllamaEmbedder(_BatchingEmbedder):
    base_url: str = "http://127.0.0.1:11434"
    allow_remote: bool = False
    provider: str = "ollama"

    def _api_root(self) -> str:
        return self.base_url.rstrip("/").removesuffix("/v1")

    def check_config(self) -> tuple[bool, str]:
        validate_ollama_url(self._api_root(), self.allow_remote)
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(f"{self._api_root()}/api/tags")
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            return False, f"Ollama unreachable: {exc}"
        names = [m.get("name", "") for m in (data.get("models") or [])]
        if not any(n == self.model or n.startswith(f"{self.model}:") for n in names):
            return False, (
                f"embedding model {self.model!r} not in Ollama tags. "
                f"Try: ollama pull {self.model}"
            )
        return True, "ok"

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        validate_ollama_url(self._api_root(), self.allow_remote)
        url = f"{self._api_root()}/api/embed"
        payload = {"model": self.model, "input": texts, "truncate": True}

        def call() -> list[list[float]]:
            try:
                with httpx.Client(timeout=self.timeout_s) as client:
                    resp = client.post(url, json=payload)
            except httpx.TimeoutException as exc:
                raise EmbedError(
                    f"Ollama embedding timed out after {self.timeout_s:g}s"
                ) from exc
            except httpx.TransportError as exc:
                raise _Retriable(f"Ollama unreachable: {exc}") from exc
            if resp.status_code >= 500:
                raise _Retriable(f"Ollama embedding failed: HTTP {resp.status_code}")
            if resp.status_code == 404:
                raise EmbedError(
                    f"Ollama has no embedding model {self.model!r}. "
                    f"Try: ollama pull {self.model}"
                )
            if resp.status_code >= 400:
                raise EmbedError(
                    f"Ollama embedding failed: HTTP {resp.status_code} "
                    f"{resp.text[:200]}"
                )
            try:
                vectors = resp.json().get("embeddings")
            except ValueError as exc:
                raise EmbedError(f"invalid Ollama embedding response: {exc}") from exc
            if not isinstance(vectors, list):
                raise EmbedError("Ollama embedding response has no 'embeddings' list")
            return vectors

        return _with_retries(call)


@dataclass
class LiteLLMEmbedder(_BatchingEmbedder):
    api_base: str | None = None
    provider: str = "litellm"

    def check_config(self) -> tuple[bool, str]:
        try:
            import litellm  # noqa: F401
        except ImportError:
            return False, "LiteLLM not installed; pip install 'paperful[llm]'"
        validate_llm_api_base(self.api_base)
        return True, "ok"

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        try:
            import litellm
        except ImportError:
            raise LlmExtraMissingError(
                "LiteLLM is not installed; pip install 'paperful[llm]'"
            )
        validate_llm_api_base(self.api_base)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "input": texts,
            "timeout": self.timeout_s,
        }
        if self.api_base:
            kwargs["api_base"] = self.api_base

        def call() -> list[list[float]]:
            try:
                resp = litellm.embedding(**kwargs)
            except Exception as exc:
                if type(exc).__name__ in _LITELLM_TRANSIENT:
                    raise _Retriable(f"LiteLLM embedding failed: {exc}") from exc
                raise EmbedError(f"LiteLLM embedding failed: {exc}") from exc
            return [_row_vector(row) for row in (_field(resp, "data") or [])]

        return _with_retries(call)


def _field(obj: Any, name: str) -> Any:
    """LiteLLM returns pydantic objects whose rows may be plain dicts."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _row_vector(row: Any) -> list[float]:
    vector = _field(row, "embedding")
    if not isinstance(vector, list):
        raise EmbedError("LiteLLM embedding row has no 'embedding' list")
    return vector


def get_embedder(cfg) -> Embedder:
    from ..config import Config

    if not isinstance(cfg, Config):
        raise TypeError("cfg must be Config")
    if not cfg.rag_enabled:
        return NullEmbedder()
    model = cfg.rag_embed_model.strip()
    if cfg.rag_embed_provider == "litellm":
        return LiteLLMEmbedder(
            model=model,
            batch_size=cfg.rag_embed_batch_size,
            timeout_s=cfg.llm_timeout_s,
            api_base=(cfg.rag_embed_api_base or cfg.llm_api_base) or None,
        )
    return OllamaEmbedder(
        model=model,
        batch_size=cfg.rag_embed_batch_size,
        timeout_s=cfg.llm_timeout_s,
        base_url=cfg.rag_embed_base_url or cfg.llm_base_url,
        allow_remote=cfg.llm_allow_remote,
    )
