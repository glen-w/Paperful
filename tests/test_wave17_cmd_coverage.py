"""1.7 coverage wave: extracted ``*_cmd`` bodies with stubbed runtime/domain.

Each run function is exercised through its human and (where offered) JSON
paths, plus its refuse/exit branches. The library, network, and LLM are
stubbed at the same seams the CLI tests use (``cli_runtime`` + domain module
functions imported inside the run body).
"""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer
from rich.console import Console

from paperful import cli_runtime


def _console() -> Console:
    return Console(file=io.StringIO(), highlight=False, width=200)


class _Bound:
    collections = ["ocean"]
    library = False
    year_from = None
    year_to = None
    types: list[str] = []
    limit = None


class _Loaded:
    def __init__(self, items, label="ocean"):
        self.items = items
        self.label = label


@pytest.fixture
def runtime(monkeypatch, cfg):
    """Stub cli_runtime seams; returns (cfg, loaded) with loaded.items settable."""

    loaded = _Loaded([SimpleNamespace(key="K1", doi="10.1/x", title="Paper One")])
    backend = SimpleNamespace(supports_write=lambda: True)
    monkeypatch.setattr(cli_runtime, "_cfg", lambda path: cfg)

    def _bind(c, **k):
        bound = _Bound()
        bound.apply = k.get("apply")
        return bound

    monkeypatch.setattr(cli_runtime, "_bind_run", _bind)
    monkeypatch.setattr(cli_runtime, "_require_manager", lambda c: None)
    monkeypatch.setattr(cli_runtime, "_connect", lambda c, quiet=False: backend)
    monkeypatch.setattr(cli_runtime, "_live_backend", lambda c, **k: backend)
    monkeypatch.setattr(cli_runtime, "_load_scope", lambda b, **k: loaded)
    monkeypatch.setattr(cli_runtime, "_loaded_scope", lambda b, item_keys=None: loaded)
    monkeypatch.setattr(cli_runtime, "_flush", lambda b: None)
    monkeypatch.setattr(cli_runtime, "_rag_auto", lambda *a, **k: None)
    return cfg, loaded, backend


# ---- acronyms ---------------------------------------------------------------


def test_acronyms_dry_and_apply(runtime, monkeypatch, tmp_path):
    from paperful import acronyms_cmd

    cfg, loaded, _b = runtime
    rows = [SimpleNamespace(token="BBNJ", count=3)]
    monkeypatch.setattr("paperful.acronyms.harvest", lambda items, min_count=1: rows)
    monkeypatch.setattr(
        "paperful.acronyms.write_allowlist",
        lambda *a, **k: tmp_path / "acronyms.json",
    )
    kwargs = dict(
        collection=["ocean"],
        library=None,
        year_from=None,
        year_to=None,
        item_type=[],
        min_count=2,
        profile=None,
        run_config=None,
        config=None,
    )
    acronyms_cmd.run_acronyms(_console(), apply=False, **kwargs)
    acronyms_cmd.run_acronyms(_console(), apply=True, **kwargs)


def test_acronyms_refuses_no_scope(runtime):
    from paperful import acronyms_cmd

    with pytest.raises(typer.Exit):
        acronyms_cmd.run_acronyms(
            _console(),
            collection=[],
            library=None,
            year_from=None,
            year_to=None,
            item_type=[],
            min_count=2,
            apply=False,
            profile=None,
            run_config=None,
            config=None,
        )


# ---- twenty -------------------------------------------------------------------


def _twenty_ready(runtime, monkeypatch):
    cfg, loaded, _b = runtime
    cfg.twenty_enabled = True
    monkeypatch.setattr("paperful.twenty.twenty_ready", lambda c: True)
    return cfg, loaded


