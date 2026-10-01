"""Embedders and embed preflight (offline)."""

from __future__ import annotations

import json
import math
import sys
import types

import httpx
import pytest

import paperful.llm.embed as embed_mod
from paperful.llm import embed_egress_is_remote, validate_embedder
from paperful.llm.embed import (
    EmbedError,
    LiteLLMEmbedder,
    NullEmbedder,
    OllamaEmbedder,
    embed_fingerprint,
    get_embedder,
    model_base_name,
    task_prefixes,
)
from paperful.llm.validate import LlmConfigError, LlmExtraMissingError


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(embed_mod.time, "sleep", lambda s: None)


def _embed_response(req: httpx.Request) -> httpx.Response:
    texts = json.loads(req.content)["input"]
    return httpx.Response(
        200, json={"embeddings": [[3.0, 4.0, float(len(t))] for t in texts]}
    )


# ---- names and prefixes ------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "base"),
    [
        ("nomic-embed-text", "nomic-embed-text"),
        ("nomic-embed-text:latest", "nomic-embed-text"),
        ("openai/text-embedding-3-small", "text-embedding-3-small"),
        (" BGE-M3:567m ", "bge-m3"),
    ],
)
def test_model_base_name(model, base):
    assert model_base_name(model) == base


def test_task_prefixes_only_for_models_that_need_them():
    assert task_prefixes("nomic-embed-text:latest") == (
        "search_document: ",
        "search_query: ",
    )
    assert task_prefixes("bge-m3") == ("", "")
    assert task_prefixes("openai/text-embedding-3-small") == ("", "")


def test_fingerprint_is_folder_safe_and_ignores_latest_tag():
    assert embed_fingerprint("ollama", "nomic-embed-text") == "ollama__nomic-embed-text"
    assert embed_fingerprint("ollama", "nomic-embed-text:latest") == (
        "ollama__nomic-embed-text"
    )
    assert embed_fingerprint("litellm", "openai/text-embedding-3-small") == (
        "litellm__openai-text-embedding-3-small"
    )
    assert embed_fingerprint("ollama", "bge-m3:567m") == "ollama__bge-m3-567m"


# ---- Ollama ------------------------------------------------------------------


def test_ollama_embeds_in_batches_with_document_prefix(mock_ollama):
    requests = mock_ollama(_embed_response)
    embedder = OllamaEmbedder(model="nomic-embed-text", batch_size=2)
    vectors = embedder.embed_documents(["a", "bb", "ccc"])
    assert len(vectors) == 3 and embedder.dim == 3
    assert [r.url.path for r in requests] == ["/api/embed", "/api/embed"]
    first = json.loads(requests[0].content)
    assert first["model"] == "nomic-embed-text"
    assert first["input"] == ["search_document: a", "search_document: bb"]
    assert json.loads(requests[1].content)["input"] == ["search_document: ccc"]
    for vector in vectors:
        assert math.isclose(sum(x * x for x in vector), 1.0)


def test_ollama_query_uses_query_prefix(mock_ollama):
    requests = mock_ollama(_embed_response)
    OllamaEmbedder(model="nomic-embed-text").embed_query("whales")
    assert json.loads(requests[0].content)["input"] == ["search_query: whales"]


def test_ollama_unprefixed_model_sends_raw_text(mock_ollama):
    requests = mock_ollama(_embed_response)
    OllamaEmbedder(model="bge-m3").embed_documents(["texte"])
    assert json.loads(requests[0].content)["input"] == ["texte"]


def test_ollama_retries_5xx_then_succeeds(mock_ollama):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="loading model")
        return _embed_response(req)

    mock_ollama(handler)
    assert len(OllamaEmbedder(model="bge-m3").embed_documents(["a"])) == 1
    assert calls["n"] == 2


def test_ollama_gives_up_after_three_5xx(mock_ollama):
    requests = mock_ollama(lambda req: httpx.Response(500, text="boom"))
    with pytest.raises(EmbedError, match="HTTP 500"):
        OllamaEmbedder(model="bge-m3").embed_documents(["a"])
    assert len(requests) == 3


