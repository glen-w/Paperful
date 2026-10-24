"""Discover → People (authorwatch) POST routes with a stubbed OpenAlex and job queue."""

from __future__ import annotations

import json

import pytest

from paperful import authorwatch as aw
from paperful.config import Config
from paperful.serve import create_app, fastapi_available
from paperful.ui import commands, jobs

pytestmark = pytest.mark.skipif(not fastapi_available(), reason="paperful[serve] extra missing")

ORCID = "0000-0002-1825-0097"


@pytest.fixture
def env(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    cfg = Config(email="t@example.org", out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    monkeypatch.setattr("paperful.ui.app.doctor_payload", lambda _c, probe=False: [])
    monkeypatch.setattr(
        "paperful.ui.app.collections_tree", lambda _c: {"ok": True, "collections": []}
    )
    queued: list[tuple[str, object]] = []

    def fake_enqueue(_cfg, verb, fn, *, args=None):
        queued.append((verb, fn))
        return f"cmd{len(queued)}"

    monkeypatch.setattr(commands, "enqueue", fake_enqueue)

    class NoNetworkOA:
        def author_by_orcid(self, orcid):
            return {"id": "https://openalex.org/A1", "display_name": "Ada Lovelace"}

    monkeypatch.setattr(aw, "_openalex_client", lambda cfg, client=None: client or NoNetworkOA())

    class Env:
        pass

    e = Env()
    e.cfg, e.queued = cfg, queued
    e.client = TestClient(create_app(cfg), raise_server_exceptions=False)
    return e


def _post(env, path, **data):
    return env.client.post(path, data=data, follow_redirects=False)


def _people(env, name="lab"):
    return aw.load_people(env.cfg, name)


def test_add_edit_remove_roundtrip(env):
    res = _post(env, "/discover/aw/add", list_name="lab", orcid=ORCID, affiliation="https://uni.example/dept")
    assert res.status_code == 303 and "list_name=lab" in res.headers["location"]
    (person,) = _people(env)
    assert person.display_name == "Ada Lovelace" and person.orcid == ORCID and person.affiliation_host

    res = _post(env, "/discover/aw/edit", list_name="lab", person_id=person.id, display_name="Ada L.", affiliation="")
    assert res.status_code == 303
    assert _people(env)[0].display_name == "Ada L."

    res = _post(env, "/discover/aw/remove", list_name="lab", person_id=person.id)
    assert res.status_code == 303 and _people(env) == []


def test_add_defaults_to_followed_list(env):
    _post(env, "/discover/aw/add", display_name="Grace Hopper")
    assert [p.display_name for p in aw.load_people(env.cfg, "followed")] == ["Grace Hopper"]


def test_add_without_identity_is_an_error_not_a_write(env):
    res = _post(env, "/discover/aw/add", list_name="lab")
    assert res.status_code >= 400
    assert _people(env) == []


@pytest.mark.parametrize("path", ["add", "remove", "edit", "delete"])
@pytest.mark.parametrize("name", ["../escape", "a/b", ".hidden", "bad name"])
def test_hostile_list_names_never_touch_the_filesystem(env, tmp_path, path, name):
    res = _post(env, f"/discover/aw/{path}", list_name=name, orcid=ORCID, person_id="p1", display_name="X")
    assert res.status_code >= 400
    assert not (tmp_path / "escape").exists()
    root = env.cfg.state_dir / "authorwatch"
    assert not root.exists() or list(root.iterdir()) == []


def test_delete_removes_list_and_unknown_list_errors(env):
    _post(env, "/discover/aw/save", name="lab")
    res = _post(env, "/discover/aw/delete", list_name="lab")
    assert res.status_code == 303 and not (env.cfg.state_dir / "authorwatch" / "lab").exists()
    assert _post(env, "/discover/aw/delete", list_name="lab").status_code >= 400


def test_save_with_blank_name_does_nothing(env):
    res = _post(env, "/discover/aw/save", name="  ")
    assert res.status_code == 303
    assert not (env.cfg.state_dir / "authorwatch").exists()


def test_resolve_enqueues_and_runs_resolution(env, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(aw, "resolve_people", lambda cfg, name, **kw: calls.append(name))
    res = _post(env, "/discover/aw/resolve", list_name="lab")
    assert res.status_code == 303
    verb, fn = env.queued[-1]
    assert verb == "authorwatch_resolve"
    fn("cmd")
    assert calls == ["lab"]


def test_run_parses_counts_and_forwards_kwargs(env, monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(aw, "run_list", lambda cfg, name, **kw: seen.update(kw, name=name))
    _post(env, "/discover/aw/run", list_name="lab", backfill_from="2024-01-01", max_authors="5", per_author_limit="9")
    verb, fn = env.queued[-1]
    assert verb == "authorwatch_run"
    fn("cmd")
    assert seen["name"] == "lab" and seen["backfill_from"] == "2024-01-01"
    assert seen["max_authors"] == 5 and seen["per_author_limit"] == 9

    seen.clear()
    _post(env, "/discover/aw/run", list_name="lab")
    env.queued[-1][1]("cmd")
    assert seen["backfill_from"] is None and "max_authors" not in seen and "per_author_limit" not in seen


def test_run_rejects_non_numeric_counts_without_queueing(env):
    before = len(env.queued)
    res = _post(env, "/discover/aw/run", list_name="lab", max_authors="many")
    assert res.status_code == 303 and "whole+numbers" in res.headers["location"].replace("%20", "+")
    assert len(env.queued) == before


def test_suggest_and_accept_forward_form(env, monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(jobs, "authorwatch_suggest", lambda cfg, **kw: seen.update(suggest=kw))
    monkeypatch.setattr(jobs, "authorwatch_accept", lambda cfg, **kw: seen.update(accept=kw))
    env.client.cookies.set("pf_collection", "ocean")
    _post(env, "/discover/aw/suggest", list_name="lab", method="coauthors", limit="7")
    assert env.queued[-1][0] == "authorwatch_suggest"
    env.queued[-1][1]("cmd")
    assert seen["suggest"] == {"list_name": "lab", "collection": "ocean", "method": "coauthors", "limit": 7}

    res = env.client.post(
        "/discover/aw/accept",
        content=b"list_name=lab&suggestion_id=s1&suggestion_id=s2&seed_from=ocean",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    env.queued[-1][1]("cmd")
    assert seen["accept"] == {"list_name": "lab", "suggestion_ids": ["s1", "s2"], "seed_from": "ocean"}


def test_briefing_requires_name_and_writes_markdown(env, monkeypatch):
    before = len(env.queued)
    assert _post(env, "/discover/aw/briefing", list_name="").status_code == 303
    assert len(env.queued) == before

    path = env.cfg.state_dir / "briefing.md"
    path.write_text("# Briefing\n", encoding="utf-8")
    monkeypatch.setattr(aw, "write_briefing", lambda cfg, name: path)
    attached: list[tuple[str, dict]] = []
    monkeypatch.setattr(jobs, "_attach_result", lambda cfg, cmd_id, payload: attached.append((cmd_id, payload)))
    _post(env, "/discover/aw/briefing", list_name="lab")
    assert env.queued[-1][0] == "authorwatch_briefing"
    env.queued[-1][1]("cmdX")
    assert attached == [("cmdX", {"path": str(path), "markdown": "# Briefing\n"})]


def test_import_writes_upload_then_hands_off(env, monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(jobs, "authorwatch_import", lambda cfg, **kw: seen.update(kw))
    res = env.client.post(
        "/discover/aw/import",
        data={"list_name": "lab", "source": "CSV"},
        files={"file": ("people.csv", b"name\nAda\n", "text/csv")},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert seen["list_name"] == "lab" and seen["source"] == "csv"
    assert seen["path"].name == "people.csv"
    assert seen["path"].read_bytes() == b"name\nAda\n"
    assert seen["path"].parent == env.cfg.state_dir / "gui" / "uploads"