def test_twenty_lookup_dry_and_empty(runtime, monkeypatch):
    from paperful import twenty_cmd

    cfg, loaded = _twenty_ready(runtime, monkeypatch)
    row = SimpleNamespace(
        query_name="Smith, Jane",
        status="match",
        listing_url="",
        hit=SimpleNamespace(website="https://example.org"),
        emails=["j@example.org"],
        note="",
    )
    monkeypatch.setattr(
        "paperful.twenty.authors_from_items", lambda items: ["Smith, Jane"]
    )
    monkeypatch.setattr(
        "paperful.twenty.lookup_authors", lambda c, a, collection="", apply=False: [row]
    )
    kwargs = dict(
        collection=["ocean"],
        library=None,
        year_from=None,
        year_to=None,
        item_type=[],
        profile=None,
        run_config=None,
        config=None,
    )
    twenty_cmd.run_twenty_lookup(_console(), apply=False, **kwargs)
    twenty_cmd.run_twenty_lookup(_console(), apply=True, **kwargs)
    loaded.items = []
    with pytest.raises(typer.Exit):
        twenty_cmd.run_twenty_lookup(_console(), apply=False, **kwargs)


def test_twenty_disabled_exits(runtime):
    from paperful import twenty_cmd

    cfg, _loaded, _b = runtime
    cfg.twenty_enabled = False
    with pytest.raises(typer.Exit):
        twenty_cmd.run_twenty_lookup(
            _console(),
            collection=["ocean"],
            library=None,
            year_from=None,
            year_to=None,
            item_type=[],
            apply=False,
            profile=None,
            run_config=None,
            config=None,
        )


def test_twenty_sync_dry_json_apply(runtime, monkeypatch):
    from paperful import twenty_cmd

    cfg, loaded = _twenty_ready(runtime, monkeypatch)
    action = SimpleNamespace(action="create", name="Smith, Jane", note="", twenty_id="")
    monkeypatch.setattr(
        "paperful.twenty.plan_sync",
        lambda c, items, collection="", limit=None: [action],
    )
    monkeypatch.setattr(
        "paperful.twenty.apply_sync_actions",
        lambda c, actions, collection="": actions,
    )
    kwargs = dict(
        collection=["ocean"],
        library=None,
        year_from=None,
        year_to=None,
        item_type=[],
        limit=None,
        yes=True,
        profile=None,
        run_config=None,
        config=None,
    )
    twenty_cmd.run_twenty_sync(_console(), apply=False, fmt="text", **kwargs)
    twenty_cmd.run_twenty_sync(_console(), apply=True, fmt="json", **kwargs)


# ---- precedent ----------------------------------------------------------------


def test_precedent_human_json_and_empty(runtime, monkeypatch, tmp_path):
    from paperful import precedent_cmd

    cfg, loaded, _b = runtime
    row = SimpleNamespace(
        doi="10.1/x",
        title="Held paper",
        evidence="held",
        suggested_action="read",
    )
    counts = {"held": 1, "public_metadata_only": 0, "openalex_fetched": 0}
    monkeypatch.setattr(
        "paperful.precedent.collect_pack",
        lambda *a, **k: ([row], ["note"], counts, False),
    )
    monkeypatch.setattr(
        "paperful.precedent.write_pack", lambda *a, **k: tmp_path / "pack"
    )
    kwargs = dict(
        query="graphene methods",
        collection=["ocean"],
        library=None,
        year_from=None,
        year_to=None,
        item=[],
        seed_doi="",
        held_k=None,
        public_k=None,
        dedupe_scope="library",
        profile=None,
        run_config=None,
        config=None,
    )
    precedent_cmd.run_precedent(_console(), fmt="text", **kwargs)
    precedent_cmd.run_precedent(_console(), fmt="json", **kwargs)
    with pytest.raises(typer.Exit):
        precedent_cmd.run_precedent(_console(), fmt="text", **{**kwargs, "query": " "})


# ---- playbooks ----------------------------------------------------------------


