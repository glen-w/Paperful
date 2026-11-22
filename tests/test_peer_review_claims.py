"""Intra-doc claims lane: overlap bind and ledger."""

from __future__ import annotations

from paperful.config import Config
from paperful.peer_review_claims import (
    attach_claim_sources,
    bind_claim,
    cites_in_window,
    content_words,
    numbered_bibliography,
    quote_in_text,
    suggested_from_claims,
)
from paperful.peer_review_units import Unit, family_of, units_from_doc
from paperful.peer_review_extract import ExtractedDoc
from paperful.store import write_json
from paperful.zot import Item


def test_bind_claim_supported_thin_unsupported():
    support = [
        Unit(
            heading="Results",
            loc="paragraph 3",
            text="Yield rose 47.2 percent under the ABC protocol compared with the control.",
        ),
        Unit(
            heading="Methods",
            loc="paragraph 2",
            text="The ABC protocol was applied to 40 plots.",
        ),
    ]
    ok = bind_claim("Yield rose 47.2 percent under the ABC protocol.", support)
    assert ok["status"] == "supported"
    assert "ABC protocol" in ok["support_quote"]
    thin = bind_claim("The ABC protocol was applied.", support)
    assert thin["status"] in {"supported", "thin"}
    miss = bind_claim("The protocol works on every continent.", support)
    assert miss["status"] == "unsupported"
    assert miss["support_quote"] == "" or miss["score"] < 0.35


def test_content_words_drops_short_and_stop():
    words = content_words("The study with their yield")
    assert "study" not in words
    assert "with" not in words
    assert "their" not in words
    assert "yield" in words


def test_claims_empty_extract_skips():
    cfg = Config()
    doc = ExtractedDoc(text="", format="md")
    extra, meta = suggested_from_claims(
        cfg, doc, [], item=None, client=object(), hay=""
    )
    assert extra == []
    assert meta["skipped"] == "empty_extract"
    assert meta["ledger"] == []


