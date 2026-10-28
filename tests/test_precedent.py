"""Precedent pack: stamps, dedupe, honesty, ingest DOIs."""

from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from paperful.cli import app
from paperful.config import Config, load_config
from paperful.identity import LibraryFingerprint
from paperful.ingest_dois import dois_from_refs_pack
from paperful.precedent import (
    HONESTY_BANNER,
    PRECEDENT_PACK_KEYS,
    SCHEMA,
    PrecedentRow,
    collect_pack,
    fetch_openalex_works,
    fetch_similar_works,
    merge_rows,
    row_from_work,
    rows_from_hits,
    write_pack,
)
from paperful.snowball.openalex import OpenAlexBudgetExceeded
from tests.conftest import make_item


def _hit(**overrides):
    base = dict(
        item_key="ITEM0001",
        chunk_index=0,
        text="Area-based management in ABNJ",
        score=0.91,
        title="Held paper",
        year=2019,
        doi="10.1000/held",
        pages="p. 3",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _work(*, doi="10.1000/public", title="Public work", year=2021, oa="W1", cited=4):
    return {
        "id": f"https://openalex.org/{oa}",
        "doi": f"https://doi.org/{doi}",
        "display_name": title,
        "publication_year": year,
        "cited_by_count": cited,
        "primary_location": {"landing_page_url": f"https://doi.org/{doi}"},
    }


class FakeClient:
    def __init__(self, works=None):
        self.works = list(works or [])

    def search(self, query, *, limit, year_from, year_to):
        del query, year_from, year_to
        return self.works[:limit]

    def resolve_keyword_slugs(self, query, limit=3):
        del query, limit
        return []

    def works_by_keywords(self, slugs, *, limit, year_from, year_to):
        del slugs, limit, year_from, year_to
        return []

    def work_by_doi(self, doi):
        del doi
        return None


def test_fingerprint_stamps_library_hit_held():
    fp = LibraryFingerprint.from_items([make_item(doi="10.1000/held")])
    row = row_from_work(
        _work(doi="10.1000/held", title="Held paper"), fp, source="openalex"
    )
    assert row.evidence == "held"
    assert row.suggested_action == "skip"
    assert row.item_key == "ITEM0001"


def test_openalex_miss_is_public_metadata_only():
    fp = LibraryFingerprint.from_items([make_item()])
    row = row_from_work(_work(), fp, source="openalex")
    assert row.evidence == "public-metadata-only"
    assert row.suggested_action == "ingest-dois"


def test_doi_dedupe_prefers_passage():
    held = rows_from_hits([_hit(doi="10.1000/a", text="passage from the PDF")])
    public = [
        PrecedentRow(
            evidence="public-metadata-only",
            doi="10.1000/a",
            title="Same DOI public",
            suggested_action="ingest-dois",
            source="openalex",
        )
    ]
    rows, dropped = merge_rows([held, public])
    assert dropped == 1
    assert len(rows) == 1
    assert rows[0].evidence == "held"
    assert "passage" in rows[0].passage
    assert rows[0].suggested_action == "ask"


def test_collect_pack_both_evidence_stamps(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    fp = LibraryFingerprint.from_items([make_item(doi="10.1000/held")])
    rows, _findings, counts, _partial = collect_pack(
        cfg,
        "area-based management",
        fp,
        client=FakeClient([_work()]),
        held_hits=[_hit()],
    )
    stamps = {r.evidence for r in rows}
    assert stamps == {"held", "public-metadata-only"}
    assert counts["held"] >= 1
    assert counts["public_metadata_only"] == 1
    folder = write_pack(cfg.state_dir, "library", "area-based management", rows, [], counts)
    dois = (folder / "dois.txt").read_text(encoding="utf-8")
    assert "10.1000/public" in dois
    assert "10.1000/held" not in dois


def test_openalex_budget_is_partial():
    class BudgetClient:
        def search(self, query, *, limit, year_from, year_to):
            del query, limit, year_from, year_to
            raise OpenAlexBudgetExceeded("daily", partial=[_work()])

        def resolve_keyword_slugs(self, query, limit=3):
            del query, limit
            return []

    works, findings, partial = fetch_openalex_works(
        BudgetClient(),
        "q",
        limit=10,
        year_from=None,
        year_to=None,
        search_keywords=False,
        keyword_limit=3,
    )
    assert partial is True
    assert "openalex_budget" in findings
    assert works and works[0]["display_name"] == "Public work"


def test_similar_hop_folds_neighbours():
    class SimilarClient:
        recommend_getter = staticmethod(lambda _ids, _limit: [])

        def work_by_doi(self, doi):
            return {
                "id": "https://openalex.org/WSEED",
                "doi": f"https://doi.org/{doi}",
                "display_name": "Seed",
                "referenced_works": ["https://openalex.org/WREF"],
                "cited_by_count": 1,
                "primary_location": {},
            }

        def works_citing(self, ref_id, *, limit, year_from, year_to):
            del ref_id, limit, year_from, year_to
            return [_work(doi="10.1000/similar", title="Neighbour", oa="WSIM")]

    works, findings, partial = fetch_similar_works(
        SimilarClient(),
        "10.1000/seed",
        limit=10,
        year_from=None,
        year_to=None,
    )
    assert not partial
    assert findings == []
    assert any(w.get("display_name") == "Neighbour" for w in works)


def test_cli_precedent_has_no_apply():
    res = CliRunner().invoke(app, ["precedent", "--help"])
    assert res.exit_code == 0
    assert "--apply" not in (res.stdout or "")


def test_collect_pack_library_openalex_hit_stays_held(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    fp = LibraryFingerprint.from_items([make_item(doi="10.1000/held")])
    rows, _findings, counts, _partial = collect_pack(
        cfg,
        "phrase",
        fp,
        client=FakeClient([_work(doi="10.1000/held", title="Held paper")]),
        held_hits=[],
    )
    assert counts["held"] == 1
    assert counts["public_metadata_only"] == 0
    assert rows[0].evidence == "held"
    assert rows[0].suggested_action == "skip"


def test_collect_pack_rag_off_still_writes_public(tmp_path):
    cfg = Config(
        out_dir=tmp_path / "out", state_dir=tmp_path / "state", rag_enabled=False
    )
    fp = LibraryFingerprint.from_items([make_item()])
    rows, findings, counts, partial = collect_pack(
        cfg,
        "area-based management",
        fp,
        client=FakeClient([_work()]),
        held_hits=[],
    )
    assert "rag_unavailable" not in findings  # held_hits injected, skip retrieve
    folder = write_pack(
        cfg.state_dir, "library", "area-based management", rows, findings, counts
    )
    pack = (folder / "pack.json").read_text(encoding="utf-8")
    md = (folder / "pack.md").read_text(encoding="utf-8")
    dois = (folder / "dois.txt").read_text(encoding="utf-8")
    assert SCHEMA in pack
    assert counts["public_metadata_only"] == 1
    assert counts["held"] == 0
    assert dois.strip() == "10.1000/public"
    assert HONESTY_BANNER in md
    for banned in ("nobody has done this", "no prior art", "novel"):
        assert banned not in md.lower()
    assert not partial


def test_collect_pack_rag_unavailable_when_index_off(tmp_path):
    cfg = Config(
        out_dir=tmp_path / "out", state_dir=tmp_path / "state", rag_enabled=False
    )
    fp = LibraryFingerprint.from_items([])
    rows, findings, counts, _partial = collect_pack(
        cfg,
        "phrase",
        fp,
        client=FakeClient([]),
    )
    assert findings == ["rag_unavailable"]
    assert rows == []
    assert counts["held"] == 0


def test_dois_txt_skips_held(tmp_path):
    cfg = Config(state_dir=tmp_path / "state")
    rows = [
        PrecedentRow(
            evidence="held",
            doi="10.1000/held",
            title="Held",
            suggested_action="ask",
            item_key="K",
            passage="quote",
        ),
        PrecedentRow(
            evidence="public-metadata-only",
            doi="10.1000/public",
            title="Public",
            suggested_action="ingest-dois",
        ),
    ]
    counts = {"held": 1, "public_metadata_only": 1, "openalex_fetched": 1, "deduped": 0}
    folder = write_pack(cfg.state_dir, "library", "q", rows, [], counts)
    assert dois_from_refs_pack(folder / "pack.json") == ["10.1000/public"]
    assert (folder / "dois.txt").read_text(encoding="utf-8") == "10.1000/public\n"


def test_honesty_banner_avoids_forbidden_claims():
    lowered = HONESTY_BANNER.lower()
    for banned in ("nobody has done this", "no prior art", "novel"):
        assert banned not in lowered


def test_precedent_config_from_toml(tmp_path):
    bare = Config()
    assert bare.precedent_held_k == 10
    assert bare.precedent_public_k == 25
    assert bare.precedent_search_keywords is True
    p = tmp_path / "config.toml"
    p.write_text(
        'email = "me@example.org"\n\n[precedent]\nheld_k = 4\npublic_k = 8\n'
        "search_keywords = false\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.precedent_held_k == 4
    assert cfg.precedent_public_k == 8
    assert cfg.precedent_search_keywords is False


def test_cli_empty_phrase_exits_1():
    res = CliRunner().invoke(app, ["precedent", "   "])
    assert res.exit_code == 1
    assert (
        "phrase" in (res.stdout or "").lower() or "phrase" in (res.output or "").lower()
    )


def test_write_pack_frozen_keys(tmp_path):
    folder = write_pack(
        tmp_path,
        "library",
        "q",
        [
            PrecedentRow(
                evidence="public-metadata-only",
                doi="10.1000/a",
                title="A",
                year=2019,
                suggested_action="ingest-dois",
            )
        ],
        [],
        {"held": 0, "public_metadata_only": 1, "openalex_fetched": 1, "deduped": 0},
    )
    import json

    pack = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    assert PRECEDENT_PACK_KEYS <= pack.keys()