def test_playbooks_propose_and_promote(runtime, monkeypatch, tmp_path):
    from paperful import playbooks_cmd

    cfg, _loaded, _b = runtime
    cfg.grey_playbooks_dir = tmp_path / "packs"
    monkeypatch.setattr("paperful.fetch_wins.load_wins", lambda path: [])
    monkeypatch.setattr(
        "paperful.fetch_wins.propose_toml", lambda rows, min_hits=1: "x = 1\n"
    )
    monkeypatch.setattr(
        "paperful.fetch_wins.proposed_path", lambda c: tmp_path / "proposed.toml"
    )
    playbooks_cmd.run_playbooks_propose(_console(), config=None, to=None, min_hits=1)
    with pytest.raises(typer.Exit):
        playbooks_cmd.run_playbooks_propose(
            _console(), config=None, to=None, min_hits=0
        )
    monkeypatch.setattr(
        "paperful.playbooks.load_pack_file",
        lambda path: [SimpleNamespace(name="learned-x")],
    )
    monkeypatch.setattr("paperful.fetch_wins.write_learned", lambda d, books: True)
    proposal = tmp_path / "proposed.toml"
    proposal.write_text("x", encoding="utf-8")
    playbooks_cmd.run_playbooks_promote(_console(), config=None, source=proposal)
    with pytest.raises(typer.Exit):
        playbooks_cmd.run_playbooks_promote(
            _console(), config=None, source=tmp_path / "missing.toml"
        )


def test_playbooks_probe_rows(runtime, monkeypatch):
    from paperful import playbooks_cmd

    row = SimpleNamespace(
        status="pass",
        playbook="grey",
        url="https://example.org",
        extra="",
        chosen="https://example.org/a.pdf",
        detail="",
        to_dict=lambda: {"status": "pass"},
    )
    monkeypatch.setattr("paperful.grey_probe.load_corpus", lambda corpus: ["t"])
    monkeypatch.setattr(
        "paperful.grey_probe.playbooks_for_probe", lambda books, examples=False: []
    )
    monkeypatch.setattr("paperful.grey_probe.probe_corpus", lambda *a, **k: [row])
    monkeypatch.setattr(
        "paperful.grey_probe.save_recorded", lambda path, rows: Path(path)
    )
    playbooks_cmd.run_playbooks_probe(
        _console(),
        corpus=None,
        config=None,
        examples=False,
        check=1,
        min_bytes=10,
        delay=0,
        save=None,
        as_json=True,
    )
    playbooks_cmd.run_playbooks_probe(
        _console(),
        corpus=None,
        config=None,
        examples=False,
        check=1,
        min_bytes=10,
        delay=0,
        save=None,
        as_json=False,
    )
    with pytest.raises(typer.Exit):
        playbooks_cmd.run_playbooks_probe(
            _console(),
            corpus=None,
            config=None,
            examples=False,
            check=0,
            min_bytes=10,
            delay=0,
            save=None,
            as_json=False,
        )


# ---- keepup -------------------------------------------------------------------


def test_keepup_cmd_all_verbs(runtime, monkeypatch, tmp_path):
    from paperful import keepup_cmd

    monkeypatch.setattr(
        "paperful.keepup.save_job", lambda *a, **k: tmp_path / "job.toml"
    )
    monkeypatch.setattr("paperful.keepup.list_jobs", lambda c: ["job1"])
    monkeypatch.setattr("paperful.keepup.show_job", lambda *a, **k: None)
    monkeypatch.setattr("paperful.keepup.delete_job", lambda *a, **k: tmp_path / "job1")
    monkeypatch.setattr(
        "paperful.keepup.run_job",
        lambda *a, **k: SimpleNamespace(created=0),
    )
    monkeypatch.setattr(
        "paperful.keepup.write_digest", lambda *a, **k: tmp_path / "digest.md"
    )
    monkeypatch.setattr("paperful.keepup.load_job", lambda *a, **k: {})
    monkeypatch.setattr(
        "paperful.keepup.apply_job",
        lambda *a, **k: SimpleNamespace(failed=0, created=0),
    )
    monkeypatch.setattr("paperful.keepup.dismiss", lambda *a, **k: "10.1/x")

    keepup_cmd.run_keepup_save(
        _console(),
        name="job1",
        collection="ocean",
        watch=["w1"],
        authorwatch=[],
        source=["cites"],
        interval_days=7,
        per_seed_limit=5,
        max_candidates=10,
        config=None,
    )
    keepup_cmd.run_keepup_list(_console(), config=None)
    keepup_cmd.run_keepup_show(_console(), name="job1", config=None)
    with pytest.raises(typer.Exit):
        keepup_cmd.run_keepup_delete(_console(), name="job1", yes=False, config=None)
    keepup_cmd.run_keepup_delete(_console(), name="job1", yes=True, config=None)
    keepup_cmd.run_keepup_run(
        _console(), name="job1", force=False, apply=False, config=None
    )
    keepup_cmd.run_keepup_digest(_console(), name="job1", config=None)
    keepup_cmd.run_keepup_apply(_console(), name="job1", apply=False, config=None)
    keepup_cmd.run_keepup_dismiss(
        _console(), name="job1", doi="10.1/x", identity="", config=None
    )


