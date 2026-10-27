"""Verify lane: density budget, segments, citation grounding."""

from __future__ import annotations

from paperful.config import Config
from paperful.critique_extract import ExtractedDoc
from paperful.critique_units import Unit
from paperful.critique_verify import (
    density_budget,
    invents_citation,
    merge_segments,
    suggested_from_verify,
)


def test_density_budget_proof_vs_ack():
    proof = (
        "Lemma 1. Let X be a Banach space. Proof. We show complete "
        "contractivity. $T(x)=x$ and \\begin{eq} a=1 \\end{eq}."
    )
    assert density_budget(proof, family="") == "heavy"
    assert density_budget("We thank the funders and colleagues.", family="acknowledgements") == (
        "light"
    )
    methods = "n=40. We measured yield under the ABC protocol. sample size was fixed."
    assert density_budget(methods, family="methodology") in {"medium", "heavy"}


def test_merge_segments_cover_all_units():
    units = [
        Unit(heading="Introduction", loc="paragraph 1", text="Intro body one."),
        Unit(heading="Methods", loc="paragraph 2", text="Methods body two."),
        Unit(heading="Results", loc="paragraph 3", text="Results body three."),
        Unit(heading="Discussion", loc="paragraph 4", text="Discussion body four."),
    ]
    segs = merge_segments(units, max_segments=8)
    joined = " ".join(s.text for s in segs)
    for u in units:
        assert u.text in joined
    assert len(segs) <= 8
    if len(segs) > 1:
        # Overlap one unit between adjacent segments.
        assert segs[0].text.split("\n\n")[-1] in segs[1].text
    capped = merge_segments(units, max_segments=2)
    assert len(capped) <= 2
    joined_c = " ".join(s.text for s in capped)
    for u in units:
        assert u.text in joined_c


def test_invents_citation_drops_unknown_title_and_doi():
    extract = "the abc protocol increased yield. see figure 2."
    biblio = "first paper\n10.1000/missing"
    assert invents_citation(
        'Compare "A Completely Fake Zebra Paper" on yield.',
        extract_hay=extract,
        biblio_hay=biblio,
    )
    assert invents_citation(
        "See 10.9999/not-in-biblio for the ABC protocol.",
        extract_hay=extract,
        biblio_hay=biblio,
    )
    assert not invents_citation(
        "See 10.9999/not-in-biblio for the ABC protocol.",
        extract_hay=extract,
        biblio_hay=biblio,
        cached_dois={"10.9999/not-in-biblio"},
    )
    assert not invents_citation(
        "The ABC protocol increased yield as in First Paper.",
        extract_hay=extract,
        biblio_hay=biblio,
    )


def test_verify_empty_extract_skips():
    cfg = Config()
    doc = ExtractedDoc(text="", format="md")
    extra, meta = suggested_from_verify(
        cfg, doc, [], item=None, client=object(), hay=""
    )
    assert extra == []
    assert meta["skipped"] == "empty_extract"


def test_verify_llm_error_records_skip(monkeypatch):
    cfg = Config()
    doc = ExtractedDoc(
        text="Methods\n\nWe measured yield under the ABC protocol.\n",
        format="md",
        paragraphs=["Methods", "We measured yield under the ABC protocol."],
        loc_kind="paragraph",
    )

    def boom(*_a, **_k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr("paperful.llm.client.chat", boom)
    extra, meta = suggested_from_verify(
        cfg, doc, [], item=None, client=object(), hay=doc.text.lower()
    )
    assert any(s.get("skipped") == "llm_error" for s in meta.get("segments") or [])
    assert any(f.code == "llm_failed" for f in extra)
