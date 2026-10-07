"""Discover snowball form parsing."""

from __future__ import annotations

from paperful.ui.snowball_form import parse_discover_topic


def test_simple_mode_is_search_only():
    payload = parse_discover_topic({"query": "BBNJ", "kind": "doi", "seeds": "10.1/x"}, advanced=False)
    assert payload.kind == "search"
    assert payload.seeds == []


def test_advanced_parses_kind_and_seeds():
    payload = parse_discover_topic(
        {"kind": "doi", "seeds": "10.1/a\n10.2/b", "direction": "cites"},
        advanced=True,
    )
    assert payload.kind == "doi"
    assert payload.seeds == ["10.1/a", "10.2/b"]
    assert payload.direction == "cites"


def test_advanced_parses_crawl_knobs():
    payload = parse_discover_topic(
        {
            "kind": "search",
            "query": "BBNJ",
            "per_hop_rank": "most-cited",
            "fetch_pdfs": "fast",
            "twenty_writeback": "1",
            "languages": "en,fr",
        },
        advanced=True,
    )
    assert payload.per_hop_rank == "most-cited"
    assert payload.fetch_pdfs == "fast"
    assert payload.twenty_writeback is True
    assert payload.languages == ("en", "fr")
