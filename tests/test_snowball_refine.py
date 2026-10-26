"""Optional snowball query suggestions (no live LLM)."""

from __future__ import annotations

from types import SimpleNamespace

from paperful.llm import LLMClientError
from paperful.snowball.refine import llm_suggester, suggestions_for


def test_suggestions_for_empty_and_errors():
    assert suggestions_for("  ", lambda _q: ["x"]) == ([], "no query")
    assert suggestions_for("q", lambda _q: (_ for _ in ()).throw(RuntimeError("boom"))) == (
        [],
        "boom",
    )


def test_suggestions_for_dedupes_and_caps():
    raw = [" A ", "A", "b", "c", "d", "e", "f"]
    out, err = suggestions_for("seed", lambda _q: raw)
    assert err is None
    assert out == ["A", "b", "c", "d", "e"]


def test_llm_suggester_json_and_error(monkeypatch):
    class Client:
        def __init__(self, payload=None, fail=False):
            self.payload = payload
            self.fail = fail

        def complete_json(self, _req):
            if self.fail:
                raise LLMClientError("offline")
            return self.payload

    monkeypatch.setattr("paperful.llm.get_client", lambda _cfg: Client({"queries": ["q1", "q2"]}))
    monkeypatch.setattr("paperful.llm.client.ctx_tokens_for", lambda *_a, **_k: 128)
    cfg = SimpleNamespace(llm_model="stub", llm_max_num_ctx=1024)
    assert llm_suggester(cfg)("krill") == ["q1", "q2"]

    monkeypatch.setattr("paperful.llm.get_client", lambda _cfg: Client("nope"))
    assert llm_suggester(cfg)("krill") == []

    monkeypatch.setattr("paperful.llm.get_client", lambda _cfg: Client(fail=True))
    try:
        llm_suggester(cfg)("krill")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "offline" in str(exc)
