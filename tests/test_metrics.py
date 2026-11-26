"""Citation metrics refresh: OpenAlex then Crossref, disk cache only."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from paperful.config import Config, load_config
from paperful.metrics import (
    apply_citation_notes,
    cache_path,
    citation_note_html,
    doi_for_item,
    load_cache,
    refresh,
    show_cached,
)
from paperful.snowball.openalex import OpenAlexClient
from tests.conftest import make_item

NOW = datetime(2026, 11, 26, tzinfo=timezone.utc)


def _cfg(tmp_path: Path) -> Config:
    cfg = Config(
        out_dir=tmp_path / "out", state_dir=tmp_path / "state", email="t@example.org"
    )
    cfg.state_dir.mkdir(parents=True)
    return cfg


def _oa(hits: dict[str, int]) -> OpenAlexClient:
    def getter(path: str, params: dict) -> dict:
        filt = str(params.get("filter") or "")
        if path != "/works" or not filt.startswith("doi:"):
            return {"results": []}
        dois = filt[4:].split("|")
        results = []
        for doi in dois:
            if doi in hits:
                results.append(
                    {
                        "id": "https://openalex.org/W" + doi[-1],
                        "doi": "https://doi.org/" + doi,
                        "cited_by_count": hits[doi],
                    }
                )
        return {"results": results}

    return OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)


def test_doi_for_arxiv_item():
    item = make_item(doi=None, arxiv_id="2301.00001")
    assert doi_for_item(item) == "10.48550/arxiv.2301.00001"


def test_openalex_hit_writes_cache(tmp_path: Path):
    cfg = _cfg(tmp_path)
    item = make_item(key="HIT1", doi="10.1000/hit")
    result = refresh(
        cfg,
        [item],
        oa_client=_oa({"10.1000/hit": 12}),
        scope="Col",
        now=NOW,
    )
    assert result["counts"]["fetched"] == 1
    assert result["counts"]["wrote"] == 1
    row = load_cache(cfg)["HIT1"]
    assert row["cited_by_count"] == 12
    assert row["source"] == "openalex"
    assert show_cached(cfg, "HIT1")["cited_by_count"] == 12


def test_arxiv_item_looks_up_openalex_arxiv_doi(tmp_path: Path):
    cfg = _cfg(tmp_path)
    item = make_item(key="AX1", doi=None, arxiv_id="2301.00001")
    doi = "10.48550/arxiv.2301.00001"
    result = refresh(
        cfg,
        [item],
        oa_client=_oa({doi: 4}),
        now=NOW,
    )
    row = result["rows"][0]
    assert row["doi"] == doi
    assert row["cited_by_count"] == 4
    assert row["source"] == "openalex"


def test_crossref_fallback_when_openalex_count_missing(tmp_path: Path):
    cfg = _cfg(tmp_path)
    item = make_item(key="CR2", doi="10.1000/nocount")

    def oa_getter(path: str, params: dict) -> dict:
        return {
            "results": [
                {
                    "id": "https://openalex.org/W9",
                    "doi": "https://doi.org/10.1000/nocount",
                }
            ]
        }

    client = OpenAlexClient(
        email="t@example.org", api_key="", sleep_s=0, getter=oa_getter
    )

    def cr_getter(url: str, params):
        return {"message": {"is-referenced-by-count": 3}}

    row = refresh(cfg, [item], oa_client=client, now=NOW, crossref_getter=cr_getter)[
        "rows"
    ][0]
    assert row["source"] == "crossref"
    assert row["cited_by_count"] == 3
    assert row["openalex_id"] == "https://openalex.org/W9"


def test_crossref_http_error_marks_source_error(tmp_path: Path):
    import httpx

    cfg = _cfg(tmp_path)
    item = make_item(key="ERR1", doi="10.1000/err")

    def cr_getter(url: str, params):
        raise httpx.ConnectError("down")

    result = refresh(
        cfg,
        [item],
        oa_client=_oa({}),
        now=NOW,
        crossref_getter=cr_getter,
    )
    row = result["rows"][0]
    assert row["source"] == "error"
    assert result["counts"]["error"] == 1
    assert "ERR1" not in load_cache(cfg)


def test_openalex_only_sources_skip_crossref(tmp_path: Path):
    cfg = _cfg(tmp_path)
    cfg.metrics_sources = ("openalex",)
    item = make_item(key="OA1", doi="10.1000/miss")

    def boom(url: str, params):
        raise AssertionError("Crossref must not run when sources omit it")

    result = refresh(cfg, [item], oa_client=_oa({}), now=NOW, crossref_getter=boom)
    assert result["rows"][0]["source"] == "unresolved"


def test_crossref_fallback_when_openalex_misses(tmp_path: Path):
    cfg = _cfg(tmp_path)
    item = make_item(key="CR1", doi="10.1000/miss")

    def getter(url: str, params):
        assert "10.1000/miss" in url
        return {"message": {"is-referenced-by-count": 7}}

    result = refresh(
        cfg,
        [item],
        oa_client=_oa({}),
        now=NOW,
        crossref_getter=getter,
    )
    row = result["rows"][0]
    assert row["source"] == "crossref"
    assert row["cited_by_count"] == 7
    assert load_cache(cfg)["CR1"]["cited_by_count"] == 7


def test_unresolved_without_doi(tmp_path: Path):
    cfg = _cfg(tmp_path)
    item = make_item(key="NOID", doi=None, arxiv_id=None)
    result = refresh(cfg, [item], oa_client=_oa({}), now=NOW)
    assert result["counts"]["unresolved"] == 1
    assert result["rows"][0]["source"] == "unresolved"


def test_stale_skip(tmp_path: Path):
    cfg = _cfg(tmp_path)
    cfg.metrics_stale_days = 30
    item = make_item(key="HIT1", doi="10.1000/hit")
    refresh(cfg, [item], oa_client=_oa({"10.1000/hit": 12}), now=NOW)
    later = datetime(2026, 11, 27, tzinfo=timezone.utc)
    result = refresh(
        cfg,
        [item],
        oa_client=_oa({"10.1000/hit": 99}),
        now=later,
        stale_days=30,
    )
    assert result["counts"]["skipped_fresh"] == 1
    assert load_cache(cfg)["HIT1"]["cited_by_count"] == 12


def test_dry_run_does_not_write_cache(tmp_path: Path):
    cfg = _cfg(tmp_path)
    item = make_item(key="HIT1", doi="10.1000/hit")
    result = refresh(
        cfg,
        [item],
        oa_client=_oa({"10.1000/hit": 12}),
        dry_run=True,
        now=NOW,
    )
    assert result["pack"]["wrote"] is False
    assert not cache_path(cfg).is_file()
    assert (result["folder"] / "pack.json").is_file()


def test_offline_does_not_call_openalex(tmp_path: Path):
    cfg = _cfg(tmp_path)
    item = make_item(key="HIT1", doi="10.1000/hit")
    refresh(cfg, [item], oa_client=_oa({"10.1000/hit": 12}), now=NOW)

    def boom(path, params):
        raise AssertionError("OpenAlex must not be called offline")

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=boom)
    result = refresh(cfg, [item], oa_client=client, offline=True, now=NOW)
    assert result["counts"]["skipped_fresh"] == 1
    assert result["counts"]["wrote"] == 0


def test_metrics_sources_from_toml(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(
        'email = "me@example.org"\n\n[metrics]\nstale_days = 7\nsources = ["openalex"]\n',
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.metrics_stale_days == 7
    assert cfg.metrics_sources == ("openalex",)
    bare = Config()
    assert bare.metrics_stale_days == 30
    assert bare.metrics_sources == ("openalex", "crossref")


def test_config_check_flags_google_scholar(tmp_path: Path):
    from paperful.config_check import check_config

    p = tmp_path / "config.toml"
    p.write_text(
        'email = "me@example.org"\n\n[metrics]\nsources = ["google_scholar"]\n',
        encoding="utf-8",
    )
    issues = check_config(p)
    assert any("google_scholar" in row for row in issues)

    p.write_text(
        'email = "me@example.org"\n\n[metrics]\nsources = ["semantic_scholar"]\n',
        encoding="utf-8",
    )
    reserved = check_config(p)
    assert any("semantic_scholar" in row and "reserved" in row for row in reserved)


def test_citation_note_html_first_line_has_count():
    html = citation_note_html(
        {
            "item_key": "HIT1",
            "doi": "10.1000/hit",
            "cited_by_count": 12,
            "source": "openalex",
            "openalex_id": "https://openalex.org/W1",
            "fetched_at": "2026-11-26T00:00:00+00:00",
        },
        run_id="run1",
    )
    assert "Citations: 12 (openalex)" in html
    assert "paperful.note.v1" in html
    assert "10.1000/hit" in html


def test_apply_citation_notes_skips_unresolved_and_writes_hits(tmp_path: Path):
    cfg = _cfg(tmp_path)
    wrote: list[tuple[str, str, str]] = []

    class Backend:
        def create_or_update_note(self, item_key, html, tag):
            wrote.append((item_key, html, tag))
            return "N1"

    rows = [
        {
            "item_key": "HIT1",
            "doi": "10.1000/hit",
            "cited_by_count": 12,
            "source": "openalex",
        },
        {"item_key": "NOPE", "doi": "", "cited_by_count": None, "source": "unresolved"},
        {
            "item_key": "ERR",
            "doi": "10.1000/e",
            "cited_by_count": None,
            "source": "error",
        },
    ]
    counts = apply_citation_notes(Backend(), cfg, rows, run_id="r")
    assert counts == {"notes_wrote": 1, "notes_skipped": 2, "notes_error": 0}
    assert wrote[0][0] == "HIT1"
    assert wrote[0][2] == "paperful-metrics"


def test_note_tag_from_toml(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(
        'email = "me@example.org"\n\n[metrics]\nnote_tag = "cite-count"\n',
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.metrics_note_tag == "cite-count"
