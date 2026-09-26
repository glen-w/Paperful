"""Europe PMC fill asks for gaps, in batches, and counts new DOIs."""

from __future__ import annotations

from paperful.snowball.candidate import Candidate
from paperful.snowball.fill import run_fill_pass
from paperful.snowball.tally import Tally, colour_for, metrics_for


def _row(doi: str, *, hop: int = 0, direction: str = "refs", why: str = "seed") -> Candidate:
    return Candidate(
        "r",
        {"type": "doi", "value": doi},
        hop,
        direction,
        {"doi": doi},
        {"title": doi},
        why,
        "new",
        {"backend": "openalex"},
        "dry-run",
    )


def test_europepmc_fill_skips_neighbours_cites_and_rows_that_already_cite():
    seen: list[str] = []

    def epmc(doi: str) -> dict:
        seen.append(doi)
        return {"references": [{"doi": "10.1000/new", "title": "New", "year": 2020}]}

    parent = _row("10.1000/parent")
    child = _row("10.1000/child", hop=1, why="ref of 10.1000/parent")
    cite = _row("10.1000/cite", direction="cites", why="cites 10.1000/parent")
    gap = _row("10.1000/gap")
    lines: list[str] = []
    tally = Tally(lines.append, interval_s=60)
    rows = [parent, child, cite, gap]
    added = run_fill_pass(
        rows,
        ("europepmc",),
        crossref_getter=None,
        s2_getter=None,
        europepmc_getter=epmc,
        pdf_getter=None,
        per_hop_limit=5,
        direction="both",
        tally=tally,
    )
    assert added == {}
    assert seen == ["10.1000/gap"]
    assert "10.1000/new" in {row.ids["doi"] for row in rows}
    tally.report()
    assert lines[-1] == "europepmc · 1 searches · 1 papers"


def test_batched_probe_skips_the_rest_when_the_index_misses(tmp_path, monkeypatch):
    from paperful.snowball.europepmc import PROBE_SIZE

    calls: list[str] = []

    class Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"hitCount": 0, "resultList": {"result": []}}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(url)
        return Resp()

    monkeypatch.setattr("httpx.get", fake_get)
    rows = [_row(f"10.1000/p{i}") for i in range(PROBE_SIZE + 5)]
    lines: list[str] = []
    tally = Tally(lines.append, interval_s=60)
    run_fill_pass(
        rows,
        ("europepmc",),
        crossref_getter=None,
        s2_getter=None,
        europepmc_getter=lambda doi: (_ for _ in ()).throw(AssertionError(doi)),
        pdf_getter=None,
        per_hop_limit=5,
        direction="refs",
        tally=tally,
        europepmc_cache=tmp_path / "europepmc",
    )
    assert len(calls) == 1
    assert "/references" not in calls[0]
    assert any("0 in index" in line and "skipped 5" in line for line in lines)
    tally.report()
    assert f"{PROBE_SIZE} searches · 0 papers" in lines[-1]


def test_reference_list_is_skipped_unless_the_record_has_one(tmp_path, monkeypatch):
    from paperful.snowball.europepmc import lookup_dois

    urls: list[str] = []

    class Resp:
        def __init__(self, body: dict):
            self.status_code = 200
            self._body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._body

    def fake_get(url, params=None, headers=None, timeout=None):
        urls.append(url)
        if url.endswith("/references"):
            return Resp({"referenceList": {"reference": [{"doi": "10.1000/should-not", "title": "No"}]}})
        return Resp(
            {
                "resultList": {
                    "result": [
                        {
                            "doi": "10.1000/bare",
                            "id": "1",
                            "source": "MED",
                            "title": "Bare",
                            "pubYear": 2020,
                            "hasReferences": "N",
                            "authorString": "Ada Lovelace",
                            "journalTitle": "PLOS",
                        }
                    ]
                }
            }
        )

    monkeypatch.setattr("httpx.get", fake_get)
    cache = tmp_path / "europepmc"
    found = lookup_dois(["10.1000/bare", "10.1000/missing"], cache_dir=cache)
    assert found["10.1000/missing"] is None
    assert found["10.1000/bare"]["references"] == []
    assert found["10.1000/bare"]["title"] == "Bare"
    assert not any(url.endswith("/references") for url in urls)
    urls.clear()
    again = lookup_dois(["10.1000/bare"], cache_dir=cache)
    assert again["10.1000/bare"]["title"] == "Bare"
    assert urls == []


def test_pmid_only_reference_is_resolved_to_a_doi(tmp_path, monkeypatch):
    from paperful.snowball.europepmc import europepmc_work

    class Resp:
        def __init__(self, body: dict):
            self.status_code = 200
            self._body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._body

    def fake_get(url, params=None, headers=None, timeout=None):
        query = (params or {}).get("query") or ""
        if url.endswith("/references"):
            return Resp(
                {
                    "referenceList": {
                        "reference": [
                            {
                                "title": "A real paper",
                                "pubYear": 2009,
                                "source": "MED",
                                "id": "19623248",
                            }
                        ]
                    }
                }
            )
        if "EXT_ID:" in query:
            return Resp(
                {"resultList": {"result": [{"pmid": "19623248", "doi": "10.1371/journal.pone.0000001", "id": "19623248"}]}}
            )
        return Resp(
            {
                "resultList": {
                    "result": [
                        {
                            "doi": "10.1073/pnas.1",
                            "id": "34645710",
                            "source": "MED",
                            "title": "Opinion",
                            "hasReferences": "Y",
                            "pubYear": 2021,
                        }
                    ]
                }
            }
        )

    monkeypatch.setattr("httpx.get", fake_get)
    payload = europepmc_work("10.1073/pnas.1", cache_dir=tmp_path / "europepmc")
    assert payload is not None
    assert payload["references"] == [
        {"doi": "10.1371/journal.pone.0000001", "pmid": "19623248", "title": "A real paper", "year": 2009}
    ]


def test_every_citation_backend_skips_a_closed_gap():
    asked: list[str] = []

    def crossref(doi: str) -> dict:
        asked.append(f"crossref:{doi}")
        if doi == "10.1000/gap":
            return {"references": [{"doi": "10.1000/via-crossref", "title": "Via", "year": 2018}]}
        return {}

    def later(doi: str) -> dict:
        asked.append(doi)
        return {"references": [{"doi": "10.1000/should-not", "title": "No", "year": 2017}]}

    parent = _row("10.1000/gap")
    neighbour = _row("10.1000/neighbour", hop=1, why="ref of 10.1000/other")
    cite = _row("10.1000/cite", direction="cites", why="cites 10.1000/gap")
    run_fill_pass(
        [parent, neighbour, cite],
        ("crossref", "semanticscholar", "europepmc", "pdf"),
        crossref_getter=crossref,
        s2_getter=later,
        europepmc_getter=later,
        pdf_getter=later,
        per_hop_limit=5,
        direction="both",
    )
    assert asked == ["crossref:10.1000/gap"]


def test_europepmc_progress_uses_papers():
    assert metrics_for("europepmc") == ("searches", "papers")
    assert colour_for("europepmc") == "magenta"
    assert metrics_for("crossref") == ("searches", "fields")