def test_keepup_cmd_error_maps_to_exit(runtime, monkeypatch):
    from paperful import keepup_cmd
    from paperful.keepup import KeepupError

    def boom(*a, **k):
        raise KeepupError("nope")

    monkeypatch.setattr("paperful.keepup.save_job", boom)
    with pytest.raises(typer.Exit):
        keepup_cmd.run_keepup_save(
            _console(),
            name="x",
            collection="ocean",
            watch=[],
            authorwatch=[],
            source=[],
            interval_days=7,
            per_seed_limit=5,
            max_candidates=10,
            config=None,
        )


# ---- snapshot / coverage --------------------------------------------------------


def test_snapshot_cmd_dry_and_write(runtime, monkeypatch):
    from paperful import snapshot_cmd

    cfg, loaded, _b = runtime
    stats = SimpleNamespace(
        records=1, pdf_exports=1, notes=0, unread=0, pdf_keys=["K1"]
    )
    monkeypatch.setattr("paperful.snapshot.run_snapshot", lambda *a, **k: stats)
    monkeypatch.setattr(
        "paperful.snapshot.snapshot_report", lambda *a, **k: {"summary": {}}
    )
    monkeypatch.setattr(snapshot_cmd, "write_run_report", lambda *a, **k: None)
    kwargs = dict(
        collection=["ocean"],
        library=None,
        year_from=None,
        year_to=None,
        item_type=[],
        limit=None,
        profile=None,
        run_config=None,
        config=None,
    )
    snapshot_cmd.run_snapshot_cmd(_console(), dry_run=True, pdfs=None, **kwargs)
    snapshot_cmd.run_snapshot_cmd(_console(), dry_run=False, pdfs="all", **kwargs)


def test_coverage_cmd_from_file(runtime, monkeypatch, tmp_path):
    from paperful import coverage_cmd

    cfg, loaded, backend = runtime
    src = tmp_path / "brief.md"
    src.write_text("Cited 10.1000/xyz in passing.", encoding="utf-8")
    row = SimpleNamespace(
        doi="10.1000/xyz",
        title="Missing one",
        status="missing",
        suggested_action="ingest",
    )
    monkeypatch.setattr(
        "paperful.coverage.extract_mentions", lambda text: ["10.1000/xyz"]
    )
    monkeypatch.setattr("paperful.coverage.classify_mentions", lambda m, c, l: [row])
    monkeypatch.setattr(
        "paperful.coverage.write_pack", lambda *a, **k: tmp_path / "pack"
    )
    kwargs = dict(collection=["ocean"], profile=None, run_config=None, config=None)
    coverage_cmd.run_coverage(
        _console(), from_note=None, from_file=src, fmt="text", **kwargs
    )
    coverage_cmd.run_coverage(
        _console(), from_note=None, from_file=src, fmt="json", **kwargs
    )
    with pytest.raises(typer.Exit):
        coverage_cmd.run_coverage(
            _console(), from_note="n", from_file=src, fmt="text", **kwargs
        )


# ---- report / export-proposals ---------------------------------------------------


def test_report_cmd_paths(runtime, monkeypatch, tmp_path):
    from paperful import cli_runtime as rt
    from paperful import report_cmd

    cfg, _loaded, _b = runtime
    monkeypatch.setattr(rt, "_load_last_run", lambda c: None)
    with pytest.raises(typer.Exit) as exc:
        report_cmd.run_report(
            _console(),
            config=None,
            not_found=False,
            status="",
            as_json=True,
            last_run=False,
        )
    assert exc.value.exit_code == 0
    with pytest.raises(typer.Exit) as exc:
        report_cmd.run_report(
            _console(),
            config=None,
            not_found=False,
            status="",
            as_json=False,
            last_run=True,
        )
    assert exc.value.exit_code == 1
    with pytest.raises(typer.Exit) as exc:
        report_cmd.run_report(
            _console(),
            config=None,
            not_found=False,
            status="",
            as_json=False,
            last_run=False,
        )
    assert exc.value.exit_code == 0

    rf = tmp_path / "report.json"
    rf.write_text(
        '{"summary": {"downloaded": 2, "failed": 0}, "items": [], "command": "run"}',
        encoding="utf-8",
    )
    report_cmd.run_report_counts(_console(), report_file=rf)
    report_cmd.run_report_new_count(_console(), report_file=rf)


