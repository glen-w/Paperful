"""Author watch lists: people ledger, resolve, run, apply."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from paperful.authorwatch import (
    SOCIAL_EXPORT_HINT,
    accept_suggestions,
    add_person,
    apply_list,
    delete_list,
    import_file,
    load_inbox,
    load_people,
    load_seen,
    load_suggestions,
    load_watch,
    remove_person,
    resolve_people,
    run_list,
    save_list,
    show_list,
    update_person,
    write_briefing,
)
from paperful.authorwatch_social import parse_social_file
from paperful.authorwatch_suggest import suggest_people
from tests.conftest import make_item
from paperful.cli import app
from paperful.doctor import _authorwatch_check
from paperful.snowball.candidate import Candidate
from tests.textutil import plain_text

runner = CliRunner()
ORCID = "0000-0002-1825-0097"
console = Console(record=True)


class FakeOA:
    def __init__(self, *, authors=None, by_orcid=None, works=None):
        self.authors = list(authors or [])
        self.by_orcid = dict(by_orcid or {})
        self.works = list(works or [])
        self.work_calls: list[dict] = []
        self.search_calls: list[str] = []

    def search_authors(self, name: str, *, limit: int = 8):
        self.search_calls.append(name)
        return list(self.authors)

    def author_by_orcid(self, orcid: str):
        return self.by_orcid.get(orcid)

    def works_by_author(self, **kwargs):
        self.work_calls.append(kwargs)
        return list(self.works)


def _work(doi: str = "10.1000/new", title: str = "A new paper about whales", year: int = 2025):
    return {
        "id": "https://openalex.org/W1",
        "doi": f"https://doi.org/{doi}",
        "display_name": title,
        "publication_year": year,
        "type": "article",
        "cited_by_count": 1,
        "language": "en",
        "authorships": [],
        "primary_location": {},
        "open_access": {"is_oa": True},
    }


def _author(name: str, *, orcid: str = "", openalex: str = "A1", inst: str = ""):
    row = {
        "id": f"https://openalex.org/{openalex}",
        "display_name": name,
        "orcid": f"https://orcid.org/{orcid}" if orcid else None,
        "last_known_institutions": [],
        "works_count": 3,
    }
    if inst:
        row["last_known_institutions"] = [
            {"display_name": inst, "homepage_url": f"https://{inst.lower().replace(' ', '')}.edu"}
        ]
    return row


def test_save_add_remove_show(cfg):
    path = save_list(cfg, "ocean-people")
    assert path.is_file()
    person = add_person(cfg, "ocean-people", orcid=ORCID, display_name="Josiah Carberry")
    assert person.status == "ok"
    assert person.orcid == ORCID
    people = load_people(cfg, "ocean-people")
    assert len(people) == 1
    removed = remove_person(cfg, "ocean-people", orcid=ORCID)
    assert removed.orcid == ORCID
    assert load_people(cfg, "ocean-people") == []
    save_list(cfg, "ocean-people")
    add_person(cfg, "ocean-people", display_name="Jane Researcher")
    show_list(cfg, "ocean-people", console=console)
    text = console.export_text()
    assert "unresolved" in text
    assert "Next:" in text


def test_add_orcid_fills_display_name(cfg):
    client = FakeOA(
        by_orcid={ORCID: _author("Josiah Carberry", orcid=ORCID, openalex="A99")}
    )
    person = add_person(cfg, "ocean", orcid=ORCID, client=client)
    assert person.display_name == "Josiah Carberry"
    assert person.openalex == "A99"
    assert person.is_ok()


def test_name_only_stays_unresolved(cfg):
    person = add_person(cfg, "ocean", display_name="Jane Researcher")
    assert person.status == "unresolved"
    assert not person.orcid


def test_resolve_unique_ambiguous_miss(cfg):
    add_person(cfg, "ocean", display_name="Unique Person")
    add_person(cfg, "ocean", display_name="Common Name")
    add_person(cfg, "ocean", display_name="Ghost Author")
    people = load_people(cfg, "ocean")

    class Switching(FakeOA):
        def search_authors(self, name, *, limit=8):
            if name == "Unique Person":
                return [_author("Unique Person", orcid=ORCID, openalex="A1")]
            if name == "Common Name":
                return [
                    _author("Common Name", orcid="0000-0002-1825-0097", openalex="A2"),
                    _author("Common Name", openalex="A3"),
                ]
            return []

    resolve_people(cfg, "ocean", client=Switching())
    by_name = {row.display_name: row for row in load_people(cfg, "ocean")}
    assert by_name["Unique Person"].status == "ok"
    assert by_name["Unique Person"].orcid == ORCID
    assert by_name["Common Name"].status == "held"
    assert by_name["Common Name"].held_candidates
    assert by_name["Ghost Author"].status == "unresolved"


def test_import_csv_json_and_social_without_file(cfg, tmp_path: Path):
    csv_path = tmp_path / "follows.csv"
    csv_path.write_text("name,orcid\nJosiah Carberry,0000-0002-1825-0097\n", encoding="utf-8")
    import_file(cfg, "ocean", path=csv_path, source="csv", resolve=False)
    assert load_people(cfg, "ocean")[0].orcid == ORCID

    json_path = tmp_path / "people.json"
    json_path.write_text('[{"name": "Other", "orcid": "0000-0002-1694-233X"}]\n', encoding="utf-8")
    import_file(cfg, "ocean", path=json_path, source="json", resolve=False)
    assert len(load_people(cfg, "ocean")) == 2

    try:
        import_file(cfg, "ocean", path=None, source="rg")
        raise AssertionError("expected export recipe")
    except Exception as exc:
        assert "scrape" in str(exc).lower() or SOCIAL_EXPORT_HINT[:20] in str(exc)


def test_poll_run_maps_openalex_budget_to_authorwatch_error(cfg):
    from paperful.authorwatch import AuthorwatchError
    from paperful.snowball.openalex import OpenAlexBudgetExceeded

    add_person(cfg, "ocean", orcid=ORCID, display_name="Josiah")
    run_list(cfg, "ocean", console=console, client=FakeOA())

    class Spent(FakeOA):
        def works_by_author(self, **kwargs):
            raise OpenAlexBudgetExceeded(
                "spent", reset_at="2099-01-01T00:00:00+00:00", reset_in_s=99
            )

    try:
        run_list(cfg, "ocean", console=console, client=Spent())
        raise AssertionError("expected budget error")
    except AuthorwatchError as exc:
        assert exc.code == 2
        assert "OpenAlex daily budget" in str(exc)
        assert "authorwatch run ocean" in str(exc)
        assert "2099-01-01" in str(exc)


def test_default_run_sets_baseline_without_polling(cfg):
    add_person(cfg, "ocean", orcid=ORCID, display_name="Josiah")
    client = FakeOA(works=[_work()])
    first = run_list(cfg, "ocean", console=console, client=client)
    assert first.baseline is True
    assert first.proposed == 0
    assert first.polled == 0
    assert client.work_calls == []
    body = load_watch(cfg, "ocean")
    assert body["baseline_at"]
    assert load_inbox(cfg, "ocean") == []


def test_baseline_run_does_not_open_library(cfg, monkeypatch):
    add_person(cfg, "ocean", display_name="Jane Researcher")

    def boom(*a, **k):
        raise AssertionError("opened library on cursor baseline")

    monkeypatch.setattr("paperful.authorwatch.get_backend", boom)
    first = run_list(cfg, "ocean", console=console, client=FakeOA(works=[_work()]))
    assert first.baseline is True
    assert first.polled == 0


def test_backfill_proposes_and_skips_exists_and_held(cfg):
    add_person(cfg, "ocean", orcid=ORCID, display_name="Josiah")
    add_person(cfg, "ocean", display_name="Held Person")
    resolve_people(
        cfg,
        "ocean",
        client=FakeOA(
            authors=[
                _author("Held Person", openalex="A2"),
                _author("Held Person", openalex="A3"),
            ]
        ),
    )
    client = FakeOA(works=[_work()])

    def lookup(doi, title, year=None, **extra):
        if doi and "exists" in doi:
            return "ITEM1"
        return None

    run_list(cfg, "ocean", console=console, client=client, lookup=lookup)
    second = run_list(
        cfg,
        "ocean",
        console=console,
        client=client,
        lookup=lookup,
        backfill_from="2025-01-01",
    )
    assert second.proposed == 1
    assert second.skipped_held >= 1
    inbox = load_inbox(cfg, "ocean")
    assert inbox[0].ids["doi"] == "10.1000/new"
    assert client.work_calls[-1]["from_publication_date"] == "2025-01-01"

    client.works = [_work(doi="10.1000/exists", title="Already in the library about whales")]
    third = run_list(
        cfg,
        "ocean",
        console=console,
        client=client,
        lookup=lookup,
        backfill_from="2025-01-01",
    )
    assert third.exists == 1
    assert third.proposed == 0


def test_later_run_passes_from_created_date(cfg):
    add_person(cfg, "ocean", orcid=ORCID, display_name="Josiah")
    client = FakeOA(works=[])
    run_list(cfg, "ocean", console=console, client=client)
    run_list(cfg, "ocean", console=console, client=client)
    assert client.work_calls
    assert client.work_calls[-1]["from_created_date"]
    assert client.work_calls[-1]["from_publication_date"] is None


def test_apply_dry_run_and_write_with_snowball_off(cfg, monkeypatch):
    cfg.snowball_enabled = False
    add_person(cfg, "ocean", orcid=ORCID, display_name="Josiah")
    row = Candidate(
        run_id="authorwatch:ocean",
        seed={"type": "authorwatch", "value": ORCID},
        hop=0,
        direction="author",
        ids={"doi": "10.1000/new", "openalex": "W1"},
        biblio={"title": "A new paper about whales", "year": 2025, "authors": ["Josiah"]},
        why="authorwatch:ocean",
        status="new",
        provenance={"backend": "openalex"},
        gate="dry-run",
        keep=True,
    )
    from paperful.authorwatch import append_inbox

    append_inbox(cfg, "ocean", [row])
    dry = apply_list(cfg, "ocean", "Watch/Ocean", console=console, apply=False, lookup=lambda *a, **k: None)
    assert dry.dry_run is True
    assert dry.created == 0

    created = []

    def fake_create(backend, rows, collection, **kwargs):
        created.extend(rows)
        assert collection == "Watch/Ocean"
        return [], {"created": len(rows), "skipped_exists": 0, "failed": 0}

    monkeypatch.setattr("paperful.snowball.ingest.create_new", fake_create)
    written = apply_list(
        cfg,
        "ocean",
        "Watch/Ocean",
        console=console,
        apply=True,
        lookup=lambda *a, **k: None,
        backend=object(),
    )
    assert written.created == 1
    assert created
    again = apply_list(
        cfg,
        "ocean",
        "Watch/Ocean",
        console=console,
        apply=True,
        lookup=lambda *a, **k: None,
        backend=object(),
    )
    assert again.already_applied == 1
    assert again.created == 0


def test_cli_help_and_import_rg_without_file(cfg, tmp_path: Path):
    help_res = runner.invoke(app, ["authorwatch", "--help"])
    assert help_res.exit_code == 0, help_res.stdout
    assert "run" in help_res.stdout
    assert "apply" in help_res.stdout
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\nstate_dir = "{tmp_path / "state"}"\n'
    )
    res = runner.invoke(
        app, ["authorwatch", "import", "ocean", "--source", "rg", "-c", str(cfg_file)]
    )
    assert res.exit_code == 2
    assert "does not live-scrape" in plain_text(res.stdout) or "does not scrape" in plain_text(res.stdout)


def test_cli_save_and_add(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\nstate_dir = "{tmp_path / "state"}"\n'
    )
    save = runner.invoke(app, ["authorwatch", "save", "ocean", "-c", str(cfg_file)])
    assert save.exit_code == 0, save.stdout
    add = runner.invoke(
        app,
        ["authorwatch", "add", "ocean", "--name", "Jane Researcher", "-c", str(cfg_file)],
    )
    assert add.exit_code == 0, add.stdout
    show = runner.invoke(app, ["authorwatch", "show", "ocean", "-c", str(cfg_file)])
    assert show.exit_code == 0, show.stdout
    assert "Jane Researcher" in plain_text(show.stdout) or "unresolved" in plain_text(show.stdout)


def test_briefing_and_doctor(cfg):
    save_list(cfg, "ocean")
    add_person(cfg, "ocean", display_name="Jane Researcher")
    path = write_briefing(cfg, "ocean")
    assert path.is_file()
    check = _authorwatch_check(cfg)
    assert check.status == "amber"
    add_person(cfg, "ocean", orcid=ORCID, display_name="Josiah")
    check = _authorwatch_check(cfg)
    assert check.status == "green"


def test_seen_records_backfill_identities(cfg):
    add_person(cfg, "ocean", orcid=ORCID, display_name="Josiah")
    client = FakeOA(works=[_work()])
    run_list(cfg, "ocean", console=console, client=client, backfill_from="2025-01-01")
    seen = load_seen(cfg, "ocean")
    assert "doi:10.1000/new" in seen
    client.works = [_work()]
    again = run_list(cfg, "ocean", console=console, client=client, backfill_from="2025-01-01")
    assert again.proposed == 0


def test_openalex_id_without_orcid_is_ok_and_polled(cfg):
    add_person(cfg, "ocean", display_name="Id Only")
    resolve_people(
        cfg,
        "ocean",
        client=FakeOA(authors=[_author("Id Only", orcid="", openalex="A77")]),
    )
    person = load_people(cfg, "ocean")[0]
    assert person.is_ok()
    assert person.orcid == ""
    assert person.openalex == "A77"
    client = FakeOA(works=[_work()])
    result = run_list(
        cfg, "ocean", console=console, client=client, backfill_from="2025-01-01"
    )
    assert result.proposed == 1
    assert client.work_calls[-1]["openalex"] == "A77"
    assert client.work_calls[-1]["orcid"] == ""


def test_affiliation_narrows_ambiguous_name(cfg):
    add_person(
        cfg,
        "ocean",
        display_name="Common Name",
        affiliation_host="stanford.edu",
    )
    resolve_people(
        cfg,
        "ocean",
        client=FakeOA(
            authors=[
                _author("Common Name", openalex="A1", inst="Elsewhere"),
                _author("Common Name", orcid=ORCID, openalex="A2", inst="Stanford"),
            ]
        ),
    )
    person = load_people(cfg, "ocean")[0]
    assert person.status == "ok"
    assert person.openalex == "A2"


def test_invalid_list_name(cfg):
    from paperful.authorwatch import AuthorwatchError

    try:
        save_list(cfg, "bad name")
        raise AssertionError("expected invalid name")
    except AuthorwatchError as exc:
        assert "Invalid list name" in str(exc)


def test_openalex_client_author_filters():
    from paperful.snowball.openalex import OpenAlexClient

    seen: list[tuple[str, dict]] = []

    def getter(path, query):
        seen.append((path, dict(query)))
        return {"results": [], "meta": {"count": 0}}

    client = OpenAlexClient(email="t@example.org", api_key="", sleep_s=0, getter=getter)
    client.search_authors("Josiah Carberry", limit=3)
    assert seen[-1][0] == "/authors"
    assert seen[-1][1]["search"] == "Josiah Carberry"
    client.works_by_author(
        orcid=ORCID, limit=5, from_publication_date="2025-01-01"
    )
    filt = seen[-1][1]["filter"]
    assert f"author.orcid:{ORCID}" in filt
    assert "from_publication_date:2025-01-01" in filt
    client.works_by_author(openalex="A123", limit=5, from_created_date="2026-02-03")
    filt = seen[-1][1]["filter"]
    assert "author.id:A123" in filt
    assert "from_created_date:2026-02-03" in filt
    assert "cited_by_count" in seen[0][1]["select"]


def test_load_collection_items_passes_scope_kwargs(cfg, monkeypatch):
    from paperful import authorwatch_suggest as sug
    from paperful import cli as cli_mod

    class FakeLoaded:
        items = [make_item(key="X1")]

    seen: dict = {}

    def fake_load(backend, *, json_out=False, **scope):
        seen.update(scope)
        seen["json_out"] = json_out
        return FakeLoaded()

    monkeypatch.setattr(cli_mod, "_connect", lambda cfg, quiet=False: object())
    monkeypatch.setattr(cli_mod, "_load_scope", fake_load)
    items = sug.load_collection_items(cfg, "AO/Coffee")
    assert len(items) == 1
    assert seen["collection"] == ["AO/Coffee"]
    assert seen["library"] is False
    assert seen["year_from"] is None
    assert seen["item_type"] == []


def test_suggest_corpus_accept_delete(cfg):
    save_list(cfg, "lab")
    items = [
        make_item(
            key="A1",
            creator_surnames=["Wonder"],
            first_author="Alice Wonder",
        ),
        make_item(
            key="A2",
            creator_surnames=["Wonder"],
            first_author="Alice Wonder",
        ),
        make_item(
            key="B1",
            creator_surnames=["Smith"],
            first_author="Bob Smith",
        ),
    ]
    rows = suggest_people(
        cfg,
        "lab",
        collection="Col",
        method="corpus",
        limit=5,
        items=items,
    )
    assert rows
    assert any("Wonder" in row.display_name for row in rows)
    accepted = accept_suggestions(cfg, "lab", ids={rows[0].id})
    assert len(accepted) == 1
    assert len(load_people(cfg, "lab")) == 1
    pending = [r for r in load_suggestions(cfg, "lab") if r.status == "pending"]
    assert pending
    from paperful.authorwatch import AuthorwatchError

    try:
        delete_list(cfg, "lab")
        raise AssertionError("expected confirm")
    except AuthorwatchError:
        pass
    delete_list(cfg, "lab", yes=True)
    assert not (cfg.state_dir / "authorwatch" / "lab").exists()


def test_suggest_most_cited_and_mix(cfg):
    save_list(cfg, "lab")
    items = [
        make_item(key="A1", creator_surnames=["Wonder"], first_author="Alice Wonder"),
        make_item(key="B1", creator_surnames=["Smith"], first_author="Bob Smith"),
    ]

    class NameOA(FakeOA):
        def search_authors(self, name: str, *, limit: int = 8):
            self.search_calls.append(name)
            if "Wonder" in name:
                return [
                    {
                        "id": "https://openalex.org/A9",
                        "display_name": "Alice Wonder",
                        "orcid": f"https://orcid.org/{ORCID}",
                        "cited_by_count": 900,
                        "last_known_institutions": [],
                        "works_count": 10,
                    }
                ]
            if "Smith" in name:
                return [
                    {
                        "id": "https://openalex.org/A8",
                        "display_name": "Bob Smith",
                        "orcid": "https://orcid.org/0000-0001-2345-6789",
                        "cited_by_count": 10,
                        "last_known_institutions": [],
                        "works_count": 2,
                    }
                ]
            return []

    client = NameOA()
    rows = suggest_people(
        cfg,
        "lab",
        collection="Col",
        method="most_cited",
        limit=5,
        items=items,
        client=client,
    )
    assert rows
    alice = next(r for r in rows if "Wonder" in r.display_name)
    assert alice.pollable
    assert alice.orcid == ORCID
    assert alice.score >= next(r for r in rows if "Smith" in r.display_name).score
    mix = suggest_people(
        cfg,
        "lab2",
        collection="Col",
        method="mix",
        limit=5,
        items=items,
        client=client,
    )
    assert mix
    assert mix[0].method == "mix"


def test_suggest_coauthor_from_works(cfg):
    save_list(cfg, "lab")
    add_person(cfg, "lab", orcid=ORCID, display_name="Seed Author")
    work = {
        "id": "https://openalex.org/W9",
        "doi": "https://doi.org/10.1000/co",
        "display_name": "Joint paper",
        "publication_year": 2024,
        "type": "article",
        "cited_by_count": 2,
        "language": "en",
        "authorships": [
            {
                "author": {
                    "id": "https://openalex.org/Aseed",
                    "display_name": "Seed Author",
                    "orcid": f"https://orcid.org/{ORCID}",
                }
            },
            {
                "author": {
                    "id": "https://openalex.org/Aco",
                    "display_name": "Co Author",
                    "orcid": "https://orcid.org/0000-0001-2345-6789",
                }
            },
        ],
        "primary_location": {},
        "open_access": {"is_oa": True},
    }
    client = FakeOA(works=[work])
    rows = suggest_people(
        cfg,
        "lab",
        collection="Col",
        method="coauthor",
        limit=5,
        items=[],
        client=client,
    )
    assert any(r.openalex == "Aco" or "Co Author" in r.display_name for r in rows)


def test_accept_openalex_only_and_dismiss_rest(cfg):
    from paperful.authorwatch import append_suggestions
    from paperful.authorwatch_suggest import Suggestion

    save_list(cfg, "lab")
    append_suggestions(
        cfg,
        "lab",
        [
            Suggestion(
                id="sug_oa",
                display_name="OA Only",
                openalex="A77",
                pollable=True,
            ),
            Suggestion(
                id="sug_skip",
                display_name="Skip Me",
                orcid=ORCID,
                pollable=True,
            ),
        ],
    )
    accepted = accept_suggestions(
        cfg, "lab", ids={"sug_oa"}, dismiss_rest=True
    )
    assert len(accepted) == 1
    assert accepted[0].openalex == "A77"
    assert accepted[0].is_ok()
    statuses = {r.id: r.status for r in load_suggestions(cfg, "lab")}
    assert statuses["sug_oa"] == "accepted"
    assert statuses["sug_skip"] == "dismissed"


def test_cli_accept_seed_from(cfg, monkeypatch):
    from paperful.authorwatch import append_suggestions
    from paperful.authorwatch_suggest import Suggestion

    save_list(cfg, "lab")
    append_suggestions(
        cfg,
        "lab",
        [
            Suggestion(
                id="sug_seed",
                display_name="Josiah Carberry",
                orcid=ORCID,
                pollable=True,
            )
        ],
    )
    called: list[str] = []

    def fake_run(cfg, name, *, console, backfill_from=None, **kwargs):
        called.append(backfill_from or "")
        class R:
            proposed = 0
        return R()

    monkeypatch.setattr("paperful.authorwatch.run_list", fake_run)
    monkeypatch.setattr("paperful.cli._cfg", lambda _p=None: cfg)
    result = runner.invoke(
        app,
        [
            "authorwatch",
            "accept",
            "lab",
            "--id",
            "sug_seed",
            "--seed-from",
            "2025-01-01",
        ],
    )
    assert result.exit_code == 0, result.output
    assert called == ["2025-01-01"]
    assert load_people(cfg, "lab")


def test_social_html_import(cfg, tmp_path):
    html = (
        Path(__file__).resolve().parent / "fixtures" / "authorwatch" / "rg-follows.html"
    )
    save_list(cfg, "social")
    added = import_file(cfg, "social", path=html, source="rg", resolve=False)
    assert len(added) == 2
    names = {row.display_name for row in added}
    assert "Josiah Carberry" in names


def test_parse_social_csv_orcid(tmp_path):
    path = tmp_path / "follows.csv"
    path.write_text("name,orcid\nJosiah Carberry,0000-0002-1825-0097\n", encoding="utf-8")
    rows = parse_social_file(path, source="rg")
    assert rows[0].orcid == "0000-0002-1825-0097"


def test_update_person(cfg):
    save_list(cfg, "lab")
    person = add_person(cfg, "lab", display_name="Jane")
    update_person(cfg, "lab", person.id, display_name="Jane Q", affiliation_host="mit.edu")
    refreshed = load_people(cfg, "lab")[0]
    assert refreshed.display_name == "Jane Q"
    assert refreshed.affiliation_host == "mit.edu"
