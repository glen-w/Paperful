"""One hop per snowball direction, mocked OpenAlex only."""

from __future__ import annotations

from paperful.snowball.hops import hop_cites, hop_keywords, hop_refs, hop_similar
from tests.test_snowball import _client, _work


def _kw(
    *,
    hop: int = 1,
    depth: int = 1,
    direction: str = "refs",
    per_hop_limit: int = 50,
):
    return dict(
        hop=hop,
        depth=depth,
        direction=direction,
        run_id="r1",
        seed={"type": "doi", "value": "10.1000/seed"},
        gate="dry-run",
        per_hop_limit=per_hop_limit,
        rank="most-cited",
        year_from=None,
        year_to=None,
        why_prefix="Seed",
        min_seed_citations=0,
    )


def test_hop_refs_adds_referenced_work():
    seed = _work("WSEED", "10.1000/seed", "Seed", 2020, 3, refs=["WREF"])
    child = _work("WREF", "10.1000/ref", "Ref", 2019, 1)
    client = _client({"WSEED": seed, "WREF": child})
    rows: list = []
    next_works: list = []
    seen = {"WSEED"}
    stop = hop_refs(client, [seed], rows, next_works, seen, **_kw())
    assert stop is False
    assert [r.ids.get("openalex") for r in rows] == ["WREF"] or [
        str(r.ids.get("openalex") or "").endswith("WREF") for r in rows
    ]
    assert any("WREF" in str(r.ids.get("openalex") or r.identity) for r in rows)
    assert any(w.get("id", "").endswith("WREF") for w in next_works)


def test_hop_cites_adds_citing_work():
    seed = _work("WSEED", "10.1000/seed", "Seed", 2020, 3)
    child = _work("WCITE", "10.1000/cite", "Cite", 2021, 2)
    client = _client({"WSEED": seed, "WCITE": child}, citing={"WSEED": ["WCITE"]})
    rows: list = []
    next_works: list = []
    seen = {"WSEED"}
    stop = hop_cites(client, [seed], rows, next_works, seen, **_kw(direction="cites"))
    assert stop is False
    assert any("WCITE" in str(r.ids.get("openalex") or r.identity) for r in rows)


def test_hop_keywords_adds_overlap_work():
    seed = _work("WSEED", "10.1000/seed", "Seed", 2020, 3)
    seed["keywords"] = [
        {"id": "https://openalex.org/keywords/kelp", "display_name": "kelp", "score": 0.9}
    ]
    child = _work("WKEY", "10.1000/key", "Key", 2021, 2)
    child["keywords"] = [
        {"id": "https://openalex.org/keywords/kelp", "display_name": "kelp", "score": 0.8}
    ]

    def getter(path: str, params: dict) -> dict:
        filt = str(params.get("filter") or "")
        if "keywords.id:" in filt:
            return {"results": [child]}
        return {"results": []}

    from paperful.snowball.openalex import OpenAlexClient

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    rows: list = []
    next_works: list = []
    seen = {"WSEED"}
    stop = hop_keywords(
        client, [seed], rows, next_works, seen, **_kw(direction="keywords")
    )
    assert stop is False
    assert any("WKEY" in str(r.ids.get("openalex") or r.identity) for r in rows)


def test_expand_hops_dispatches_refs(monkeypatch):
    from paperful.snowball.crawl import _expand_hops
    from paperful.snowball.openalex import OpenAlexClient

    seen: list[str] = []

    def fake_refs(*args, **kwargs):
        seen.append("refs")
        return False

    monkeypatch.setattr("paperful.snowball.hops.hop_refs", fake_refs)
    monkeypatch.setattr(
        "paperful.snowball.hops.hop_cites",
        lambda *a, **k: seen.append("cites") or False,
    )
    seed = _work("WSEED", "10.1000/seed", "Seed", 2020, 3)
    client = OpenAlexClient(
        email="t@example.org", api_key="", sleep_s=0, getter=lambda p, q: {}
    )
    rows = _expand_hops(
        client,
        [seed],
        run_id="r1",
        seed={"type": "doi", "value": "10.1000/seed"},
        gate="dry-run",
        depth=1,
        direction="refs",
        per_hop_limit=10,
        year_from=None,
        year_to=None,
        why_prefix="Seed",
    )
    assert rows == []
    assert seen == ["refs"]


def test_hop_similar_delegates_to_similar_neighbours(monkeypatch):
    called = {}

    def fake(*args, **kwargs):
        called["yes"] = True
        return False

    monkeypatch.setattr("paperful.snowball.crawl._similar_neighbours", fake)
    from paperful.snowball.openalex import OpenAlexClient

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=lambda p, q: {})
    stop = hop_similar(client, [], [], set(), **_kw(direction="similar"))
    assert stop is False
    assert called["yes"]