def test_export_proposals_cmd(runtime, monkeypatch, tmp_path):
    from paperful import report_cmd

    monkeypatch.setattr(
        "paperful.pack_bib.export_pack_text",
        lambda path, kind: ("@article{x}", tmp_path / "candidates.jsonl", 1),
    )
    dest = tmp_path / "out.bib"
    report_cmd.run_export_proposals(
        _console(), pack=Path("pack"), dest=dest, fmt="", config=None
    )
    assert dest.read_text(encoding="utf-8") == "@article{x}"
    with pytest.raises(typer.Exit):
        report_cmd.run_export_proposals(
            _console(), pack=Path("pack"), dest=dest, fmt="yaml", config=None
        )


# ---- notes delete -----------------------------------------------------------------


def test_notes_delete_dry_apply_and_guards(runtime, monkeypatch):
    from paperful import notes_delete_cmd

    cfg, loaded, backend = runtime
    backend.resolve_collection = lambda spec: SimpleNamespace(key="C1")
    hit = SimpleNamespace(
        note_key="N1",
        parent_key="K1",
        title="T",
        note_type="summary",
        model="m",
        standalone=False,
    )
    monkeypatch.setattr("paperful.notes.collect", lambda *a, **k: [hit])
    monkeypatch.setattr("paperful.notes.select", lambda hits, **k: hits)
    monkeypatch.setattr("paperful.notes.apply_delete", lambda b, matched: (1, []))
    kwargs = dict(
        collection=["ocean"],
        library=None,
        item=[],
        model="",
        except_model="",
        all_owned=False,
        yes=True,
        year_from=None,
        year_to=None,
        item_type=[],
        profile=None,
        run_config=None,
        config=None,
    )
    notes_delete_cmd.run_notes_delete(
        _console(), note_type=["summary"], apply=False, fmt="text", **kwargs
    )
    notes_delete_cmd.run_notes_delete(
        _console(), note_type=["summary"], apply=True, fmt="json", **kwargs
    )
    with pytest.raises(typer.Exit):
        notes_delete_cmd.run_notes_delete(
            _console(), note_type=["bogus"], apply=False, fmt="text", **kwargs
        )
    with pytest.raises(typer.Exit):
        notes_delete_cmd.run_notes_delete(
            _console(), note_type=[], apply=False, fmt="text", **kwargs
        )


# ---- export library -----------------------------------------------------------------


def test_export_library_ris_and_endnote(runtime, monkeypatch, tmp_path):
    from paperful import export_cmd

    cfg, loaded, backend = runtime
    item = SimpleNamespace(
        key="K1",
        doi="10.1/x",
        title="Paper One",
        year=2024,
        date="2024",
        item_type="journalArticle",
        publication_title="J",
        url="",
        pmid=None,
        abstract="",
        has_pdf=False,
        collection_paths=[],
        first_author="Smith",
        creators=[],
        authors=[],
    )
    loaded.items = [item]
    backend.children = lambda key: [
        {"key": "N1", "data": {"itemType": "note", "note": "<p>hi</p>", "tags": []}}
    ]
    kwargs = dict(
        collection=["ocean"],
        library=False,
        year_from=None,
        year_to=None,
        item_type=[],
        limit=None,
        config=None,
    )
    dest = tmp_path / "lib.ris"
    export_cmd.run_export_library(_console(), dest=dest, fmt=None, pdfs=False, **kwargs)
    assert dest.is_file()
    bundle = tmp_path / "bundle"
    export_cmd.run_export_library(
        _console(), dest=bundle, fmt="endnote-xml", pdfs=False, **kwargs
    )
    assert (bundle / "paperful.xml").is_file()
    with pytest.raises(typer.Exit):
        export_cmd.run_export_library(
            _console(), dest=dest, fmt="yaml", pdfs=False, **kwargs
        )


