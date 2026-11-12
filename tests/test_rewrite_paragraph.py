"""Whole-paragraph LLM returns (fake client)."""

from __future__ import annotations

import json

from paperful.rewrite import build_rewrite
from paperful.rewrite_llm import paragraph_span
from tests.test_rewrite import _finding, _pack


class _ParaClient:
    def __init__(self, paragraph: str) -> None:
        self.paragraph = paragraph
        self.calls = 0

    def chat_stream(self, request):
        self.calls += 1
        payload = {
            "edits": [
                {
                    "finding_id": "a",
                    "kind": "replace",
                    "paragraph": self.paragraph,
                    "needs_author": False,
                }
            ]
        }
        yield json.dumps(payload)


def test_paragraph_span_keeps_unflagged_prefix():
    source = "Alpha stays. Bravo is too long and must shrink now."
    target = "Alpha stays. Bravo is shorter."
    diff = paragraph_span(source, target)
    assert diff is not None
    quote, replacement, start, _end = diff
    assert "Alpha stays." in source[: start + 1]
    assert "too long" in quote
    assert "shorter" in replacement


def test_two_findings_one_paragraph_one_call(cfg, tmp_path):
    para = (
        "Alpha stays put in this sentence. "
        "This is a very long sentence that goes on and on without a pause so that the prose checker can flag it."
    )
    rewritten = (
        "Alpha stays put in this sentence. "
        "This is shorter."
    )
    src = tmp_path / "draft.md"
    src.write_text(para + "\n", encoding="utf-8")
    f1 = _finding(
        code="long_sentence",
        quote="This is a very long sentence that goes on and on without a pause so that the prose checker can flag it.",
        extra={},
        loc="paragraph 1",
    )
    f2 = _finding(
        code="long_sentence",
        quote="Alpha stays put in this sentence",
        extra={},
        loc="paragraph 1",
    )
    f2["id"] = "f-alpha"
    pack = _pack([f1, f2], path=str(src))
    client = _ParaClient(rewritten)
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
    edits = (result.get("plan") or {}).get("edits") or []
    assert client.calls == 1
    assert len(edits) == 1
    assert edits[0]["target_paragraph"] == rewritten
    assert edits[0]["source_paragraph"] == para
    assert "Alpha stays put in this sentence." in edits[0]["target_paragraph"]
