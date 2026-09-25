"""Duplicate classification and gap counts. No live Zotero or network."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from paperful import cli
from paperful.dedupe import (
    DedupeGroup,
    actionable_groups,
    apply_merge,
    classify,
    merge_parent_patch,
    plan_child_moves,
    summarize_gaps,
    write_pack,
)
from paperful.library import LibraryError, ZoteroBackend
from paperful.zot import Collection, item_from_json
from tests.conftest import make_item

runner = CliRunner()

SAME = "The BBNJ agreement and marine biodiversity beyond national jurisdiction"
OTHER = "A completely different paper about fisheries subsidies in coastal states"


def _pair(**overrides):
    base = dict(
        title=SAME,
        doi="10.1000/bbnj.1",
        year=2023,
        date="2023",
        creator_count=1,
        date_added="2020-01-01T00:00:00Z",
    )
    base.update(overrides)
    return make_item(**base)


def test_high_doi_prefers_stored_pdf_over_link_over_bare():
    items = [
        _pair(key="BARE", has_pdf=False, has_linked_url=False, date_added="2010-01-01T00:00:00Z"),
        _pair(key="LINK", has_pdf=False, has_linked_url=True, date_added="2011-01-01T00:00:00Z"),
        _pair(key="PDF", has_pdf=True, has_linked_url=False, date_added="2019-01-01T00:00:00Z"),
    ]
    groups = classify(items, "high_doi")
    assert len(groups) == 1
    assert groups[0].keep == "PDF"
    assert set(groups[0].trash) == {"BARE", "LINK"}
    assert groups[0].held is False
    assert groups[0].reason == "doi"


def test_older_date_added_breaks_ties():
    items = [
        _pair(key="NEW", date_added="2024-06-01T00:00:00Z"),
        _pair(key="OLD", date_added="2018-01-01T00:00:00Z"),
    ]
    groups = classify(items)
    assert groups[0].keep == "OLD"
    assert groups[0].trash == ["NEW"]


def test_richer_metadata_before_date_added():
    items = [
        _pair(key="THIN", creator_count=0, date=None, year=None, date_added="2010-01-01T00:00:00Z"),
        _pair(key="RICH", creator_count=3, date_added="2024-01-01T00:00:00Z"),
    ]
    groups = classify(items, "high_doi")
    assert groups[0].keep == "RICH"


def test_doi_prefix_groups_together():
    items = [
        _pair(key="A", doi="https://doi.org/10.1000/BBNJ.1"),
        _pair(key="B", doi="10.1000/bbnj.1"),
    ]
    groups = classify(items, "high_doi")
    assert len(groups) == 1
    assert groups[0].doi == "10.1000/bbnj.1"


def test_divergent_titles_are_held():
    items = [
        _pair(key="A", title=SAME),
        _pair(key="B", title=OTHER, has_pdf=False),
    ]
    groups = classify(items, "high_doi")
    assert len(groups) == 1
    assert groups[0].held is True
    assert groups[0].reason == "held_divergent_title"
    assert groups[0].trash == []
    assert groups[0].keep is None


def test_html_entity_titles_are_not_divergent():
    items = [
        _pair(key="A", title="Fish &amp; ships in the high seas agreement text"),
        _pair(key="B", title="Fish & ships in the high seas agreement text", has_pdf=True),
    ]
    groups = classify(items, "high_doi")
    assert groups[0].held is False
    assert groups[0].keep == "B"


def test_medium_skips_items_already_in_a_doi_group():
    doi_dupes = [
        _pair(key="A", has_pdf=True),
        _pair(key="B"),
    ]
    title_dupes = [
        make_item(
            key="C",
            doi=None,
            title=SAME,
            year=2023,
            date="2023",
        ),
        make_item(
            key="D",
            doi=None,
            title=SAME,
            year=2023,
            date="2023",
        ),
    ]
    groups = classify(doi_dupes + title_dupes, "all")
    phases = {g.phase for g in groups}
    assert phases == {"high_doi", "medium_title_year"}
    medium = next(g for g in groups if g.phase == "medium_title_year")
    assert medium.needs_review is True
    assert set(medium.trash + [medium.keep]) == {"C", "D"}
    assert "A" not in medium.trash and "B" not in medium.trash


def test_unique_doi_can_match_missing_doi_on_title_year():
    items = [
        _pair(key="DOI", doi="10.9999/only"),
        make_item(key="NONE", doi=None, title=SAME, year=2023, date="2023"),
    ]
    groups = classify(items, "all")
    assert len(groups) == 1
    assert groups[0].phase == "medium_title_year"
    assert groups[0].needs_review is True


def test_apply_skips_medium_and_held(tmp_path):
    items = [
        _pair(key="KEEP", has_pdf=True),
        _pair(key="DROP"),
        _pair(key="HELD1", doi="10.1000/other", title=SAME),
        _pair(key="HELD2", doi="10.1000/other", title=OTHER),
        make_item(key="M1", doi=None, title="Grey report on area based tools", year=2021),
        make_item(key="M2", doi=None, title="Grey report on area based tools", year=2021),
    ]
    groups = classify(items)
    trashed: list[str] = []

    class Backend:
        def merge_into(self, keep: str, drop: str) -> dict:
            trashed.append(drop)
            return {"moved": [], "fields": []}

    n, errors = apply_merge(
        Backend(),
        groups,
        apply_medium=False,
        audit_path=tmp_path / "dedupe-applied.jsonl",
        scope="BBNJ",
        pack=tmp_path / "pack.json",
    )
    assert errors == []
    assert "DROP" in trashed
    assert "M1" not in trashed and "M2" not in trashed
    assert "HELD1" not in trashed and "HELD2" not in trashed
    assert n == 1


def test_apply_medium_trashes_and_audits(tmp_path):
    items = [
        make_item(key="M1", doi=None, title="Grey report on area based tools", year=2021, has_pdf=True),
        make_item(key="M2", doi=None, title="Grey report on area based tools", year=2021),
    ]
    groups = classify(items, "medium_title_year")
    audit = tmp_path / "dedupe-applied.jsonl"
    trashed: list[str] = []

    class Backend:
        def merge_into(self, keep: str, drop: str) -> dict:
            trashed.append(drop)
            return {"moved": [], "fields": []}

    n, errors = apply_merge(
        Backend(),
        groups,
        apply_medium=True,
        audit_path=audit,
        scope="BBNJ",
        pack=tmp_path / "pack.json",
    )
    assert n == 1 and errors == []
    assert trashed == ["M2"]
    line = json.loads(audit.read_text().strip())
    assert line["drop"] == "M2" and line["keep"] == "M1"
    assert line["phase"] == "medium_title_year"


def test_dry_run_pack_does_not_need_a_backend(tmp_path):
    items = [
        _pair(key="KEEP", has_pdf=True),
        _pair(key="DROP"),
    ]
    groups = classify(items)
    json_path, md_path = write_pack(
        tmp_path, "BBNJ", groups, phase="all", n_items=2, stamp="20260918T120000Z"
    )
    payload = json.loads(json_path.read_text())
    assert payload["schema"] == "paperful.dedupe_pack.v1"
    assert payload["counts"]["trash_candidates"] == 1
    assert payload["groups"][0]["keep"] == "KEEP"
    text = md_path.read_text()
    assert "DROP" in text
    assert "Held: 0" in text


def test_summarize_gaps():
    items = [
        make_item(key="A", has_pdf=True, doi="10.1/a"),
        make_item(key="B", has_pdf=False, has_linked_url=True, doi=None),
        make_item(key="C", has_pdf=False, doi=None),
    ]
    gaps = summarize_gaps(items)
    assert gaps.items == 3
    assert gaps.no_stored_pdf == 2
    assert gaps.linked_url_only == 1
    assert gaps.missing_doi == 2


def test_item_from_json_dedupe_fields():
    item = item_from_json(
        {
            "key": "K",
            "data": {
                "itemType": "journalArticle",
                "title": "T",
                "collections": [],
                "creators": [
                    {"creatorType": "author", "lastName": "A"},
                    {"creatorType": "author", "lastName": "B"},
                ],
                "dateAdded": "2019-01-01T00:00:00Z",
                "date": "2019",
                "DOI": "10.1000/x",
            },
        },
        {},
        None,
        has_pdf=False,
        has_linked_url=True,
    )
    assert item.creator_count == 2
    assert item.date_added == "2019-01-01T00:00:00Z"
    assert item.has_linked_url is True


def test_trash_item_sets_deleted(cfg):
    class FakeZot:
        def __init__(self):
            self.updated = None

        def item(self, key):
            return {"data": {"key": key, "title": "T", "version": 1}}

        def update_item(self, raw):
            self.updated = raw

    class ZL:
        def __init__(self):
            self.zot = FakeZot()

    backend = ZoteroBackend(cfg, ZL())
    backend._ensure_write = lambda: None
    backend.trash_item("DROP")
    assert backend.zl.zot.updated["data"]["deleted"] is True


def test_cli_dedupe_dry_run_writes_pack(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n'
    )

    class Stub:
        def ping(self):
            return {
                "zotero_version": "10.0.1",
                "api_version": "3",
                "supports_write": True,
            }

        def resolve_collection(self, spec):
            return Collection("2DBKZRPC", "BBNJ", None, "BBNJ", "BBNJ")

        def subtree_keys(self, root):
            return [root.key]

        def items_in_scope(self, keys):
            return [
                _pair(key="KEEP", has_pdf=True),
                _pair(key="DROP", doi="HTTPS://DOI.ORG/10.1000/bbnj.1"),
                _pair(key="H1", doi="10.1000/split", title=SAME),
                _pair(key="H2", doi="10.1000/split", title=OTHER),
            ]

    monkeypatch.setattr(cli, "ZoteroLocal", lambda *a, **k: Stub())
    res = runner.invoke(
        cli.app,
        ["dedupe", "-c", str(cfg_file), "-C", "2DBKZRPC", "--dry-run", "--json"],
    )
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    assert payload["applied"] == 0
    assert payload["counts"]["held"] == 1
    assert payload["counts"]["trash_candidates"] == 1
    pack = json.loads(Path(payload["pack"]).read_text())
    reasons = {g["reason"] for g in pack["groups"]}
    assert "doi" in reasons and "held_divergent_title" in reasons
    assert Path(payload["markdown"]).is_file()
    assert not (tmp_path / "state" / "dedupe-applied.jsonl").exists()
    assert not list((tmp_path / "out").rglob("*"))


def test_cli_apply_trashes_only_high_doi(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n'
    )
    trashed: list[str] = []

    class Stub:
        def ping(self):
            return {
                "zotero_version": "10.0.1",
                "api_version": "3",
                "supports_write": True,
            }

        def resolve_collection(self, spec):
            return Collection("2DBKZRPC", "BBNJ", None, "BBNJ", "BBNJ")

        def subtree_keys(self, root):
            return [root.key]

        def items_in_scope(self, keys):
            return [
                _pair(key="KEEP", has_pdf=True),
                _pair(key="DROP"),
                make_item(
                    key="M1",
                    doi=None,
                    title="Grey report on area based tools",
                    year=2021,
                    has_pdf=True,
                ),
                make_item(
                    key="M2",
                    doi=None,
                    title="Grey report on area based tools",
                    year=2021,
                ),
            ]

    monkeypatch.setattr(cli, "ZoteroLocal", lambda *a, **k: Stub())
    monkeypatch.setattr(
        ZoteroBackend,
        "merge_into",
        lambda self, keep, drop: trashed.append(drop) or {"moved": [], "fields": []},
    )
    kept = tmp_path / "out" / "BBNJ" / "keep.pdf"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"%PDF-1.4 kept")
    res = runner.invoke(
        cli.app, ["dedupe", "-c", str(cfg_file), "-C", "BBNJ", "--apply"]
    )
    assert res.exit_code == 0, res.stdout
    assert trashed == ["DROP"]
    audit = (tmp_path / "state" / "dedupe-applied.jsonl").read_text()
    assert "DROP" in audit and "M2" not in audit
    assert kept.read_bytes() == b"%PDF-1.4 kept"


def test_medium_skips_placeholder_titles_and_missing_years():
    items = [
        make_item(key="A", doi=None, title="(untitled)", year=2020),
        make_item(key="B", doi=None, title="(untitled)", year=2020),
        make_item(key="C", doi=None, title="", year=2020),
        make_item(
            key="D",
            doi=None,
            title="A real grey literature report title",
            year=None,
        ),
        make_item(
            key="E",
            doi=None,
            title="A real grey literature report title",
            year=None,
        ),
    ]
    assert classify(items, "medium_title_year") == []


def test_phase_high_doi_ignores_title_year_pairs():
    items = [
        make_item(key="C", doi=None, title=SAME, year=2023, date="2023"),
        make_item(key="D", doi=None, title=SAME, year=2023, date="2023"),
    ]
    assert classify(items, "high_doi") == []


def test_classify_rejects_unknown_phase():
    try:
        classify([], "nope")
    except ValueError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_actionable_runs_high_doi_before_medium():
    medium = DedupeGroup(
        phase="medium_title_year",
        reason="title_year",
        keep="M1",
        trash=["M2"],
        held=False,
        needs_review=True,
    )
    high = DedupeGroup(
        phase="high_doi",
        reason="doi",
        keep="H1",
        trash=["H2"],
        held=False,
        needs_review=False,
    )
    held = DedupeGroup(
        phase="high_doi",
        reason="held_divergent_title",
        keep=None,
        trash=["NO"],
        held=True,
        needs_review=True,
    )
    chosen = actionable_groups([medium, held, high], apply_medium=True)
    assert [g.keep for g in chosen] == ["H1", "M1"]
    assert [g.keep for g in actionable_groups([medium, high], apply_medium=False)] == [
        "H1"
    ]


def test_apply_records_item_errors_and_reraises_library_error(tmp_path):
    groups = classify([_pair(key="KEEP", has_pdf=True), _pair(key="DROP"), _pair(key="BAD")])
    audit = tmp_path / "dedupe-applied.jsonl"

    class Flaky:
        def merge_into(self, keep: str, drop: str) -> dict:
            if drop == "BAD":
                raise RuntimeError("nope")
            return {"moved": [], "fields": []}

    n, errors = apply_merge(
        Flaky(),
        groups,
        apply_medium=False,
        audit_path=audit,
        scope="BBNJ",
        pack=tmp_path / "pack.json",
    )
    assert n == 1
    assert errors == ["BAD: nope"]
    assert "BAD" not in audit.read_text()
    assert "DROP" in audit.read_text()

    class Denied:
        def merge_into(self, keep: str, drop: str) -> dict:
            raise LibraryError("write authorisation denied in Zotero")

    try:
        apply_merge(
            Denied(),
            groups,
            apply_medium=False,
            audit_path=tmp_path / "other.jsonl",
            scope="BBNJ",
            pack=tmp_path / "pack.json",
        )
    except LibraryError as exc:
        assert "authorisation" in str(exc)
    else:
        raise AssertionError("expected LibraryError")


def _cfg_and_stub(tmp_path, monkeypatch, items, *, write=True):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n'
    )

    class Stub:
        def ping(self):
            return {
                "zotero_version": "10.0.1",
                "api_version": "3",
                "supports_write": write,
            }

        def resolve_collection(self, spec):
            return Collection("2DBKZRPC", "BBNJ", None, "BBNJ", "BBNJ")

        def subtree_keys(self, root):
            return [root.key]

        def items_in_scope(self, keys):
            return list(items)

    monkeypatch.setattr(cli, "ZoteroLocal", lambda *a, **k: Stub())
    return cfg_file


def test_cli_omitting_apply_is_a_dry_run(tmp_path, monkeypatch):
    cfg_file = _cfg_and_stub(
        tmp_path,
        monkeypatch,
        [_pair(key="KEEP", has_pdf=True), _pair(key="DROP")],
    )

    def boom(self, keep, drop):
        raise AssertionError(f"merged {drop}")

    monkeypatch.setattr(ZoteroBackend, "merge_into", boom)
    res = runner.invoke(cli.app, ["dedupe", "-c", str(cfg_file), "-C", "BBNJ"])
    assert res.exit_code == 0, res.stdout
    assert "Dry-run" in res.stdout
    assert not (tmp_path / "state" / "dedupe-applied.jsonl").exists()
    packs = list((tmp_path / "state" / "dedupe-packs").glob("*.json"))
    assert len(packs) == 1


def test_cli_rejects_dry_run_with_apply(tmp_path, monkeypatch):
    cfg_file = _cfg_and_stub(tmp_path, monkeypatch, [])
    res = runner.invoke(
        cli.app,
        ["dedupe", "-c", str(cfg_file), "-C", "BBNJ", "--dry-run", "--apply"],
    )
    assert res.exit_code == 1
    assert "not both" in res.stdout


def test_cli_unknown_phase(tmp_path, monkeypatch):
    cfg_file = _cfg_and_stub(tmp_path, monkeypatch, [])
    res = runner.invoke(
        cli.app, ["dedupe", "-c", str(cfg_file), "-C", "BBNJ", "--phase", "nope"]
    )
    assert res.exit_code == 1
    assert "Unknown phase" in res.stdout


def test_cli_apply_without_write_api_exits_2(tmp_path, monkeypatch):
    cfg_file = _cfg_and_stub(
        tmp_path,
        monkeypatch,
        [_pair(key="KEEP", has_pdf=True), _pair(key="DROP")],
        write=False,
    )
    res = runner.invoke(
        cli.app, ["dedupe", "-c", str(cfg_file), "-C", "BBNJ", "--apply"]
    )
    assert res.exit_code == 2, res.stdout
    assert "Zotero 10+" in res.stdout
    assert (tmp_path / "state" / "dedupe-packs").is_dir()
    assert not (tmp_path / "state" / "dedupe-applied.jsonl").exists()


def test_cli_limit_slices_before_classify(tmp_path, monkeypatch):
    cfg_file = _cfg_and_stub(
        tmp_path,
        monkeypatch,
        [
            _pair(key="KEEP", has_pdf=True),
            _pair(key="DROP"),
            _pair(key="OTHER", doi="10.1000/second"),
            _pair(key="OTHER2", doi="10.1000/second"),
        ],
    )
    res = runner.invoke(
        cli.app,
        ["dedupe", "-c", str(cfg_file), "-C", "BBNJ", "--limit", "2", "--json"],
    )
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    assert payload["counts"]["items"] == 2
    assert payload["counts"]["groups"] == 1
    assert payload["counts"]["trash_candidates"] == 1


def test_cli_gaps_json(tmp_path, monkeypatch):
    cfg_file = _cfg_and_stub(
        tmp_path,
        monkeypatch,
        [
            make_item(key="A", has_pdf=True, doi="10.1/a"),
            make_item(key="B", has_pdf=False, has_linked_url=True, doi=None),
        ],
    )
    res = runner.invoke(
        cli.app, ["gaps", "-c", str(cfg_file), "-C", "BBNJ", "--json"]
    )
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    assert payload["items"] == 2
    assert payload["no_stored_pdf"] == 1
    assert payload["linked_url_only"] == 1
    assert payload["missing_doi"] == 1
    assert "run" not in res.stdout  # json only, no table


def test_merge_fields_fill_blanks_and_better_text():
    patch = merge_parent_patch(
        {
            "title": "scan.pdf",
            "abstractNote": "short",
            "DOI": "",
            "creators": [{"creatorType": "author", "lastName": "Ada"}],
            "publicationTitle": "",
            "dateAdded": "2020-02-01T00:00:00Z",
            "collections": ["A"],
            "tags": [{"tag": "auto", "type": 1}],
            "relations": {},
        },
        {
            "title": "The real title",
            "abstractNote": "a much longer abstract",
            "DOI": "10.1000/x",
            "creators": [
                {"creatorType": "author", "lastName": "Ada"},
                {"creatorType": "author", "lastName": "Byron"},
            ],
            "publicationTitle": "Nature",
            "dateAdded": "2019-01-01T00:00:00Z",
            "collections": ["B"],
            "tags": [{"tag": "auto", "type": 0}, {"tag": "review", "type": 0}],
            "relations": {"dc:relation": ["http://example.test/items/DROP"]},
        },
    )
    assert patch["fields"]["title"] == "The real title"
    assert patch["fields"]["abstractNote"] == "a much longer abstract"
    assert patch["fields"]["DOI"] == "10.1000/x"
    assert len(patch["fields"]["creators"]) == 2
    assert patch["fields"]["publicationTitle"] == "Nature"
    assert patch["date_added"] == "2019-01-01T00:00:00Z"
    assert patch["collections"] == ["A", "B"]
    assert {t["tag"]: t["type"] for t in patch["tags"]}["auto"] == 0
    assert "review" in {t["tag"] for t in patch["tags"]}


def test_merge_fields_leave_conflicting_doi_and_unrelated_creators():
    patch = merge_parent_patch(
        {
            "title": "Same title",
            "DOI": "10.1000/keep",
            "creators": [{"creatorType": "author", "lastName": "Ada"}],
            "abstractNote": "keeper abstract wins when longer than donor",
        },
        {
            "title": "Same title",
            "DOI": "10.1000/drop",
            "creators": [{"creatorType": "author", "lastName": "Other"}],
            "abstractNote": "short",
        },
    )
    assert "DOI" not in patch["fields"]
    assert "creators" not in patch["fields"]
    assert "abstractNote" not in patch["fields"]
    assert "title" not in patch["fields"]


def test_plan_child_moves_reparents_notes_and_collapses_same_pdf():
    keep = [
        {
            "key": "KPDF",
            "data": {
                "itemType": "attachment",
                "contentType": "application/pdf",
                "linkMode": "imported_file",
                "md5": "abc",
            },
        }
    ]
    drop = [
        {
            "key": "NOTE",
            "data": {"itemType": "note", "note": "hello"},
        },
        {
            "key": "DPDF",
            "data": {
                "itemType": "attachment",
                "contentType": "application/pdf",
                "linkMode": "imported_file",
                "md5": "abc",
            },
        },
        {
            "key": "URL",
            "data": {
                "itemType": "attachment",
                "contentType": "application/pdf",
                "linkMode": "linked_url",
                "url": "https://example.test/a.pdf",
            },
        },
    ]
    moves = plan_child_moves(keep, drop, {"KPDF": 0, "DPDF": 0})
    by_key = {row["key"]: row["action"] for row in moves}
    assert by_key["NOTE"] == "reparent"
    assert by_key["DPDF"] == "trash"
    assert by_key["URL"] == "reparent"

    annotated = plan_child_moves(keep, drop[:2], {"KPDF": 0, "DPDF": 2})
    actions = [(row["key"], row["action"]) for row in annotated]
    assert ("KPDF", "trash") in actions
    assert ("DPDF", "reparent") in actions


def test_merge_into_moves_children_then_deletes_donor(cfg):
    items = {
        "KEEP": {
            "key": "KEEP",
            "data": {
                "key": "KEEP",
                "title": "file.pdf",
                "abstractNote": "",
                "DOI": "",
                "creators": [],
                "collections": ["A"],
                "tags": [],
                "relations": {},
                "version": 1,
            },
        },
        "DROP": {
            "key": "DROP",
            "data": {
                "key": "DROP",
                "title": "Real title",
                "abstractNote": "The abstract",
                "DOI": "10.1000/x",
                "creators": [{"creatorType": "author", "lastName": "Ada"}],
                "collections": ["B"],
                "tags": [{"tag": "oa", "type": 0}],
                "relations": {},
                "version": 2,
            },
        },
        "NOTE": {
            "key": "NOTE",
            "data": {
                "key": "NOTE",
                "itemType": "note",
                "parentItem": "DROP",
                "note": "hi",
            },
        },
        "PDF": {
            "key": "PDF",
            "data": {
                "key": "PDF",
                "itemType": "attachment",
                "contentType": "application/pdf",
                "linkMode": "imported_file",
                "parentItem": "DROP",
                "md5": "abc",
            },
        },
    }

    class FakeZot:
        def item(self, key):
            return items[key]

        def children(self, key):
            return [
                row
                for row in items.values()
                if (row.get("data") or {}).get("parentItem") == key
            ]

        def update_item(self, raw):
            items[raw["data"]["key"]] = raw

    class ZL:
        def __init__(self):
            self.zot = FakeZot()

    backend = ZoteroBackend(cfg, ZL())
    backend._ensure_write = lambda: None
    result = backend.merge_into("KEEP", "DROP")
    assert result["moved"] == ["NOTE", "PDF"]
    assert "title" in result["fields"]
    assert items["NOTE"]["data"]["parentItem"] == "KEEP"
    assert items["PDF"]["data"]["parentItem"] == "KEEP"
    assert items["DROP"]["data"]["deleted"] is True
    assert items["KEEP"]["data"]["title"] == "Real title"
    assert items["KEEP"]["data"]["abstractNote"] == "The abstract"
    assert items["KEEP"]["data"]["collections"] == ["A", "B"]


def test_merge_into_does_not_trash_when_child_move_fails(cfg):
    items = {
        "KEEP": {"key": "KEEP", "data": {"key": "KEEP", "title": "Keep", "version": 1}},
        "DROP": {"key": "DROP", "data": {"key": "DROP", "title": "Drop", "version": 1}},
        "NOTE": {
            "key": "NOTE",
            "data": {"key": "NOTE", "itemType": "note", "parentItem": "DROP", "note": "x"},
        },
    }

    class FakeZot:
        def item(self, key):
            return items[key]

        def children(self, key):
            return [
                row
                for row in items.values()
                if (row.get("data") or {}).get("parentItem") == key
            ]

        def update_item(self, raw):
            if raw["data"].get("key") == "NOTE":
                raise RuntimeError("child move failed")
            items[raw["data"]["key"]] = raw

    class ZL:
        def __init__(self):
            self.zot = FakeZot()

    backend = ZoteroBackend(cfg, ZL())
    backend._ensure_write = lambda: None
    try:
        backend.merge_into("KEEP", "DROP")
    except RuntimeError as exc:
        assert "child move" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
    assert items["DROP"]["data"].get("deleted") is not True