# ---- restore ---------------------------------------------------------------------


def test_restore_dry_and_apply(runtime, monkeypatch, tmp_path):
    from paperful import cli_runtime as rt
    from paperful import restore_cmd

    cfg, loaded, backend = runtime
    backend.resolve_collection = lambda spec: SimpleNamespace(path="ocean")
    backend.items_in_scope = lambda keys: []
    backend.children = lambda key: []
    monkeypatch.setattr(rt, "_resolve_types", lambda types: set())
    monkeypatch.setattr(rt, "_scope_keys", lambda b, c, l: ([], "ocean"))
    import contextlib

    monkeypatch.setattr(rt, "_spinner", lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr("paperful.restore.iter_records", lambda out, prefixes: [])
    monkeypatch.setattr(
        "paperful.restore.plan_restore",
        lambda records, items, note_tags_for=None: SimpleNamespace(
            counts=lambda: {
                "create_item": 0,
                "exists": 0,
                "skip": 0,
                "attach_pdf": 0,
                "create_note": 0,
            }
        ),
    )
    monkeypatch.setattr(
        "paperful.restore.apply_restore",
        lambda planned, b, b2, track=None: {
            "create_item": 0,
            "attach_pdf": 0,
            "create_note": 0,
        },
    )
    kwargs = dict(
        collection=["ocean"],
        library=None,
        year_from=None,
        year_to=None,
        item_type=[],
        limit=None,
        profile=None,
        run_config=None,
        config=None,
    )
    restore_cmd.run_restore(_console(), dry_run=True, apply=False, fmt="text", **kwargs)
    restore_cmd.run_restore(_console(), dry_run=False, apply=True, fmt="json", **kwargs)
    with pytest.raises(typer.Exit):
        restore_cmd.run_restore(
            _console(), dry_run=True, apply=True, fmt="text", **kwargs
        )


# ---- sync / import / openalex-store -------------------------------------------------


def test_sync_cmd_changes_and_snapshot_fallback(runtime, monkeypatch):
    from paperful import sync_cmd

    cfg, loaded, backend = runtime
    stats = SimpleNamespace(
        previous=1,
        version=2,
        full=False,
        written=3,
        gone=0,
        pdf_exports=1,
        unread=0,
        unwritten=[],
        pdf_missing=0,
        pdf_keys=["K1"],
    )
    monkeypatch.setattr("paperful.sync.run_sync", lambda *a, **k: stats)
    monkeypatch.setattr("paperful.sync.sync_report", lambda *a, **k: {})
    monkeypatch.setattr(sync_cmd, "write_run_report", lambda *a, **k: None)
    backend.changes = lambda since: []
    sync_cmd.run_sync_command(
        _console(),
        full=False,
        dry_run=False,
        pdfs=None,
        accept_gone=False,
        config=None,
    )
    sync_cmd.run_sync_command(
        _console(),
        full=True,
        dry_run=True,
        pdfs="all",
        accept_gone=True,
        config=None,
    )
    # Backend without a change feed falls back to a whole snapshot.
    del backend.changes
    snap = SimpleNamespace(records=1, pdf_exports=0, notes=0)
    monkeypatch.setattr("paperful.snapshot.run_snapshot", lambda *a, **k: snap)
    monkeypatch.setattr("paperful.snapshot.snapshot_report", lambda *a, **k: {})
    sync_cmd.run_sync_command(
        _console(),
        full=False,
        dry_run=True,
        pdfs=None,
        accept_gone=False,
        config=None,
    )


def test_import_cmd_dry_and_apply(runtime, monkeypatch, tmp_path):
    from paperful import sync_cmd

    bib = tmp_path / "in.bib"
    bib.write_text(
        "@article{x, title={T}, author={Smith, Jane}, year={2020}}\n",
        encoding="utf-8",
    )
    sync_cmd.run_import_library(
        _console(), path=bib, fmt=None, apply=False, config=None
    )
    monkeypatch.setattr(
        "paperful.xfer.apply_import",
        lambda records, backend, dry_run=False, track=None: {
            "create": 1,
            "attach": 0,
            "notes": 0,
            "skipped_pdf": 0,
        },
    )
    sync_cmd.run_import_library(_console(), path=bib, fmt=None, apply=True, config=None)
    with pytest.raises(typer.Exit):
        sync_cmd.run_import_library(
            _console(),
            path=tmp_path / "missing.bib",
            fmt=None,
            apply=False,
            config=None,
        )


def test_openalex_store_cmd(runtime, monkeypatch):
    from paperful import sync_cmd

    monkeypatch.setattr(
        "paperful.snowball.local_openalex.build_cites_index_from_config",
        lambda cfg, output_dir=None, timeout_s=None, progress=None: (
            "/tmp/cites",
            {"built": 1, "skipped": 2, "total": 3},
        ),
    )
    sync_cmd.run_openalex_store_build_cites(
        _console(), out="/tmp/cites", timeout_s=30, config=None
    )


# ---- ask turn ---------------------------------------------------------------------


def test_ask_turn_happy_and_guards(cfg, monkeypatch):
    from paperful.rag import ask_turn

    with pytest.raises(ValueError):
        ask_turn.run_ask_turn(
            cfg,
            question=" ",
            thread_id=None,
            collection="",
            year_from=None,
            year_to=None,
            focus=None,
        )
    with pytest.raises(ValueError):
        ask_turn.run_ask_turn(
            cfg,
            question="q?",
            thread_id=None,
            collection="",
            year_from=None,
            year_to=None,
            focus=None,
        )
    cfg.rag_enabled = True
    monkeypatch.setattr(ask_turn, "validate_llm_for_ask", lambda c: None)
    monkeypatch.setattr(ask_turn, "validate_embedder", lambda c: object())
    monkeypatch.setattr(ask_turn, "get_client", lambda c: object())
    monkeypatch.setattr(ask_turn.Index, "open", classmethod(lambda cls, c: object()))
    monkeypatch.setattr(ask_turn, "Ledger", lambda path: SimpleNamespace())
    monkeypatch.setattr(ask_turn, "ledger_path", lambda c: cfg.state_dir / "l.json")
    monkeypatch.setattr(ask_turn, "scope_keys", lambda *a, **k: ["K1"])
    monkeypatch.setattr(
        ask_turn,
        "load_thread",
        lambda state, tid: SimpleNamespace(turns=[]),
    )
    monkeypatch.setattr(ask_turn, "save_thread", lambda *a, **k: None)
    source = SimpleNamespace(
        marker="[1]", item_key="K1", title="T", pages="1", citation="Smith 2020"
    )
    reply = SimpleNamespace(
        text="Answer.",
        sources=[source],
        ask_mode="simple",
        evidence=[],
        read=lambda: None,
        cited=lambda: [source],
    )
    monkeypatch.setattr(ask_turn, "answer", lambda *a, **k: reply)
    out = ask_turn.run_ask_turn(
        cfg,
        question="What?",
        thread_id="new",
        collection="ocean",
        year_from=None,
        year_to=None,
        focus=None,
    )
    assert out["answer"] == "Answer."
    assert out["cited"] == ["[1]"]
    assert out["sources"][0]["itemKey"] == "K1"


# ---- attach ---------------------------------------------------------------------


def test_attach_manual_and_none_pending(runtime, monkeypatch, tmp_path):
    from paperful import attach_cmd

    cfg, loaded, backend = runtime
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(
        "paperful.handoff.attach_pdf_file",
        lambda *a, **k: SimpleNamespace(itemKey="K1"),
    )
    attach_cmd.run_attach(
        _console(),
        item=["K1"],
        file=pdf,
        config=None,
        limit=None,
        allow_pdf_doi_mismatch=False,
        allow_short_pdf=False,
    )
    with pytest.raises(typer.Exit):
        attach_cmd.run_attach(
            _console(),
            item=["K1", "K2"],
            file=pdf,
            config=None,
            limit=None,
            allow_pdf_doi_mismatch=False,
            allow_short_pdf=False,
        )
    attach_cmd.run_attach(
        _console(),
        item=[],
        file=None,
        config=None,
        limit=None,
        allow_pdf_doi_mismatch=False,
        allow_short_pdf=False,
    )