def test_claims_llm_error_records_skip(monkeypatch):
    cfg = Config()
    doc = ExtractedDoc(
        text="Abstract\n\nYield rose 47.2 percent under the ABC protocol.\n",
        format="md",
        paragraphs=["Abstract", "Yield rose 47.2 percent under the ABC protocol."],
        loc_kind="paragraph",
    )

    def boom(*_a, **_k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr("paperful.llm.client.chat", boom)
    extra, meta = suggested_from_claims(
        cfg, doc, [], item=None, client=object(), hay=doc.text.lower()
    )
    assert meta["skipped"] == "llm_error"
    assert any(f.code == "llm_failed" for f in extra)


def _item(**overrides) -> Item:
    base = dict(
        key="LIB1",
        item_type="journalArticle",
        title="ABC protocol yields",
        doi="10.1000/abc",
        arxiv_id=None,
        url=None,
        year=2020,
        first_author="Smith",
    )
    base.update(overrides)
    return Item(**base)


def test_numbered_bibliography_and_window_cites():
    text = (
        "Results\n\nYield rose 47.2 percent under the ABC protocol [1].\n\n"
        "References\n\n"
        "[1] Smith, A. (2020). ABC protocol yields. https://doi.org/10.1000/abc\n"
    )
    by_num = numbered_bibliography(text)
    assert 1 in by_num
    assert "10.1000/abc" in (by_num[1].get("doi") or "")
    cites = cites_in_window("Yield rose 47.2 percent under the ABC protocol [1].")
    assert cites == [{"kind": "num", "n": 1}]


def test_attach_claim_sources_locator_quote_in_page(tmp_path):
    cfg = Config(state_dir=tmp_path / "state", out_dir=tmp_path / "out")
    cfg.state_dir.mkdir(parents=True)
    page = (
        "Yield rose 47.2 percent under the ABC protocol compared with the control "
        "across forty field plots in the trial."
    )
    write_json(
        cfg.rag_dir / "text" / "LIB1.json",
        {"pages": [page, "Unrelated methods leftover."]},
    )
    doc = ExtractedDoc(
        text=(
            "Results\n\nYield rose 47.2 percent under the ABC protocol [1].\n\n"
            "References\n\n"
            "[1] Smith, A. (2020). ABC protocol yields. https://doi.org/10.1000/abc\n"
        ),
        format="md",
    )
    ledger = [
        {
            "id": "c1",
            "text": "Yield rose 47.2 percent under the ABC protocol.",
            "status": "supported",
            "support_quote": "Yield rose 47.2 percent under the ABC protocol [1].",
            "loc": "paragraph 2",
        }
    ]
    extra = []
    skip = attach_claim_sources(
        ledger, doc, cfg, [_item()], extra=extra, comment_cap=16
    )
    assert skip == ""
    src = ledger[0]["sources"][0]
    assert src["item_key"] == "LIB1"
    assert src["status"] == "supported"
    assert src["quote"]
    assert quote_in_text(src["quote"], page)
    assert extra == []


def test_attach_claim_sources_loads_only_scope_keys(tmp_path, monkeypatch):
    cfg = Config(state_dir=tmp_path / "state", out_dir=tmp_path / "out")
    cfg.state_dir.mkdir(parents=True)
    doc = ExtractedDoc(
        text="Results\n\nA claim [1].\n\nReferences\n\n[1] Smith, A. (2020). https://doi.org/10.1000/abc\n",
        format="md",
    )
    ledger = [{"id": "c1", "text": "A claim", "status": "unsupported"}]
    seen: dict[str, object] = {}

    def fake_load(_cfg, *, exclude_key="", keys=None):
        seen["exclude_key"] = exclude_key
        seen["keys"] = None if keys is None else list(keys)
        return {}

    monkeypatch.setattr("paperful.peer_review_overlap.load_library_pages", fake_load)
    attach_claim_sources(ledger, doc, cfg, [_item()], extra=[], comment_cap=8)
    assert seen["keys"] == ["LIB1"]


def test_attach_claim_sources_no_scope_skips():
    cfg = Config()
    doc = ExtractedDoc(text="A claim [1].\n\nReferences\n\n[1] X.", format="md")
    ledger = [{"id": "c1", "text": "A claim", "status": "unsupported"}]
    extra = []
    skip = attach_claim_sources(ledger, doc, cfg, [], extra=extra, comment_cap=8)
    assert skip == "no_scope"
    assert "sources" not in ledger[0]
    assert extra == []


def test_attach_claim_sources_no_text_not_unsupported(tmp_path):
    cfg = Config(state_dir=tmp_path / "state", out_dir=tmp_path / "out")
    cfg.state_dir.mkdir(parents=True)
    doc = ExtractedDoc(
        text=(
            "Results\n\nYield rose 47.2 percent under the ABC protocol [1].\n\n"
            "References\n\n"
            "[1] Smith, A. (2020). ABC protocol yields. https://doi.org/10.1000/abc\n"
        ),
        format="md",
    )
    ledger = [
        {
            "id": "c1",
            "text": "Yield rose 47.2 percent under the ABC protocol.",
            "status": "thin",
            "loc": "",
        }
    ]
    extra = []
    attach_claim_sources(ledger, doc, cfg, [_item()], extra=extra, comment_cap=8)
    assert ledger[0]["source_status"] == "no_text"
    codes = {f.code for f in extra}
    assert "claim_cite_no_text" in codes
    assert "claim_source_unsupported" not in codes


def test_attach_claim_sources_unrelated_page_is_unsupported(tmp_path):
    cfg = Config(state_dir=tmp_path / "state", out_dir=tmp_path / "out")
    cfg.state_dir.mkdir(parents=True)
    write_json(
        cfg.rag_dir / "text" / "LIB1.json",
        {"pages": ["The committee discussed catering and parking."]},
    )
    doc = ExtractedDoc(
        text=(
            "Results\n\nYield rose 47.2 percent under the ABC protocol [1].\n\n"
            "References\n\n"
            "[1] Smith, A. (2020). ABC protocol yields. https://doi.org/10.1000/abc\n"
        ),
        format="md",
    )
    ledger = [
        {
            "id": "c1",
            "text": "Yield rose 47.2 percent under the ABC protocol.",
            "status": "thin",
            "loc": "",
        }
    ]
    extra = []
    attach_claim_sources(ledger, doc, cfg, [_item()], extra=extra, comment_cap=8)
    assert ledger[0]["source_status"] == "unsupported"
    codes = {f.code for f in extra}
    assert "claim_source_unsupported" in codes
    assert "claim_cite_no_text" not in codes


def test_units_map_canonical_families():
    doc = ExtractedDoc(
        text="Abstract\nHello.\n\nMethods\nWe measured yield.\n",
        format="md",
        paragraphs=["Abstract", "Hello.", "Methods", "We measured yield."],
        loc_kind="paragraph",
    )
    units = units_from_doc(doc)
    families = {family_of(u) for u in units}
    assert "abstract" in families
    assert "methodology" in families