def test_ollama_does_not_retry_4xx(mock_ollama):
    requests = mock_ollama(lambda req: httpx.Response(400, text="bad input"))
    with pytest.raises(EmbedError, match="HTTP 400"):
        OllamaEmbedder(model="bge-m3").embed_documents(["a"])
    assert len(requests) == 1


def test_ollama_missing_model_names_the_pull_command(mock_ollama):
    mock_ollama(lambda req: httpx.Response(404, json={"error": "model not found"}))
    with pytest.raises(EmbedError, match="ollama pull bge-m3"):
        OllamaEmbedder(model="bge-m3").embed_documents(["a"])


def test_ollama_timeout_is_not_retried(mock_ollama):
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    requests = mock_ollama(handler)
    with pytest.raises(EmbedError, match="timed out"):
        OllamaEmbedder(model="bge-m3", timeout_s=5).embed_documents(["a"])
    assert len(requests) == 1


def test_ollama_connection_drop_is_retried(mock_ollama):
    def handler(req):
        raise httpx.ConnectError("refused", request=req)

    requests = mock_ollama(handler)
    with pytest.raises(EmbedError, match="unreachable"):
        OllamaEmbedder(model="bge-m3").embed_documents(["a"])
    assert len(requests) == 3


def test_wrong_vector_count_is_an_error(mock_ollama):
    mock_ollama(lambda req: httpx.Response(200, json={"embeddings": [[1.0, 0.0]]}))
    with pytest.raises(EmbedError, match="1 vectors for 2 texts"):
        OllamaEmbedder(model="bge-m3").embed_documents(["a", "b"])


def test_width_change_between_calls_is_an_error(mock_ollama):
    widths = iter([2, 3])

    def handler(req):
        return httpx.Response(200, json={"embeddings": [[1.0] * next(widths)]})

    mock_ollama(handler)
    embedder = OllamaEmbedder(model="bge-m3")
    embedder.embed_query("a")
    with pytest.raises(EmbedError, match="3-dim vector; expected 2"):
        embedder.embed_query("b")


def test_zero_vector_is_an_error(mock_ollama):
    mock_ollama(lambda req: httpx.Response(200, json={"embeddings": [[0.0, 0.0]]}))
    with pytest.raises(EmbedError, match="empty or non-finite"):
        OllamaEmbedder(model="bge-m3").embed_query("a")


def test_ollama_refuses_remote_host_without_flag():
    embedder = OllamaEmbedder(model="bge-m3", base_url="http://10.0.0.5:11434")
    with pytest.raises(LlmConfigError, match="not local"):
        embedder.embed_query("a")


def test_ollama_check_config(mock_ollama):
    mock_ollama(
        lambda req: httpx.Response(
            200, json={"models": [{"name": "nomic-embed-text:latest"}]}
        )
    )
    assert OllamaEmbedder(model="nomic-embed-text").check_config() == (True, "ok")
    ok, msg = OllamaEmbedder(model="bge-m3").check_config()
    assert not ok and "ollama pull bge-m3" in msg


# ---- LiteLLM -----------------------------------------------------------------


