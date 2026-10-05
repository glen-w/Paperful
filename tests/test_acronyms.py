"""Acronym harvest and Title Case allowlist. No network."""

from __future__ import annotations

import json

from paperful.acronyms import (
    harvest,
    load_acronym_allowlist,
    tokens_in,
    write_allowlist,
)
from paperful.lint import normalize_saved_title, title_to_title_case
from paperful.metadata import propose_patch
from tests.conftest import make_item


def test_tokens_skip_uniform_text_and_roman_numerals():
    assert tokens_in("THE BBNJ AGREEMENT") == set()
    assert tokens_in("the bbnj agreement") == set()
    assert "BBNJ" in tokens_in("The BBNJ Agreement and FAO guidance")
    assert "FAO" in tokens_in("The BBNJ Agreement and FAO guidance")
    assert "III" not in tokens_in("Chapter III of the BBNJ text")
    assert "AND" not in tokens_in("Fish AND chips in the FAO report")


def test_harvest_needs_repeats_and_a_higher_bar_for_long_tokens():
    items = [
        make_item(
            key="A",
            title="The BBNJ Agreement and the FAO report",
            abstract="AGREEMENT text about BBNJ.",
            publication_title="FAO Fisheries",
        ),
        make_item(
            key="B",
            title="FAO notes on the BBNJ text",
            abstract="Still the AGREEMENT in mixed case? AGREEMENT here.",
            publication_title="Ocean",
        ),
    ]
    # AGREEMENT is 9 letters and appears in two items, below the length bar.
    tokens = {row.token: row.count for row in harvest(items, min_count=2)}
    assert tokens == {"BBNJ": 2, "FAO": 2}


def test_allowlist_round_trip_keeps_extra_and_title_case(cfg):
    items = [
        make_item(key="A", title="The BBNJ Agreement"),
        make_item(key="B", title="Another BBNJ note"),
    ]
    path = write_allowlist(
        cfg.state_dir,
        "bbnj",
        scope="BBNJ",
        rows=harvest(items),
        min_count=2,
        n_items=2,
    )
    body = json.loads(path.read_text(encoding="utf-8"))
    body["extra"] = ["RFMO"]
    path.write_text(json.dumps(body), encoding="utf-8")
    again = write_allowlist(
        cfg.state_dir,
        "bbnj",
        scope="BBNJ",
        rows=harvest(items),
        min_count=2,
        n_items=2,
    )
    saved = json.loads(again.read_text(encoding="utf-8"))
    assert saved["schema"] == "paperful.acronyms.v1"
    assert saved["extra"] == ["RFMO"]
    allowed = load_acronym_allowlist(cfg.state_dir)
    assert allowed == frozenset({"BBNJ", "RFMO"})
    assert (
        title_to_title_case("THE BBNJ AGREEMENT AND RFMO RULES", allowed)
        == "The BBNJ Agreement and RFMO Rules"
    )
    assert (
        title_to_title_case("THE BBNJ AGREEMENT AND RFMO RULES")
        == "The Bbnj Agreement and Rfmo Rules"
    )
    assert (
        normalize_saved_title("THE BBNJ AGREEMENT AND RFMO RULES", allowed)
        == "The BBNJ Agreement and RFMO Rules"
    )


def test_fix_metadata_title_case_uses_the_allowlist(cfg):
    from paperful.acronyms import Acronym

    write_allowlist(
        cfg.state_dir,
        "bbnj",
        scope="BBNJ",
        rows=[Acronym("BBNJ", 4), Acronym("FAO", 3)],
        min_count=2,
        n_items=4,
    )
    item = make_item(
        title="THE BBNJ AGREEMENT AND FAO FISHERIES",
        doi=None,
        doi_verified="missing",
    )
    patch = propose_patch(None, cfg, item, [], prepared=True)  # type: ignore[arg-type]
    assert patch is not None
    assert patch.source == "title_case"
    assert patch.after["title"] == "The BBNJ Agreement and FAO Fisheries"
