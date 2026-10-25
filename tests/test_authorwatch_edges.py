"""authorwatch edge paths: next-step ladder, show output, name checks, ledger errors."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from paperful import authorwatch as aw
from paperful.authorwatch import (
    AuthorwatchError,
    Person,
    accept_suggestions,
    add_person,
    delete_list,
    list_dir,
    list_summaries,
    load_people,
    next_step,
    remove_person,
    save_list,
    save_people,
    show_list,
    update_person,
)
from paperful.config import Config
from paperful.snowball.candidate import Candidate

ORCID = "0000-0002-1825-0097"


@pytest.fixture
def cfg(tmp_path) -> Config:
    c = Config(email="t@example.org", out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    c.state_dir.mkdir(parents=True)
    return c


class OA:
    def author_by_orcid(self, orcid):
        return {"id": "https://openalex.org/A1", "display_name": "Ada Lovelace"}


def _set_watch(cfg, name, **fields):
    path = list_dir(cfg, name) / "watch.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    body.update(fields)
    path.write_text(json.dumps(body), encoding="utf-8")


def _inbox_row(doi="10.1/new"):
    return Candidate(
        run_id="aw", seed={"type": "orcid", "value": ORCID}, hop=1, direction="authored",
        ids={"doi": doi}, biblio={"title": "T", "year": 2025}, why="w", status="new",
        provenance={"backend": "openalex"}, gate="dry-run", keep=True, score=1.0,
    )


@pytest.mark.parametrize("bad", ["", "../x", "a/b", ".hidden", "-lead", "has space", "x" * 200 + "/"])
def test_list_names_are_validated(cfg, bad):
    with pytest.raises(AuthorwatchError, match="Invalid list name"):
        save_list(cfg, bad)
    assert not (cfg.state_dir / "authorwatch").exists() or not any(
        (cfg.state_dir / "authorwatch").iterdir()
    )


def test_next_step_ladder(cfg):
    save_list(cfg, "lab")
    assert next_step(cfg, "lab") == "paperful authorwatch add lab --orcid <ORCID>"

    save_people(cfg, "lab", [Person(id="p1", display_name="Unknown One")])
    assert next_step(cfg, "lab") == "paperful authorwatch resolve lab"

    save_people(
        cfg, "lab",
        [Person(id="p1", display_name="Held One", status="held", held_candidates=[{"display_name": "A"}])],
    )
    assert next_step(cfg, "lab") == "paperful authorwatch add lab --orcid <ORCID>"

    save_people(
        cfg, "lab",
        [Person(id="p1", display_name="Held One", status="held",
                held_candidates=[{"display_name": "A"}, {"display_name": "B", "orcid": ORCID}])],
    )
    assert next_step(cfg, "lab") == f"paperful authorwatch add lab --orcid {ORCID}"

    save_people(cfg, "lab", [Person(id="p1", orcid=ORCID, status="ok", display_name="Ok")])
    assert next_step(cfg, "lab") == "paperful authorwatch run lab --backfill-from YYYY-MM-DD"

    _set_watch(cfg, "lab", baseline_at="2025-01-01T00:00:00+00:00")
    assert next_step(cfg, "lab") == "paperful authorwatch run lab"

    aw.append_inbox(cfg, "lab", [_inbox_row()])
    assert next_step(cfg, "lab") == "paperful authorwatch apply lab -C <collection> --apply"


def test_show_list_reports_counts_held_table_and_next(cfg, monkeypatch):
    save_list(cfg, "lab")
    save_people(
        cfg, "lab",
        [
            Person(id="p1", display_name="Ada", orcid=ORCID, status="ok"),
            Person(id="p2", display_name="Grace H", status="held",
                   held_candidates=[{"display_name": "Grace Hopper", "orcid": "0000-0001-0000-0001"},
                                    {"display_name": "Grace Hall", "openalex": "A99"}]),
            Person(id="p3", display_name="Nobody"),
        ],
    )
    monkeypatch.setattr(
        aw,
        "gather_briefing",
        lambda cfg, name, max_people=0: {
            "people": [
                {"display_name": "Ada", "recent_works": [1, 2], "coauthors": [{"display_name": "Bob"}]},
                {"orcid": "0000-0000-0000-0001", "recent_works": [], "coauthors": [{}]},
                {"display_name": "Quiet", "recent_works": [], "coauthors": []},
            ]
        },
    )
    buf = StringIO()
    show_list(cfg, "lab", console=Console(file=buf, highlight=False, width=140))
    out = buf.getvalue()
    assert "people · 3 (ok 1 · held 1 · unresolved 1)" in out
    assert "baseline · not yet" in out
    assert "held (add --orcid to confirm)" in out
    assert "Grace Hopper 0000-0001-0000-0001" in out and "Grace Hall A99" in out
    assert "Ada: 2 recent, co-authors incl. Bob" in out
    assert "0000-0000-0000-0001: co-authors" in out
    assert "Quiet" not in out
    assert "Next: paperful authorwatch run lab --backfill-from YYYY-MM-DD" in out


def test_show_list_survives_briefing_failure_and_shows_dates(cfg, monkeypatch):
    save_list(cfg, "lab")
    save_people(cfg, "lab", [Person(id="p1", display_name="Ada", orcid=ORCID, status="ok")])
    _set_watch(cfg, "lab", baseline_at="2025-01-01", last_run_at="2025-02-02")

    def boom(*a, **k):
        raise AuthorwatchError("OpenAlex unavailable")

    monkeypatch.setattr(aw, "gather_briefing", boom)
    buf = StringIO()
    show_list(cfg, "lab", console=Console(file=buf, highlight=False, width=140))
    out = buf.getvalue()
    assert "baseline · 2025-01-01" in out and "last run · 2025-02-02" in out
    assert "Next: paperful authorwatch run lab" in out


def test_add_person_requires_something_and_merges_duplicates(cfg):
    with pytest.raises(AuthorwatchError, match="Pass --orcid"):
        add_person(cfg, "lab")
    first = add_person(cfg, "lab", orcid=ORCID, client=OA())
    assert first.display_name == "Ada Lovelace" and first.openalex == "A1" and first.is_ok()
    again = add_person(cfg, "lab", orcid=ORCID, display_name="Ignored", affiliation_host="https://uni.example/x", client=OA())
    assert again.id == first.id
    assert len(load_people(cfg, "lab")) == 1
    assert load_people(cfg, "lab")[0].affiliation_host


def test_add_person_by_openalex_and_by_name_only(cfg):
    by_id = add_person(cfg, "lab", openalex="https://openalex.org/A42")
    assert by_id.openalex == "A42" and by_id.status == "ok" and by_id.display_name == "A42"
    named = add_person(cfg, "lab", display_name="Grace Hopper")
    assert named.status == "unresolved" and not named.is_ok()
    # Dedupe keys differ (name: vs orcid:), so an ORCID add does not fold into the
    # name-only row; `resolve` is what promotes unresolved rows.
    other = add_person(cfg, "lab", display_name="Grace Hopper", orcid=ORCID, client=OA())
    assert other.orcid == ORCID and other.id != named.id
    assert len(load_people(cfg, "lab")) == 3


def test_add_person_survives_orcid_lookup_failure(cfg):
    class Broken:
        def author_by_orcid(self, orcid):
            raise RuntimeError("down")

    person = add_person(cfg, "lab", orcid=ORCID, client=Broken())
    assert person.orcid == ORCID and person.display_name == ORCID and person.is_ok()


def test_update_and_remove_error_paths(cfg):
    person = add_person(cfg, "lab", orcid=ORCID, client=OA())
    with pytest.raises(AuthorwatchError, match="Pass --id"):
        update_person(cfg, "lab", "")
    with pytest.raises(AuthorwatchError, match="No matching person"):
        update_person(cfg, "lab", "p_nope", display_name="X")
    edited = update_person(cfg, "lab", person.id, display_name="  Ada L  ", affiliation_host="https://u.example")
    assert edited.display_name == "Ada L"
    with pytest.raises(AuthorwatchError, match="Pass --orcid or --id"):
        remove_person(cfg, "lab")
    with pytest.raises(AuthorwatchError):
        remove_person(cfg, "lab", person_id="p_nope")
    assert remove_person(cfg, "lab", person_id=person.id).id == person.id
    assert load_people(cfg, "lab") == []


def test_delete_list_guards(cfg):
    with pytest.raises(AuthorwatchError, match="Unknown authorwatch list"):
        delete_list(cfg, "ghost", yes=True)
    save_list(cfg, "lab")
    with pytest.raises(AuthorwatchError, match="Refusing to delete"):
        delete_list(cfg, "lab")
    assert list_dir(cfg, "lab").is_dir()
    delete_list(cfg, "lab", yes=True)
    assert not list_dir(cfg, "lab").exists()


def test_list_summaries_skips_non_lists(cfg):
    assert list_summaries(cfg) == []
    save_list(cfg, "lab")
    save_people(cfg, "lab", [Person(id="p1", orcid=ORCID, status="ok", display_name="A"),
                             Person(id="p2", display_name="B")])
    (cfg.state_dir / "authorwatch" / "stray-file.txt").write_text("x", encoding="utf-8")
    (cfg.state_dir / "authorwatch" / "empty-dir").mkdir()
    assert list_summaries(cfg) == [("lab", 2, 1)]


def test_accept_suggestions_requires_selection(cfg):
    save_list(cfg, "lab")
    with pytest.raises(AuthorwatchError, match="No suggestions"):
        accept_suggestions(cfg, "lab", all_pending=True)
    from paperful.authorwatch_suggest import Suggestion

    aw.save_suggestions(
        cfg, "lab",
        [Suggestion.from_dict({"id": "s1", "display_name": "Ada", "orcid": ORCID, "status": "pending"}),
         Suggestion.from_dict({"id": "s2", "display_name": "Bob", "status": "pending"})],
    )
    with pytest.raises(AuthorwatchError, match="Pass --id"):
        accept_suggestions(cfg, "lab")
    accepted = accept_suggestions(cfg, "lab", ids={"s1"}, dismiss_rest=True, client=OA())
    assert [p.orcid for p in accepted] == [ORCID]
    statuses = {r.id: r.status for r in aw.load_suggestions(cfg, "lab")}
    assert statuses == {"s1": "accepted", "s2": "dismissed"}


def test_load_people_rejects_corrupt_ledger_lines_gracefully(cfg):
    save_list(cfg, "lab")
    path = list_dir(cfg, "lab") / "people.jsonl"
    path.write_text(
        json.dumps({"id": "p1", "display_name": "Ok", "orcid": ORCID, "status": "ok"}) + "\n\n",
        encoding="utf-8",
    )
    assert [p.id for p in load_people(cfg, "lab")] == ["p1"]
