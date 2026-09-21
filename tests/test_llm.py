"""LLM client and validation (offline)."""

from __future__ import annotations

import sys
import types

import httpx
import pytest

from paperful.llm import (
    OllamaClient,
    get_client,
    llm_egress_is_remote,
    llm_model_for_agent,
)
from paperful.llm.client import LiteLLMClient, LLMClientError, _parse_json_object
from paperful.llm.preflight import validate_llm_for_recover, validate_llm_for_verb
from paperful.llm.validate import (
    LlmConfigError,
    reject_litellm_ollama_model,
    validate_llm_api_base,
    validate_ollama_url,
)


@pytest.fixture
def mock_ollama(monkeypatch):
    """Route every httpx.Client created inside paperful.llm.client through a handler."""
    import paperful.llm.client as mod

    state = {"handler": None, "requests": []}
    orig = httpx.Client

    class _Client(orig):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(state["handler"])
            super().__init__(*a, **kw)

    monkeypatch.setattr(mod.httpx, "Client", _Client)

    def install(handler):
        def wrapped(req):
            state["requests"].append(req)
            return handler(req)

        state["handler"] = wrapped
        return state["requests"]

    return install


# ---- validation --------------------------------------------------------------


def test_validate_ollama_rejects_remote_by_default():
    with pytest.raises(LlmConfigError):
        validate_ollama_url("http://192.168.1.1:11434", False)


def test_validate_ollama_allows_remote_when_opted_in():
    validate_ollama_url("http://192.168.1.1:11434", True)


@pytest.mark.parametrize("url", ["ftp://localhost", "localhost:11434", "http://"])
def test_validate_ollama_bad_urls(url):
    with pytest.raises(LlmConfigError):
        validate_ollama_url(url, True)


def test_reject_litellm_ollama_model():
    with pytest.raises(LlmConfigError):
        reject_litellm_ollama_model("ollama/qwen2.5:7b")
    reject_litellm_ollama_model("openai/gpt-4.1-mini")


def test_validate_api_base():
    validate_llm_api_base("")
    validate_llm_api_base("https://api.example/v1")
    with pytest.raises(LlmConfigError):
        validate_llm_api_base("api.example/v1")


def test_egress_detection(cfg):
    cfg.llm_enabled = True
    assert not llm_egress_is_remote(cfg)
    cfg.llm_provider = "litellm"
    assert llm_egress_is_remote(cfg)
    cfg.llm_provider = "ollama"
    cfg.llm_allow_remote = True
    assert llm_egress_is_remote(cfg)
    cfg.llm_enabled = False
    assert not llm_egress_is_remote(cfg)


def test_agent_model_override(cfg):
    assert llm_model_for_agent(cfg) == cfg.llm_model
    cfg.browser_agent_model = " big:14b "
    assert llm_model_for_agent(cfg) == "big:14b"


# ---- factory -----------------------------------------------------------------


def test_get_client_null_when_disabled(cfg):
    cfg.llm_enabled = False
    assert get_client(cfg).provider == "null"
    with pytest.raises(LLMClientError):
        get_client(cfg).complete(None)


def test_get_client_by_provider(cfg):
    cfg.llm_enabled = True
    assert isinstance(get_client(cfg), OllamaClient)
    cfg.llm_provider = "litellm"
    assert isinstance(get_client(cfg), LiteLLMClient)


# ---- Ollama transport --------------------------------------------------------


def test_ollama_check_config_ok(mock_ollama):
    mock_ollama(
        lambda r: httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}]})
    )
    ok, msg = OllamaClient("http://127.0.0.1:11434", False).check_config("qwen2.5:7b")
    assert ok and msg == "ok"


def test_ollama_check_config_missing_model(mock_ollama):
    mock_ollama(lambda r: httpx.Response(200, json={"models": [{"name": "llama3:8b"}]}))
    ok, msg = OllamaClient("http://127.0.0.1:11434", False).check_config("qwen2.5:7b")
    assert not ok and "not in Ollama tags" in msg


def test_ollama_check_config_unreachable(mock_ollama):
    def boom(r):
        raise httpx.ConnectError("refused")

    mock_ollama(boom)
    ok, msg = OllamaClient("http://127.0.0.1:11434", False).check_config("x")
    assert not ok and "unreachable" in msg


def test_ollama_strips_v1_suffix(mock_ollama):
    reqs = mock_ollama(lambda r: httpx.Response(200, json={"models": []}))
    OllamaClient("http://127.0.0.1:11434/v1", False).check_config("x")
    assert reqs[0].url.path == "/api/tags"