def test_litellm_embeds_attribute_and_dict_rows(monkeypatch):
    seen = {}

    def embedding(**kwargs):
        seen.update(kwargs)
        rows = [{"embedding": [1.0, 0.0]}, types.SimpleNamespace(embedding=[0.0, 2.0])]
        return types.SimpleNamespace(data=rows)

    monkeypatch.setitem(
        sys.modules, "litellm", types.SimpleNamespace(embedding=embedding)
    )
    embedder = LiteLLMEmbedder(
        model="openai/text-embedding-3-small", api_base="https://llm.example/v1"
    )
    assert embedder.embed_documents(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert seen["input"] == ["a", "b"] and seen["api_base"] == "https://llm.example/v1"
    assert embedder.check_config() == (True, "ok")


def test_litellm_retries_only_transient_errors(monkeypatch):
    class APIConnectionError(Exception):
        pass

    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise APIConnectionError("reset")
        return {"data": [{"embedding": [1.0]}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(embedding=flaky))
    assert LiteLLMEmbedder(model="m").embed_query("a") == [1.0]
    assert calls["n"] == 2

    def bad_key(**kwargs):
        calls["n"] += 1
        raise ValueError("invalid api key")

    calls["n"] = 0
    monkeypatch.setitem(
        sys.modules, "litellm", types.SimpleNamespace(embedding=bad_key)
    )
    with pytest.raises(EmbedError, match="invalid api key"):
        LiteLLMEmbedder(model="m").embed_query("a")
    assert calls["n"] == 1


def test_litellm_missing_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)
    embedder = LiteLLMEmbedder(model="m")
    ok, msg = embedder.check_config()
    assert not ok and "paperful[llm]" in msg
    with pytest.raises(LlmExtraMissingError):
        embedder.embed_query("a")


# ---- factory and preflight ---------------------------------------------------


def test_get_embedder_by_config(cfg):
    assert isinstance(get_embedder(cfg), NullEmbedder)
    cfg.rag_enabled = True
    cfg.llm_base_url = "http://127.0.0.1:9999"
    ollama = get_embedder(cfg)
    assert isinstance(ollama, OllamaEmbedder)
    assert ollama.base_url == "http://127.0.0.1:9999"
    assert ollama.model == "nomic-embed-text"
    cfg.rag_embed_base_url = "http://localhost:1234"
    assert get_embedder(cfg).base_url == "http://localhost:1234"
    cfg.rag_embed_provider = "litellm"
    cfg.rag_embed_model = "openai/text-embedding-3-small"
    cfg.llm_api_base = "https://llm.example/v1"
    lite = get_embedder(cfg)
    assert isinstance(lite, LiteLLMEmbedder)
    assert lite.api_base == "https://llm.example/v1"


def test_null_embedder_refuses():
    with pytest.raises(EmbedError, match="rag.enabled"):
        NullEmbedder().embed_query("a")


def test_validate_embedder_gates(cfg, mock_ollama):
    with pytest.raises(LlmConfigError, match="rag.enabled is false"):
        validate_embedder(cfg)
    cfg.rag_enabled = True
    mock_ollama(lambda req: httpx.Response(200, json={"models": []}))
    with pytest.raises(LlmConfigError, match="ollama pull nomic-embed-text"):
        validate_embedder(cfg)
    mock_ollama(
        lambda req: httpx.Response(200, json={"models": [{"name": "nomic-embed-text"}]})
    )
    assert validate_embedder(cfg).model == "nomic-embed-text"


def test_validate_embedder_does_not_need_llm_enabled(cfg, mock_ollama):
    cfg.rag_enabled = True
    cfg.llm_enabled = False
    mock_ollama(
        lambda req: httpx.Response(200, json={"models": [{"name": "nomic-embed-text"}]})
    )
    assert validate_embedder(cfg).provider == "ollama"


def test_validate_embedder_rejects_ollama_model_through_litellm(cfg):
    cfg.rag_enabled = True
    cfg.rag_embed_provider = "litellm"
    cfg.rag_embed_model = "ollama/nomic-embed-text"
    with pytest.raises(LlmConfigError, match='rag.embed_provider = "ollama"'):
        validate_embedder(cfg)


def test_embed_egress(cfg):
    assert embed_egress_is_remote(cfg) is False
    cfg.rag_enabled = True
    assert embed_egress_is_remote(cfg) is False
    cfg.rag_embed_base_url = "http://10.0.0.5:11434"
    assert embed_egress_is_remote(cfg) is True
    cfg.rag_embed_base_url = ""
    cfg.rag_embed_provider = "litellm"
    assert embed_egress_is_remote(cfg) is True
