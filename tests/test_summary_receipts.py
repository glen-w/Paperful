"""Opt-in summarize --receipts: quote or drop."""

from __future__ import annotations

import pytest

from paperful import summarize
from paperful.summarize import ReceiptsEmpty, apply_receipts_html, current_prompt_sha
from tests.conftest import make_item
from tests.test_llm_verbs import PDF_TEXT, StubLLM, _ground


@pytest.fixture
def llm_cfg(cfg):
    cfg.llm_enabled = True
    return cfg


def test_receipts_drop_unsupported_and_keep_quote(cfg):
    pages = [(1, PDF_TEXT)]
    html = (
        "<h2>Objective</h2>"
        "<p>Researchers study governance of marine areas beyond national "
        "jurisdiction in the high seas with area based management tools.</p>"
        "<p>The moon is made of cheese and nothing else in this paragraph.</p>"
    )
    out = apply_receipts_html(html, pages, cfg=cfg)
    assert "<h2>Objective</h2>" in out
    assert "governance of marine areas" in out.lower()
    assert "moon is made of cheese" not in out
    assert "<h2>Receipts</h2>" in out
    quote = out.split("“", 1)[-1].split("”", 1)[0]
    assert quote
    assert "governance" in quote.lower() or "marine" in quote.lower()
    from paperful.peer_review_claims import quote_in_text

    assert quote_in_text(quote, PDF_TEXT)


def test_receipts_empty_raises(cfg):
    html = "<p>The moon is made of cheese and green cheese only tonight.</p>"
    try:
        apply_receipts_html(html, [(1, PDF_TEXT)], cfg=cfg)
    except ReceiptsEmpty as exc:
        assert "no quoted span" in str(exc)
    else:
        raise AssertionError("expected ReceiptsEmpty")


def test_receipts_change_prompt_sha(cfg):
    off = current_prompt_sha(cfg)
    cfg.summarize_receipts = True
    on = current_prompt_sha(cfg)
    assert off != on


def test_summarize_items_skips_when_receipts_empty(llm_cfg, monkeypatch):
    _ground(monkeypatch, summarize)
    monkeypatch.setattr(summarize, "pdf_pages_for", lambda *a, **k: [PDF_TEXT])
    llm_cfg.summarize_receipts = True
    monkeypatch.setattr(
        summarize,
        "get_client",
        lambda cfg: StubLLM(
            text="<p>The moon is made of cheese and green cheese only tonight.</p>"
        ),
    )
    item = make_item(has_pdf=True)
    batch = summarize.summarize_items(llm_cfg, [item], None, None, dest="disk")
    assert batch.summarized == 0
    assert batch.skipped == 1
    assert "no quoted span" in batch.rows[0].reason
    assert not (llm_cfg.summaries_dir / f"{item.key}.html").is_file()


def test_summarize_receipts_writes_list(llm_cfg, monkeypatch):
    _ground(monkeypatch, summarize)
    monkeypatch.setattr(summarize, "pdf_pages_for", lambda *a, **k: [PDF_TEXT])
    llm_cfg.summarize_receipts = True
    monkeypatch.setattr(
        summarize,
        "get_client",
        lambda cfg: StubLLM(
            text=(
                "<p>Researchers study governance of marine areas beyond national "
                "jurisdiction in the high seas with area based management tools.</p>"
            )
        ),
    )
    item = make_item(has_pdf=True)
    path = summarize.summarize_item(llm_cfg, item, None, None)
    html = path.read_text(encoding="utf-8")
    assert "<h2>Receipts</h2>" in html
    sha_on = html.split("prompt ")[-1][:8]
    llm_cfg.summarize_receipts = False
    assert sha_on != current_prompt_sha(llm_cfg)
