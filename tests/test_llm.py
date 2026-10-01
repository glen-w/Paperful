"""LLM client and validation (offline)."""

from __future__ import annotations

import json
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
from paperful.llm.client import (
    ChatRequest,
    LiteLLMClient,
    LLMClientError,
    NullLLMClient,
    _parse_json_object,
    chat,
)
from paperful.llm.preflight import validate_llm_for_recover, validate_llm_for_verb
from paperful.llm.validate import (
    LlmConfigError,
    reject_litellm_ollama_model,
    validate_llm_api_base,
    validate_ollama_url,
)


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
        assert '"stream": true' in body or '"stream":true' in body
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


def test_ctx_tokens_for_rounds_and_caps():
    from paperful.llm import ctx_tokens_for

    assert ctx_tokens_for("x" * 3, max_num_ctx=32768) == 3072
    assert ctx_tokens_for("x" * 100_000, max_num_ctx=4096) == 4096


def test_ollama_sends_num_ctx(mock_ollama):
    reqs = mock_ollama(lambda r: httpx.Response(200, json={"response": "ok"}))
    from paperful.llm import CompletionRequest

    OllamaClient("http://127.0.0.1:11434", False).complete(
        CompletionRequest(model="m", prompt="p", num_ctx=8192)
    )
    import json as _json

    assert _json.loads(reqs[0].read())["options"]["num_ctx"] == 8192


def test_ollama_complete_joins_stream_and_skips_thinking(mock_ollama):
    body = "\n".join(
        [
            '{"response":"","thinking":"plan the summary","done":false}',
            '{"response":"<p>Hi","done":false}',
            '{"response":"</p>","done":true}',
        ]
    )
    seen: dict[str, str] = {}

    def handler(r):
        seen["body"] = r.read().decode()
        return httpx.Response(200, text=body)

    mock_ollama(handler)
    from paperful.llm import CompletionRequest

    text = OllamaClient("http://127.0.0.1:11434", False).complete(
        CompletionRequest(model="m", prompt="p")
    )
    assert text == "<p>Hi</p>"
    assert '"stream": true' in seen["body"] or '"stream":true' in seen["body"]
    assert "plan the summary" not in text


def test_ollama_timeout_is_llm_client_error(mock_ollama):
    def boom(r):
        raise httpx.ReadTimeout("timed out")

    mock_ollama(boom)
    from paperful.llm import CompletionRequest

    with pytest.raises(LLMClientError, match="timed out after 300s"):
        OllamaClient("http://127.0.0.1:11434", False).complete(
            CompletionRequest(model="m", prompt="p", timeout_seconds=300)
        )


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


def test_litellm_complete_wraps_transport_errors(monkeypatch):
    def completion(**kw):
        raise TimeoutError("timed out")

    monkeypatch.setitem(
        sys.modules, "litellm", types.SimpleNamespace(completion=completion)
    )
    from paperful.llm import CompletionRequest

    with pytest.raises(LLMClientError, match="timed out"):
        LiteLLMClient(api_base=None).complete(CompletionRequest(model="m", prompt="p"))


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


# ---- chat (messages, streamed) -----------------------------------------------


def _chat_request(**kw) -> ChatRequest:
    messages = (
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hi"},
    )
    return ChatRequest(model="qwen2.5:7b", messages=messages, **kw)


def test_ollama_chat_stream_yields_content_and_skips_thinking(mock_ollama):
    lines = [
        {"message": {"role": "assistant", "content": "", "thinking": "hmm"}},
        {"message": {"role": "assistant", "content": "Hel"}},
        {"message": {"role": "assistant", "content": "lo"}},
        {"message": {"role": "assistant", "content": ""}, "done": True},
    ]
    body = "\n".join(json.dumps(line) for line in lines)
    requests = mock_ollama(lambda req: httpx.Response(200, text=body))
    client = OllamaClient(base_url="http://127.0.0.1:11434/v1", allow_remote=False)
    pieces = list(client.chat_stream(_chat_request(num_ctx=4096, max_tokens=50)))
    assert pieces == ["Hel", "lo"]
    sent = json.loads(requests[0].content)
    assert requests[0].url.path == "/api/chat"
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]
    assert sent["stream"] is True
    assert sent["options"] == {"temperature": 0.2, "num_predict": 50, "num_ctx": 4096}


def test_ollama_chat_stream_raises_on_error_line(mock_ollama):
    body = json.dumps({"message": {"content": "par"}}) + "\n" + json.dumps(
        {"error": "model crashed"}
    )
    mock_ollama(lambda req: httpx.Response(200, text=body))
    client = OllamaClient(base_url="http://127.0.0.1:11434", allow_remote=False)
    with pytest.raises(LLMClientError, match="model crashed"):
        chat(client, _chat_request())


def test_ollama_chat_stream_http_error(mock_ollama):
    mock_ollama(lambda req: httpx.Response(500, text="boom"))
    client = OllamaClient(base_url="http://127.0.0.1:11434", allow_remote=False)
    with pytest.raises(LLMClientError, match="Ollama request failed"):
        chat(client, _chat_request())


def test_litellm_chat_stream_reads_deltas(monkeypatch):
    seen = {}

    def completion(**kwargs):
        seen.update(kwargs)

        def chunk(text):
            delta = types.SimpleNamespace(content=text)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)])

        return iter([chunk("a"), types.SimpleNamespace(choices=[]), chunk(None), chunk("b")])

    monkeypatch.setitem(
        sys.modules, "litellm", types.SimpleNamespace(completion=completion)
    )
    client = LiteLLMClient(api_base="https://llm.example/v1")
    assert chat(client, _chat_request(max_tokens=9)) == "ab"
    assert seen["stream"] is True and seen["max_tokens"] == 9
    assert seen["api_base"] == "https://llm.example/v1"
    assert seen["messages"][0] == {"role": "system", "content": "be brief"}


def test_litellm_chat_stream_wraps_errors(monkeypatch):
    def completion(**kwargs):
        raise RuntimeError("rate limited")

    monkeypatch.setitem(
        sys.modules, "litellm", types.SimpleNamespace(completion=completion)
    )
    with pytest.raises(LLMClientError, match="rate limited"):
        chat(LiteLLMClient(api_base=None), _chat_request())


def test_null_client_chat_is_disabled():
    with pytest.raises(LLMClientError, match="disabled"):
        chat(NullLLMClient(), _chat_request())


def test_preflight_ask_uses_rag_model(cfg, mock_ollama):
    from paperful.llm.preflight import validate_llm_for_ask

    cfg.llm_enabled = True
    cfg.rag_model = "qwen3:8b"
    mock_ollama(
        lambda req: httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]})
    )
    assert validate_llm_for_ask(cfg) == "qwen3:8b"
    cfg.llm_enabled = False
    with pytest.raises(LlmConfigError, match="llm.enabled"):
        validate_llm_for_ask(cfg)