def test_ollama_complete_and_json(mock_ollama):
    def handler(r):
        body = r.read().decode()
        assert '"stream": false' in body or '"stream":false' in body
        return httpx.Response(200, json={"response": '{"title": "Clean"}'})

    reqs = mock_ollama(handler)
    client = OllamaClient("http://127.0.0.1:11434", False)
    from paperful.llm import CompletionRequest

    req = CompletionRequest(model="m", prompt="p", max_tokens=50)
    assert client.complete(req) == '{"title": "Clean"}'
    assert client.complete_json(req) == {"title": "Clean"}
    import json as _json

    payload = _json.loads(reqs[1].read())
    assert payload["options"]["format"] == "json"
    assert payload["options"]["num_predict"] == 50


def test_ollama_error_payload(mock_ollama):
    mock_ollama(lambda r: httpx.Response(200, json={"error": "model not found"}))
    from paperful.llm import CompletionRequest

    with pytest.raises(LLMClientError):
        OllamaClient("http://127.0.0.1:11434", False).complete(
            CompletionRequest(model="m", prompt="p")
        )


def test_ollama_complete_refuses_remote_without_flag():
    from paperful.llm import CompletionRequest

    with pytest.raises(LlmConfigError):
        OllamaClient("http://10.0.0.5:11434", False).complete(
            CompletionRequest(model="m", prompt="p")
        )


@pytest.mark.parametrize("text", ["", "not json", "[1,2]"])
def test_parse_json_object_rejects(text):
    with pytest.raises(LLMClientError):
        _parse_json_object(text)


# ---- LiteLLM (import-gated) --------------------------------------------------


def test_litellm_missing_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)
    ok, msg = LiteLLMClient(api_base=None).check_config("gpt")
    assert not ok and "paperful[llm]" in msg
    from paperful.llm import CompletionRequest
    from paperful.llm.validate import LlmExtraMissingError

    with pytest.raises(LlmExtraMissingError):
        LiteLLMClient(api_base=None).complete(CompletionRequest(model="m", prompt="p"))


def test_litellm_complete_with_fake_module(monkeypatch):
    calls = {}

    def completion(**kw):
        calls.update(kw)
        msg = types.SimpleNamespace(content='{"ok": true}')
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    monkeypatch.setitem(
        sys.modules, "litellm", types.SimpleNamespace(completion=completion)
    )
    from paperful.llm import CompletionRequest

    client = LiteLLMClient(api_base="https://proxy.example/v1")
    assert client.check_config("gpt") == (True, "ok")
    out = client.complete_json(
        CompletionRequest(model="gpt", prompt="hi", max_tokens=9)
    )
    assert out == {"ok": True}
    assert calls["api_base"] == "https://proxy.example/v1"
    assert calls["response_format"] == {"type": "json_object"}
    assert calls["max_tokens"] == 9


# ---- preflight ---------------------------------------------------------------


def test_preflight_disabled(cfg):
    with pytest.raises(LlmConfigError, match="enabled"):
        validate_llm_for_verb(cfg)


def test_preflight_empty_model(cfg):
    cfg.llm_enabled = True
    cfg.llm_model = ""
    with pytest.raises(LlmConfigError, match="model"):
        validate_llm_for_verb(cfg)


def test_preflight_ollama_ok(cfg, mock_ollama):
    cfg.llm_enabled = True
    mock_ollama(
        lambda r: httpx.Response(200, json={"models": [{"name": cfg.llm_model}]})
    )
    assert validate_llm_for_verb(cfg) == cfg.llm_model


def test_preflight_ollama_unreachable_is_config_error(cfg, mock_ollama):
    cfg.llm_enabled = True

    def boom(r):
        raise httpx.ConnectError("refused")

    mock_ollama(boom)
    with pytest.raises(LlmConfigError, match="unreachable"):
        validate_llm_for_verb(cfg)


def test_preflight_litellm_rejects_ollama_prefix(cfg):
    cfg.llm_enabled = True
    cfg.llm_provider = "litellm"
    cfg.llm_model = "ollama/qwen"
    with pytest.raises(LlmConfigError):
        validate_llm_for_verb(cfg)


def test_preflight_recover_rejects_ollama_prefixed_agent_model(cfg, monkeypatch):
    cfg.llm_enabled = True
    cfg.llm_provider = "litellm"
    cfg.llm_model = "openai/gpt"
    cfg.browser_agent_model = "ollama/big"
    monkeypatch.setitem(
        sys.modules, "litellm", types.SimpleNamespace(completion=lambda **k: None)
    )
    with pytest.raises(LlmConfigError, match="browser_agent"):
        validate_llm_for_recover(cfg)
