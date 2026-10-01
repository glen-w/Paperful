"""`continue_deferred`: each budget-paused OpenAlex call resumes without loss or repeats."""

from __future__ import annotations

from collections.abc import Callable

from paperful.snowball.crawl import continue_deferred, search_candidates
from paperful.snowball.openalex import OpenAlexBudgetExceeded, OpenAlexClient

_RESET = "2099-01-01T00:00:00+00:00"


def _work(oa: str, *, keywords: list[str] | None = None, cites: int = 1) -> dict:
    return {
        "id": f"https://openalex.org/{oa}",
        "doi": f"https://doi.org/10.1000/{oa.lower()}",
        "display_name": f"Work {oa}",
        "publication_year": 2021,
        "type": "article",
        "cited_by_count": cites,
        "referenced_works": [],
        "keywords": [
            {"id": f"https://openalex.org/keywords/{k}", "display_name": k, "score": 0.9}
            for k in (keywords or [])
        ],
        "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
    }


def _client(route: Callable[[str, dict], dict]) -> OpenAlexClient:
    return OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=route)


def _spent() -> OpenAlexBudgetExceeded:
    return OpenAlexBudgetExceeded("spent", reset_at=_RESET, reset_in_s=999)


def _deferred(kind: str, remaining: list[str], **extra) -> dict:
    return {
        "kind": kind,
        "run_id": "run-1",
        "seed": {"type": "keyword", "value": "kelp"},
        "gate": "dry-run",
        "hop": 1,
        "per_hop_limit": 50,
        "why_prefix": "Seed",
        "remaining_ids": remaining,
        **extra,
    }


def _oa_ids(rows) -> list[str]:
    return [str(r.ids.get("openalex") or "").rsplit("/", 1)[-1] for r in rows]


def test_refs_resume_keeps_partial_batch_and_narrows_remaining():
    ids = [f"W{i}" for i in range(150)]
    works = {oa: _work(oa) for oa in ids}
    batches = {"n": 0}

    def route(path: str, params: dict) -> dict:
        batches["n"] += 1
        if batches["n"] == 2:
            raise _spent()
        asked = str(params["filter"]).split(":", 1)[1].split("|")
        return {"results": [works[oa] for oa in asked]}

    client = _client(route)
    rows = continue_deferred(client, _deferred("refs", ids))
    assert _oa_ids(rows) == ids[:100]
    assert client.deferred is not None
    assert client.deferred["remaining_ids"] == ids[100:]
    assert client.deferred["run_id"] == "run-1"
    assert client.deferred["gate"] == "dry-run"

    again = _client(route)
    rest = continue_deferred(again, client.deferred)
    assert again.deferred is None
    assert _oa_ids(rest) == ids[100:]
    assert all(r.direction == "refs" for r in rows + rest)


def test_seeds_resume_stops_at_the_doi_that_hit_the_budget():
    dois = ["10.1000/a", "10.1000/b", "10.1000/c"]
    calls: list[str] = []

    def route(path: str, params: dict) -> dict:
        doi = path.split("/works/https://doi.org/", 1)[1]
        calls.append(doi)
        if doi == "10.1000/b" and calls.count(doi) == 1:
            raise _spent()
        return _work(doi.rsplit("/", 1)[1].upper())

    client = _client(route)
    deferred = _deferred("seeds", dois, seed={"type": "doi", "value": dois[0]})
    rows = continue_deferred(client, deferred)
    assert _oa_ids(rows) == ["A"]
    assert client.deferred["remaining_ids"] == ["10.1000/b", "10.1000/c"]

    again = _client(route)
    rest = continue_deferred(again, client.deferred)
    assert _oa_ids(rest) == ["B", "C"]
    assert calls == ["10.1000/a", "10.1000/b", "10.1000/b", "10.1000/c"]


def test_seeds_resume_honours_include_seeds_false():
    client = _client(lambda path, params: _work("A"))
    rows = continue_deferred(
        client, _deferred("seeds", ["10.1000/a"], include_seeds=False)
    )
    assert rows == []
    assert client.deferred is None


def test_keywords_resume_pauses_on_the_second_seed():
    seeds = {"S1": _work("S1", keywords=["kelp"]), "S2": _work("S2", keywords=["krill"])}
    hits = {"kelp": _work("K1", keywords=["kelp"]), "krill": _work("K2", keywords=["krill"])}
    spent_once = {"krill": True}

    def route(path: str, params: dict) -> dict:
        filt = str(params.get("filter") or "")
        if filt.startswith("openalex:"):
            return {"results": [seeds[filt.split(":", 1)[1]]]}
        slug = filt.split(",", 1)[0].rsplit("/", 1)[-1].split(":", 1)[1]
        if spent_once.pop(slug, False):
            raise _spent()
        return {"results": [hits[slug]]}

    client = _client(route)
    rows = continue_deferred(client, _deferred("keywords", ["S1", "S2"]))
    assert _oa_ids(rows) == ["K1"]
    assert rows[0].biblio["keyword_overlap"] == 1
    assert client.deferred["remaining_ids"] == ["S2"]

    again = _client(route)
    assert _oa_ids(continue_deferred(again, client.deferred)) == ["K2"]


def _search_route(total: int, spend_first: bool):
    works = [_work(f"W{i}") for i in range(total)]
    state = {"spent": spend_first}

    def route(path: str, params: dict) -> dict:
        if state["spent"]:
            state["spent"] = False
            raise _spent()
        size = int(params["per_page"])
        if "cursor" in params:
            start = 0 if params["cursor"] == "*" else int(params["cursor"])
            nxt = str(start + size) if start + size < total else None
            meta = {"count": total, "next_cursor": nxt}
        else:
            start = (int(params["page"]) - 1) * size
            meta = {"count": total}
        return {"results": works[start : start + size], "meta": meta}

    return route


def test_search_resume_keeps_the_original_max_candidates():
    route = _search_route(30, spend_first=True)
    client = _client(route)
    rows = search_candidates(
        client,
        "kelp",
        run_id="run-1",
        gate="dry-run",
        depth=0,
        direction="refs",
        max_candidates=30,
        per_hop_limit=5,
        year_from=None,
        year_to=None,
    )
    assert rows == []
    assert client.deferred["kind"] == "search"

    resumed = continue_deferred(_client(route), client.deferred)
    assert len(resumed) == 30


def test_search_resume_keeps_an_uncapped_search_uncapped():
    route = _search_route(120, spend_first=False)
    deferred = _deferred("search", ["kelp"], max_candidates=0, per_hop_limit=5)
    assert len(continue_deferred(_client(route), deferred)) == 120


def test_search_resume_of_an_older_deferred_file_falls_back_to_per_hop():
    route = _search_route(30, spend_first=False)
    deferred = _deferred("search", ["kelp"], per_hop_limit=5)
    assert len(continue_deferred(_client(route), deferred)) == 5


def test_unknown_kind_is_a_no_op():
    client = _client(lambda path, params: {"results": []})
    assert continue_deferred(client, _deferred("mystery", ["W1"])) == []
    assert client.deferred is None
