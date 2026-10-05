"""Commands read the mirror. A closed manager costs write-back, not the read work."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paperful import cli
from paperful.catalogue import MirrorCatalogue, MirrorFirstBackend, open_library
from paperful.config import Config
from paperful.library import LibraryError, ZoteroBackend
from paperful.mirror import forget_index
from paperful.sync import run_sync, sync_state
from tests.conftest import make_item
from tests.test_cli import StubZL
from tests.test_sync import PDF, FakeZotero

runner = CliRunner()


@pytest.fixture(autouse=True)
def _fresh_index():
    forget_index()
    yield
    forget_index()


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(
        out_dir=tmp_path / "out", state_dir=tmp_path / "state", mirror_pdfs="lazy"
    )


def _library() -> FakeZotero:
    from paperful.zot import Collection

    zot = FakeZotero()
    zot.cols["COLC"] = Collection("COLC", "Sub", "COLA", "Alpha/Sub", "Alpha/Sub")
    zot.put("ITEM0001", title="In alpha", DOI="10.1000/one")
    zot.put("ITEM0002", title="In sub", collections=["COLC"])
    zot.put("ITEM0003", title="In beta", collections=["COLB"])
    zot.put("ITEM0004", title="In both", collections=["COLA", "COLB"])
    zot.attach("ITEM0001", "ATT00001")
    zot.note("ITEM0001", "NOTE0001", "<p>my note</p>")
    zot.rows["NOTE0001"]["data"]["tags"] = [{"tag": "paperful-summary"}]
    return zot


# ---- the catalogue -----------------------------------------------------------------


def test_catalogue_scopes_like_a_live_listing(cfg):
    zot = _library()
    run_sync(cfg, zot)
    cat = MirrorCatalogue(cfg.out_dir)
    assert sorted(c.path for c in cat.collections().values()) == [
        "Alpha",
        "Alpha/Sub",
        "Beta",
    ]
    alpha = cat.resolve_collection("Alpha")
    keys = cat.subtree_keys(alpha)
    assert sorted(keys) == ["COLA", "COLC"]
    scoped = cat.items_in_scope(keys)
    assert sorted(i.key for i in scoped) == ["ITEM0001", "ITEM0002", "ITEM0004"]
    both = next(i for i in scoped if i.key == "ITEM0004")
    assert both.collection_paths == ["Alpha"]  # Beta is outside this scope
    assert len(cat.items_in_scope(None)) == 4
    assert [i.key for i in cat.items_in_scope(["COLB"])] == ["ITEM0003", "ITEM0004"]
    assert cat.collection_counts() == {"COLA": (3, 2), "COLB": (2, 2), "COLC": (1, 1)}
    assert [i.key for i in cat.items_lacking_pdf(["COLA"])] == ["ITEM0004"]


def test_catalogue_leaves_out_items_that_left_the_library(cfg):
    zot = _library()
    run_sync(cfg, zot)
    zot.to_trash("ITEM0003")
    run_sync(cfg, zot)
    cat = MirrorCatalogue(cfg.out_dir)
    assert "ITEM0003" not in {i.key for i in cat.items_in_scope(None)}
    assert cat.get_item("ITEM0003") is None
    assert cat.get_item("ITEM0001").doi == "10.1000/one"
    assert cat.get_item("NOSUCH00") is None


def test_catalogue_children_notes_and_raw_payload(cfg):
    zot = _library()
    run_sync(cfg, zot)
    cat = MirrorCatalogue(cfg.out_dir)
    kinds = sorted(ch["data"]["itemType"] for ch in cat.children("ITEM0001"))
    assert kinds == ["attachment", "note"]
    assert cat.find_child_note_keys("ITEM0001", "paperful-summary") == ["NOTE0001"]
    assert cat.read_child_note("ITEM0001", "paperful-summary") == "<p>my note</p>"
    assert cat.find_child_note_keys("ITEM0001", "other-tag") == []
    assert cat.read_child_note("ITEM0002", "paperful-summary") is None
    raw = cat.raw_item("ITEM0001")
    assert raw["data"]["DOI"] == "10.1000/one"
    assert raw["data"]["collections"] == ["COLA"]
    assert raw["data"]["title"] == "In alpha"


def test_a_note_that_matches_the_disk_summary_keeps_its_key(cfg):
    """Without the key a re-run would not find the note and would post a second one."""
    zot = _library()
    cfg.summaries_dir.mkdir(parents=True)
    (cfg.summaries_dir / "ITEM0001.html").write_text("<p>disk summary</p>")
    run_sync(cfg, zot)
    cat = MirrorCatalogue(cfg.out_dir)
    assert cat.find_child_note_keys("ITEM0001", "paperful-summary") == ["NOTE0001"]


def test_merge_preview_from_the_mirror_matches_the_manager(cfg):
    zot = _library()
    zot.put("KEEP0001", title="A duplicated paper", DOI="10.1000/dup")
    zot.put("DROP0001", title="A duplicated paper", abstractNote="Only the copy has one.")
    zot.attach("KEEP0001", "ATTK0001")
    zot.attach("DROP0001", "ATTD0001")  # same bytes: the copy's file is redundant
    zot.note("DROP0001", "NOTED001")
    run_sync(cfg, zot)
    backend = MirrorFirstBackend(cfg, MirrorCatalogue(cfg.out_dir), None)
    preview = backend.preview_merge("KEEP0001", "DROP0001")
    assert preview["fields"] == ["abstractNote"]
    moves = {(m["key"], m["action"]) for m in preview["move"]}
    assert moves == {("ATTD0001", "trash"), ("NOTED001", "reparent")}
    assert backend.preview_merge("KEEP0001", "NOSUCH00")["move"] == []


# ---- opening the library ---------------------------------------------------------------


def test_open_library_refreshes_then_reads_the_mirror(cfg):
    zot = _library()
    said: list[str] = []
    backend = open_library(cfg, live=zot, status=said.append)
    assert any("First refresh" in line for line in said)
    assert sync_state(cfg.out_dir)["version"] == zot.version
    zot.calls.clear()
    assert len(backend.items_in_scope(None)) == 4
    assert backend.get_item("ITEM0001").has_pdf
    assert backend.children("ITEM0001")
    assert zot.reads() == 0 and zot.calls["changes"] == 0


def test_a_closed_manager_still_reads_and_refuses_writes(cfg):
    run_sync(cfg, _library())
    backend = open_library(cfg, offline=True)
    assert len(backend.items_in_scope(None)) == 4
    assert backend.supports_write() is False
    assert backend.ping()["offline"] is True
    assert backend.flush_writes() is None
    assert getattr(backend, "attachment_has_bytes", None) is None
    for write in (
        lambda: backend.apply_patch("ITEM0001", {"title": "x"}),
        lambda: backend.attach("ITEM0001", Path("x.pdf")),
        lambda: backend.create_or_update_note("ITEM0001", "<p>x</p>", "t"),
        lambda: backend.trash_item("ITEM0001"),
        lambda: backend.create_parent({"title": "x"}),
    ):
        with pytest.raises(LibraryError, match="not reachable"):
            write()


def test_no_manager_and_no_mirror_is_an_error(cfg):
    with pytest.raises(LibraryError):
        open_library(cfg)  # no Zotero in tests: see conftest
    with pytest.raises(LibraryError):
        open_library(cfg, offline=True)


def test_a_failed_refresh_falls_back_to_the_mirror_and_says_so(cfg):
    zot = _library()
    open_library(cfg, live=zot)
    zot.put("ITEM0009", title="Not seen yet")
    zot.fail.add("changes")
    said: list[str] = []
    backend = open_library(cfg, live=zot, status=said.append)
    assert any("Could not refresh" in line for line in said)
    assert len(backend.items_in_scope(None)) == 4


def test_manual_refresh_does_not_ask_the_manager(cfg):
    zot = _library()
    open_library(cfg, live=zot)
    cfg.mirror_refresh = "manual"
    zot.put("ITEM0009", title="Not seen yet")
    zot.calls.clear()
    backend = open_library(cfg, live=zot)
    assert zot.calls["changes"] == 0
    assert len(backend.items_in_scope(None)) == 4


def test_writes_go_to_the_manager_and_show_up_in_the_next_read(cfg):
    zot = _library()

    def apply_patch(key, fields):
        zot.put(key, **fields)

    zot.apply_patch = apply_patch
    zot.item_from_raw = None  # the wrapper falls back to get_item
    zot.get_item = lambda key: MirrorCatalogue(cfg.out_dir).get_item(key)
    zot.collections = lambda: dict(zot.cols)
    backend = open_library(cfg, live=zot)
    backend.apply_patch("ITEM0001", {"title": "Patched"})
    assert zot.rows["ITEM0001"]["data"]["title"] == "Patched"
    assert backend.raw_item("ITEM0001")["data"]["title"] == "Patched"


def test_export_pdf_prefers_the_mirror(cfg, tmp_path):
    zot = _library()
    run_sync(cfg, zot, pdfs="all")
    zot.calls.clear()
    backend = MirrorFirstBackend(cfg, MirrorCatalogue(cfg.out_dir), zot)
    item = backend.get_item("ITEM0001")
    dest = tmp_path / "bundle" / "x.pdf"
    assert backend.export_pdf(item, dest) == dest and dest.read_bytes() == PDF
    assert zot.calls["export_pdf"] == 0
    assert MirrorFirstBackend(cfg, MirrorCatalogue(cfg.out_dir), None).export_pdf(
        backend.get_item("ITEM0002"), tmp_path / "none.pdf"
    ) is None


# ---- the commands -----------------------------------------------------------------------


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n[mirror]\npdfs = "lazy"\n'
    )
    return p


class CountingZL(StubZL):
    """The stub library, counting what a command asks of it."""

    def __init__(self):
        super().__init__()
        self.listings = 0
        self.scope_reads = 0

    def listing(self, path, **params):
        if path == "/items":
            self.listings += 1
        return super().listing(path, **params)

    def items_in_scope(self, keys):
        # ``keys`` is None when the stub builds its own listing rows.
        if keys is not None:
            self.scope_reads += 1
        return super().items_in_scope(keys)


@pytest.fixture
def library(monkeypatch):
    zl = CountingZL()
    monkeypatch.setattr(cli, "ZoteroLocal", lambda *a, **k: zl)
    return zl


def _close_manager(monkeypatch):
    class Down:
        def __init__(self, *a, **k):
            pass

        def ping(self):
            raise ConnectionError("Zotero is not running")

    monkeypatch.setattr(cli, "ZoteroLocal", Down)


READ_VERBS = [
    ["collections"],
    ["gaps", "-C", "BBNJ", "--json"],
    ["lint", "-C", "BBNJ", "--json"],
    ["fix-metadata", "-C", "BBNJ"],
    ["dedupe", "-C", "BBNJ", "--json"],
    ["versions", "-C", "BBNJ", "--json"],
    ["export", "OUT.ris", "-C", "BBNJ"],
    ["ocr", "-C", "BBNJ"],
    ["run", "-C", "BBNJ", "--dry-run"],
    ["authorwatch", "save", "ocean-people"],
]


@pytest.mark.parametrize("argv", READ_VERBS, ids=[a[0] for a in READ_VERBS])
def test_read_verbs_work_with_the_manager_closed(
    argv, cfg_file, library, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "paperful.lint.prepare_identifiers", lambda *a, **k: [], raising=False
    )
    first = runner.invoke(cli.app, ["gaps", "-C", "BBNJ", "--json", "-c", str(cfg_file)])
    assert first.exit_code == 0, first.stdout
    _close_manager(monkeypatch)
    forget_index()
    argv = [str(tmp_path / "out.ris") if a == "OUT.ris" else a for a in argv]
    res = runner.invoke(cli.app, [*argv, "-c", str(cfg_file)])
    assert res.exit_code == 0, res.stdout


WRITE_VERBS = [
    ["fix-metadata", "-C", "BBNJ", "--apply"],
    ["attach"],
    ["snapshot", "-C", "BBNJ"],
    ["sync"],
    ["restore", "-C", "BBNJ"],
    ["attachments", "-C", "BBNJ"],
    ["authorwatch", "apply", "ocean-people", "-C", "BBNJ", "--apply"],
]


@pytest.mark.parametrize("argv", WRITE_VERBS, ids=[" ".join(a[:1] + a[3:]) for a in WRITE_VERBS])
def test_verbs_that_need_the_manager_exit_2_when_it_is_closed(
    argv, cfg_file, library, monkeypatch
):
    monkeypatch.setattr(
        "paperful.lint.prepare_identifiers", lambda *a, **k: [], raising=False
    )
    assert runner.invoke(cli.app, ["gaps", "-C", "BBNJ", "-c", str(cfg_file)]).exit_code == 0
    _close_manager(monkeypatch)
    res = runner.invoke(cli.app, [*argv, "-c", str(cfg_file)])
    assert res.exit_code == 2, res.stdout


def test_offline_flag_never_contacts_the_manager(cfg_file, library, monkeypatch):
    assert runner.invoke(cli.app, ["gaps", "-C", "BBNJ", "-c", str(cfg_file)]).exit_code == 0

    def forbidden(*a, **k):
        raise AssertionError("--offline contacted the manager")

    monkeypatch.setattr(cli, "ZoteroLocal", forbidden)
    res = runner.invoke(
        cli.app, ["--offline", "gaps", "-C", "BBNJ", "--json", "-c", str(cfg_file)]
    )
    assert res.exit_code == 0, res.stdout
    assert json.loads(res.stdout)["items"] == 2
    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    res = runner.invoke(cli.app, ["gaps", "-C", "BBNJ", "--json", "-c", str(cfg_file)])
    assert res.exit_code == 0, res.stdout
    assert runner.invoke(cli.app, ["sync", "-c", str(cfg_file)]).exit_code == 2


def test_offline_with_no_mirror_exits_2(cfg_file, library):
    res = runner.invoke(cli.app, ["--offline", "gaps", "-C", "BBNJ", "-c", str(cfg_file)])
    assert res.exit_code == 2
    assert "no mirror" in res.stdout


def test_a_command_reads_scope_from_the_mirror_not_the_manager(cfg_file, library):
    for _ in range(2):
        res = runner.invoke(cli.app, ["gaps", "-C", "BBNJ", "--json", "-c", str(cfg_file)])
        assert res.exit_code == 0, res.stdout
    # One change listing per command; never the manager's own scoped listing.
    assert library.listings == 2
    assert library.scope_reads == 0


def test_a_change_in_the_library_reaches_the_next_command(cfg_file, library):
    res = runner.invoke(cli.app, ["gaps", "-C", "BBNJ", "--json", "-c", str(cfg_file)])
    assert json.loads(res.stdout)["items"] == 2
    extra = make_item(key="I3", year=2022, collection_paths=["BBNJ"])
    base = StubZL.items_in_scope
    library.items_in_scope = lambda keys: [*base(library, keys), extra]
    forget_index()
    res = runner.invoke(cli.app, ["gaps", "-C", "BBNJ", "--json", "-c", str(cfg_file)])
    assert json.loads(res.stdout)["items"] == 3


# ---- the rule, enforced ----------------------------------------------------------------


def test_only_the_adapter_modules_touch_the_zotero_client():
    """pyzotero and the raw client stay in zot.py, library.py, and attach.py."""
    allowed = {"zot.py", "library.py", "attach.py"}
    root = Path(cli.__file__).parent
    client_call = re.compile(r"\.zot\.[a-z_]+\(|\bimport pyzotero\b|\bfrom pyzotero\b")
    offenders = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if path.name not in allowed and client_call.search(path.read_text())
    )
    assert offenders == []


def test_the_zotero_adapter_is_not_what_commands_hold():
    """``_connect`` hands commands the mirror-first backend when the manager has a change feed."""
    assert callable(getattr(ZoteroBackend, "changes", None))
