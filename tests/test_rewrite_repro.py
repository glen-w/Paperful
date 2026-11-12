"""Rewrite LLM call reproducibility (offline fake client)."""

from __future__ import annotations

from paperful.rewrite import build_rewrite
from paperful.rewrite_areas import RewriteArea
from paperful.rewrite_llm import proposed_from_area
from tests.test_rewrite import DRAFT, _finding, _pack


class _FakeClient:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def chat_stream(self, request):
        self.requests.append(request)
        yield '{"edits":[]}'


def test_proposed_from_area_pins_temp_seed_and_worklog(cfg):
    client = _FakeClient()
    area = RewriteArea(id="style", model="test-model")
    finding = _finding(
        code="long_sentence",
        quote="This is a very long sentence that goes on and on without a pause so that the prose checker can flag it as a long_sentence finding for the style area when a model is available.",
        extra={},
    )
    from paperful.rewrite_align import align_finding

    text = DRAFT
    bound = align_finding(finding, text=text, paragraphs=text.split("\n\n"))
    assert not isinstance(bound, str)
    edits, skips, model, meta = proposed_from_area(
        cfg,
        area=area,
        findings=[finding],
        alignments={finding["id"]: bound},
        excerpt=text,
        client=client,
        timeout_s=5,
    )
    assert model == "test-model"
    assert client.requests
    req = client.requests[0]
    assert req.temperature == 0.0
    assert req.seed == 0
    assert meta.get("prompt_sha")
    assert meta.get("num_ctx")
    assert meta.get("paperful")
    assert edits == []
    assert skips


def test_overlong_prompt_skips_context_overflow(cfg):
    cfg.llm_max_num_ctx = 1024
    client = _FakeClient()
    area = RewriteArea(id="style", model="test-model")
    finding = _finding(code="long_sentence", extra={})
    from paperful.rewrite_align import align_finding

    text = DRAFT + (" word" * 8000)
    bound = align_finding(finding, text=text, paragraphs=[text])
    if isinstance(bound, str):
        finding["quote"] = text[:80]
        bound = align_finding(finding, text=text, paragraphs=[text])
    assert not isinstance(bound, str)
    _edits, skips, _model, meta = proposed_from_area(
        cfg,
        area=area,
        findings=[finding],
        alignments={finding["id"]: bound},
        excerpt=text,
        client=client,
        timeout_s=5,
    )
    assert not client.requests
    assert all(s["reason"] == "context_overflow" for s in skips)
    assert meta.get("prompt_sha")


def test_build_rewrite_worklog_calls(cfg, tmp_path):
    src = tmp_path / "draft.md"
    src.write_text(DRAFT, encoding="utf-8")
    finding = _finding(
        code="long_sentence",
        quote="This is a very long sentence that goes on and on without a pause so that the prose checker can flag it as a long_sentence finding for the style area when a model is available.",
        extra={},
    )
    pack = _pack([finding], path=str(src))
    client = _FakeClient()
    cfg.llm_model = "test-model"
    result = build_rewrite(
        cfg,
        pack=pack,
        manuscript=src,
        areas=("style",),
        outputs=("edits",),
        dry_run=True,
        llm_client=client,
    )
    calls = ((result.get("plan") or {}).get("worklog") or {}).get("calls") or []
    assert calls
    assert calls[0]["temperature"] == 0.0
    assert calls[0]["seed"] == 0
    assert calls[0]["prompt_sha"]
