"""authorwatch_suggest scoring helpers and the coauthor/mix/most_cited paths (fake OpenAlex)."""

from __future__ import annotations

import pytest

from paperful import authorwatch as aw
from paperful import authorwatch_suggest as sug
from paperful.authorwatch import AuthorwatchError, Person, save_people
from paperful.authorwatch_suggest import (
    Suggestion,
    _author_row_hit,
    _candidate_from_author,
    _enrich_cited,
    _mix_candidates,
    _normalize_scores,
    accumulate_coauthors_from_works,
    suggest_people,
)
from paperful.config import Config
from paperful.snowball.openalex import OpenAlexBudgetExceeded
from tests.conftest import make_item

ORCID_A = "0000-0002-1825-0097"
ORCID_B = "0000-0001-2345-6789"


@pytest.fixture
def cfg(tmp_path) -> Config:
    c = Config(email="t@example.org", out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    c.state_dir.mkdir(parents=True)
    return c


def _row(name, **kw) -> dict:
    base = {
        "id": "https://openalex.org/A1",
        "display_name": name,
        "orcid": None,
        "cited_by_count": 0,
    }
    base.update(kw)
    return base


class OA:
    def __init__(self, authors=None, by_orcid=None, works=None, budget_on=None):
        self.authors = authors or {}
        self.by_orcid = by_orcid or {}
        self.works = works or []
        self.budget_on = budget_on
        self.calls: list[str] = []

    def search_authors(self, name, *, limit=8):
        self.calls.append(f"search:{name}")
        if self.budget_on == "search":
            raise OpenAlexBudgetExceeded("budget gone")
        value = self.authors.get(name)
        if isinstance(value, Exception):
            raise value
        return list(value or [])

    def author_by_orcid(self, orcid):
        self.calls.append(f"orcid:{orcid}")
        if self.budget_on == "orcid":
            raise OpenAlexBudgetExceeded("budget gone")
        value = self.by_orcid.get(orcid)
        if isinstance(value, Exception):
            raise value
        return value

    def works_by_author(self, **kwargs):
        self.calls.append("works")
        if self.budget_on == "works":
            raise OpenAlexBudgetExceeded("budget gone")
        return list(self.works)


# --- scoring helpers ------------------------------------------------------------------


def test_normalize_scores():
    assert _normalize_scores({}) == {}
    assert _normalize_scores({"a": 5, "b": 5}) == {"a": 1.0, "b": 1.0}
    # All-zero citation counts must not read as a perfect score; equal non-zero counts do.
    assert _normalize_scores({"a": 0, "b": 0}) == {"a": 0.0, "b": 0.0}
    assert _normalize_scores({"a": 10, "b": 20, "c": 30}) == {"a": 0.0, "b": 0.5, "c": 1.0}


def test_author_row_hit_needs_exactly_one_clean_hit():
    assert _author_row_hit(OA(authors={"Ann": [_row("Ann")]}), "Ann")["display_name"] == "Ann"
    assert _author_row_hit(OA(authors={"Ann": [_row("Ann"), _row("Ann B")]}), "Ann") is None  # ambiguous
    assert _author_row_hit(OA(authors={"Ann": []}), "Ann") is None
    assert _author_row_hit(OA(authors={"Ann": RuntimeError("boom")}), "Ann") is None
    with pytest.raises(OpenAlexBudgetExceeded):
        _author_row_hit(OA(budget_on="search"), "Ann")


def test_candidate_from_author_normalises_ids_and_pollable():
    full = _candidate_from_author(
        _row("Ann", orcid=f"https://orcid.org/{ORCID_A}"), method="most_cited", score=0.5, why="w"
    )
    assert full.orcid == ORCID_A and full.openalex == "A1" and full.pollable and full.status == "pending"
    bare = _candidate_from_author({"id": "", "display_name": ""}, method="m", score=0, why="")
    assert bare.display_name == "" and not bare.pollable


def test_mix_candidates_blends_scores_and_keeps_pollable():
    corpus = [
        Suggestion(id="1", display_name="Ann", score=1.0, method="corpus"),
        Suggestion(id="2", display_name="Bob", score=0.4, method="corpus"),
    ]
    cited = [
        Suggestion(id="3", display_name="ann", orcid=ORCID_A, score=0.2, pollable=True),
        Suggestion(id="4", display_name="Cy", openalex="A7", score=0.9, pollable=True),
    ]
    mixed = {r.display_name: r for r in _mix_candidates(corpus, cited)}
    assert mixed["Ann"].score == pytest.approx(0.6) and mixed["Ann"].why == "corpus=1.00 · cited=0.20"
    assert mixed["Bob"].score == pytest.approx(0.2) and not mixed["Bob"].pollable
    assert mixed["Cy"].score == pytest.approx(0.45) and mixed["Cy"].pollable
    assert all(r.method == "mix" and r.status == "pending" for r in mixed.values())
    ordered = [r.display_name for r in _mix_candidates(corpus, cited)]
    assert ordered == ["Ann", "Cy", "Bob"]


# --- _enrich_cited ---------------------------------------------------------------------


def test_enrich_cited_ranks_by_citations_and_labels_why(cfg):
    corpus = [
        Suggestion(id="a", display_name="Ann Low", score=1.0, why="3 item(s)"),
        Suggestion(id="b", display_name="Bob High", score=0.5, why="1 item(s)"),
        Suggestion(id="c", display_name="Nobody Known", score=0.1, why="1 item(s)"),
        Suggestion(id="d", display_name="  ", score=0.1),
        Suggestion(id="e", display_name="Has Orcid", orcid=ORCID_B, score=0.2, why="1 item(s)"),
    ]
    oa = OA(
        authors={
            "Ann Low": [_row("Ann Low", id="https://openalex.org/A10", orcid=f"https://orcid.org/{ORCID_A}", cited_by_count=10)],
            "Bob High": [_row("Bob High", id="https://openalex.org/A11", orcid=f"https://orcid.org/0000-0003-0000-0001", cited_by_count=1000)],
            "Nobody Known": [],
        },
        by_orcid={ORCID_B: {"cited_by_count": 500}},
    )
    out = _enrich_cited(cfg, corpus, client=oa, method="most_cited")
    names = [r.display_name for r in out]
    assert "  " not in names and len(out) == 4
    top = out[0]
    assert top.display_name == "Bob High" and top.score == pytest.approx(1.0) and top.pollable
    assert "cited_by_count=1000" in top.why
    assert out[1].display_name == "Has Orcid" and "cited_by_count=500" in out[1].why
    low = next(r for r in out if r.display_name == "Ann Low")
    assert low.score == pytest.approx(0.0) and "cited_by_count=10" in low.why
    unknown = next(r for r in out if r.display_name == "Nobody Known")
    assert not unknown.pollable and unknown.score == 0.1  # no OpenAlex hit: left as the corpus row


def test_enrich_cited_without_any_openalex_hits_returns_input_rows(cfg):
    rows = [Suggestion(id="a", display_name="Ann", score=0.7)]
    assert _enrich_cited(cfg, rows, client=OA(), method="most_cited") == rows


def test_enrich_cited_tolerates_orcid_lookup_failure_but_not_budget_errors(cfg):
    row = Suggestion(id="a", display_name="Ann", orcid=ORCID_A, score=0.3)
    out = _enrich_cited(cfg, [row], client=OA(by_orcid={ORCID_A: RuntimeError("down")}), method="x")
    assert out[0].display_name == "Ann"
    with pytest.raises(OpenAlexBudgetExceeded):
        _enrich_cited(cfg, [row], client=OA(budget_on="orcid"), method="x")


# --- co-authors ------------------------------------------------------------------------


def _work(*authors):
    return {
        "authorships": [
            {"author": {"id": f"https://openalex.org/{aid}", "display_name": name, "orcid": orcid}}
            for aid, name, orcid in authors
        ]
    }


def test_accumulate_coauthors_skips_seed_and_members():
    works = [
        _work(("A1", "Seed Person", None), ("A2", "Frequent Co", f"https://orcid.org/{ORCID_B}")),
        _work(("A1", "Seed Person", None), ("A2", "Frequent Co", f"https://orcid.org/{ORCID_B}"), ("A3", "Member", None)),
        _work(("A4", "One Off", None)),
        {"authorships": None},
        {"authorships": [{"author": {"display_name": ""}}, "junk"]},
    ]
    counts, nodes = accumulate_coauthors_from_works(works, seed_key="openalex:A1", skip_keys={"openalex:A3"})
    assert counts[f"orcid:{ORCID_B}"] == 2 and counts["openalex:A4"] == 1
    assert "openalex:A1" not in counts and "openalex:A3" not in counts
    assert nodes[f"orcid:{ORCID_B}"] == ("Frequent Co", ORCID_B, "A2")
    assert accumulate_coauthors_from_works([], seed_key="x", skip_keys=set()) == ({}, {})


def test_suggest_people_coauthor_method(cfg):
    aw.save_list(cfg, "lab")
    save_people(cfg, "lab", [Person(id="p1", display_name="Seed", orcid=ORCID_A, openalex="A1", status="ok")])
    oa = OA(works=[_work(("A1", "Seed", f"https://orcid.org/{ORCID_A}"), ("A2", "Frequent Co", None))] * 2)
    rows = suggest_people(cfg, "lab", collection="", method="coauthor", client=oa, items=[])
    assert [r.display_name for r in rows] == ["Frequent Co"]
    assert rows[0].method == "coauthor" and rows[0].pollable
    # Already pending: a second call offers nothing new.
    assert suggest_people(cfg, "lab", collection="", method="coauthor", client=oa, items=[]) == []


def test_coauthor_method_skips_failing_people_and_budget_errors_surface(cfg):
    aw.save_list(cfg, "lab")
    save_people(
        cfg, "lab",
        [Person(id="p1", display_name="Seed", orcid=ORCID_A, status="ok"),
         Person(id="p2", display_name="No ids", status="unresolved")],
    )

    class Flaky(OA):
        def works_by_author(self, **kwargs):
            raise RuntimeError("openalex hiccup")

    assert suggest_people(cfg, "lab", collection="", method="coauthor", client=Flaky(), items=[]) == []
    with pytest.raises(AuthorwatchError, match="budget gone"):
        suggest_people(cfg, "lab", collection="", method="coauthor", client=OA(budget_on="works"), items=[])


# --- suggest_people orchestration -------------------------------------------------------


def _items():
    return [
        make_item(key="A1", creator_surnames=["Wonder"], first_author="Alice Wonder"),
        make_item(key="A2", creator_surnames=["Wonder"], first_author="Alice Wonder"),
        make_item(key="B1", creator_surnames=["Smith"], first_author="Bob Smith"),
    ]


def test_suggest_people_rejects_unknown_method_and_blank_collection(cfg):
    with pytest.raises(AuthorwatchError, match="Unknown method"):
        suggest_people(cfg, "lab", collection="C", method="vibes", items=[])
    with pytest.raises(AuthorwatchError, match="needs a target collection"):
        suggest_people(cfg, "lab", collection="  ", method="corpus", client=OA())


def test_suggest_people_respects_limit_and_existing_members(cfg):
    aw.save_list(cfg, "lab")
    save_people(cfg, "lab", [Person(id="p1", display_name="Alice Wonder", status="unresolved")])
    rows = suggest_people(cfg, "lab", collection="C", method="corpus", items=_items(), client=OA())
    assert [r.display_name for r in rows] == ["Bob Smith"]  # Alice is already on the list
    capped = suggest_people(
        cfg, "lab2", collection="C", method="corpus", items=_items(), client=OA(), limit=1
    )
    assert len(capped) == 1
    huge = suggest_people(
        cfg, "lab3", collection="C", method="corpus", items=_items(), client=OA(), limit=10_000
    )
    assert len(huge) == 2


def test_suggest_people_mix_method(cfg):
    oa = OA(
        authors={
            "Alice Wonder": [_row("Alice Wonder", id="https://openalex.org/A9", orcid=f"https://orcid.org/{ORCID_A}", cited_by_count=900)],
            "Bob Smith": [],
        }
    )
    rows = suggest_people(cfg, "lab", collection="C", method="mix", items=_items(), client=oa)
    assert {r.method for r in rows} == {"mix"}
    assert rows[0].display_name == "Alice Wonder" and "corpus=" in rows[0].why


def test_suggest_people_budget_error_becomes_authorwatch_error(cfg):
    with pytest.raises(AuthorwatchError, match="budget gone"):
        suggest_people(
            cfg, "lab", collection="C", method="most_cited", items=_items(), client=OA(budget_on="search")
        )


def test_suggestion_round_trips_through_dict():
    row = Suggestion(id="s", display_name="X", orcid=ORCID_A, openalex="A1", method="corpus", score=0.5, why="w", pollable=True)
    assert Suggestion.from_dict(row.to_dict()) == row
    assert Suggestion.from_dict({}).status == "pending"
    assert Suggestion(display_name="Name Only").identity().startswith("name:")
    assert Suggestion(id="s1").identity() == "s1"
    assert sug  # module import guard
