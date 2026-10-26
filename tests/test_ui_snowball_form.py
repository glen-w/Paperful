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


def test_advanced_parses_map_categories_and_study_designs():
    payload = parse_discover_topic(
        {
            "kind": "search",
            "query": "GLP-1",
            "study_designs": "rct, meta-analysis",
            "map_categories": "trials, evidence-synthesis",
        },
        advanced=True,
    )
    assert payload.study_designs == ("randomized-controlled-trial", "meta-analysis")
    assert payload.map_categories == ("trials", "evidence-synthesis")


def test_compose_query_and_lists(cfg):
    import pytest

    from paperful.snowball.command import SnowballError
    from paperful.ui.snowball_form import (
        compose_query,
        doi_list,
        orcid_list,
        parse_discover_topic,
        profile_body_from_payload,
    )

    search = parse_discover_topic({"query": "krill diet", "or_mode": "1"}, advanced=True)
    assert "krill" in compose_query(search).lower() or compose_query(search)
    seeded = parse_discover_topic(
        {"kind": "search", "seeds": "ocean treaty"}, advanced=True
    )
    assert compose_query(seeded)
    empty = parse_discover_topic({"kind": "search"}, advanced=True)
    assert compose_query(empty) == ""

    doi = parse_discover_topic(
        {"kind": "doi", "query": "10.1000/abc", "seeds": "10.1000/def"},
        advanced=True,
    )
    dois = doi_list(doi)
    assert "10.1000/abc" in dois or "10.1000/def" in dois
    with pytest.raises(SnowballError):
        doi_list(parse_discover_topic({"kind": "doi"}, advanced=True))

    orcid = parse_discover_topic(
        {"kind": "orcid", "query": "0000-0002-1825-0097"},
        advanced=True,
    )
    assert orcid_list(orcid)
    with pytest.raises(SnowballError):
        orcid_list(parse_discover_topic({"kind": "orcid"}, advanced=True))

    hybrid = parse_discover_topic(
        {
            "kind": "hybrid",
            "query": "BBNJ",
            "or_mode": "1",
            "tags": "grey,oa",
            "backends": "openalex",
            "refine": "1",
            "note_provenance": "1",
            "author_site_preflight": "1",
            "min_seed_citations": "3",
            "stop_rule": "saturation",
            "stop_eps": "0.1",
            "stop_k": "2",
            "stop_max_screened": "10",
            "languages": "en",
            "study_designs": "rct",
            "map_categories": "trials",
        },
        advanced=True,
    )
    body = profile_body_from_payload(hybrid, collection="BBNJ")
    assert body["hybrid"] is True
    assert body["or"] is True
    assert body["refine"] is True
    assert body["tag"] == ["grey", "oa"]

    coll = parse_discover_topic({"kind": "collection", "seeds": "Other"}, advanced=True)
    body2 = profile_body_from_payload(coll, collection="")
    assert body2["seed_collection"] == "Other"

    doi_body = profile_body_from_payload(doi, collection="BBNJ")
    assert "doi" in doi_body
    orcid_body = profile_body_from_payload(orcid, collection="BBNJ")
    assert "orcid" in orcid_body
