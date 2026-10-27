"""Intra-doc claims lane: overlap bind and ledger."""

from __future__ import annotations

from paperful.config import Config
from paperful.critique_claims import bind_claim, content_words, suggested_from_claims
from paperful.critique_units import Unit, family_of, units_from_doc
from paperful.critique_extract import ExtractedDoc


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
