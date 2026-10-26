"""``ui.index_jobs`` real-path fallbacks with inner functions stubbed (no LLM)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from paperful.config import Config
from paperful.ui import commands, jobs
from paperful.ui import index_jobs


def _cfg(tmp_path) -> Config:
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.rag_enabled = True
    return cfg


def _cmd(cfg: Config, cmd_id: str) -> None:
    commands.write_command(cfg, {"id": cmd_id, "status": "running"})


def test_ask_turn_fallback_calls_run_ask_turn(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _cmd(cfg, "ask1")
    jobs.ask_turn_fn = None
    monkeypatch.setattr(
        "paperful.rag.ask_turn.run_ask_turn",
        lambda *_a, **kw: {"question": kw["question"], "ask_mode": kw.get("ask_mode")},
    )
    index_jobs.ask_turn(
        cfg,
        "ask1",
        question="What do krill eat?",
        thread_id=None,
        collection="BBNJ",
        year_from=None,
        year_to=None,
        focus=None,
        ask_mode="simple",
    )
    rec = commands.read_command(cfg, "ask1")
    assert rec["result"]["question"] == "What do krill eat?"
    assert rec["result"]["ask_mode"] == "simple"


def test_rag_ingest_requires_enabled(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.rag_enabled = False
    _cmd(cfg, "ing0")
    jobs.rag_ingest_fn = None
    with pytest.raises(ValueError, match="rag.enabled"):
        index_jobs.rag_ingest(
            cfg,
            "ing0",
            collection="BBNJ",
            year_from=None,
            year_to=None,
            limit=None,
            dry_run=True,
        )


def test_rag_ingest_dry_run_skips_embedder(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _cmd(cfg, "ing1")
    jobs.rag_ingest_fn = None
    monkeypatch.setattr(
        "paperful.rag.ingest.select_entries", lambda *_a, **_k: ["e1"]
    )

    class Batch:
        def summary(self):
            return {"pdf": 1, "chunks": 4}

    monkeypatch.setattr(
        "paperful.rag.ingest.ingest_entries",
        lambda *_a, **kw: Batch(),
    )
    index_jobs.rag_ingest(
        cfg,
        "ing1",
        collection="BBNJ",
        year_from=2018,
        year_to=2020,
        limit=3,
        dry_run=True,
    )
    rec = commands.read_command(cfg, "ing1")
    assert rec["result"]["dry_run"] is True
    assert rec["result"]["summary"]["chunks"] == 4


def test_rag_ingest_live_validates_embedder(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _cmd(cfg, "ing2")
    jobs.rag_ingest_fn = None
    seen = {}
    monkeypatch.setattr("paperful.rag.ingest.select_entries", lambda *_a, **_k: [])
    monkeypatch.setattr(
        "paperful.llm.preflight.validate_embedder", lambda _cfg: "embedder"
    )

    class Batch:
        def summary(self):
            return {"pdf": 0}

    def ingest(_cfg, entries, **kw):
        seen.update(kw)
        return Batch()

    monkeypatch.setattr("paperful.rag.ingest.ingest_entries", ingest)
    index_jobs.rag_ingest(
        cfg,
        "ing2",
        collection="",
        year_from=None,
        year_to=None,
        limit=None,
        dry_run=False,
    )
    assert seen["embedder"] == "embedder"
    assert seen["prune"] is True


def test_rag_questions_scope_and_write(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    jobs.rag_questions_fn = None
    _cmd(cfg, "q0")
    with pytest.raises(ValueError, match="rag.enabled"):
        cfg.rag_enabled = False
        index_jobs.rag_questions(
            cfg,
            "q0",
            collection="",
            whole_library=True,
            year_from=None,
            year_to=None,
            item_keys=None,
            item_types=None,
            use_llm=False,
            limit=None,
            dry_run=True,
        )
    cfg.rag_enabled = True
    _cmd(cfg, "q1")
    with pytest.raises(ValueError, match="scope required"):
        index_jobs.rag_questions(
            cfg,
            "q1",
            collection="",
            whole_library=False,
            year_from=None,
            year_to=None,
            item_keys=None,
            item_types=None,
            use_llm=False,
            limit=None,
            dry_run=True,
        )

    class FakeLedger:
        def __init__(self, *_a, **_k):
            pass

    written = []
    monkeypatch.setattr("paperful.rag.ledger.Ledger", FakeLedger)
    monkeypatch.setattr("paperful.rag.index.ledger_path", lambda _cfg: tmp_path / "l")
    monkeypatch.setattr(
        "paperful.rag.questions.extract_scope",
        lambda *_a, **_k: [SimpleNamespace(questions=["q"])],
    )
    monkeypatch.setattr(
        "paperful.rag.questions.write_item", lambda *_a, **_k: written.append(1)
    )
    monkeypatch.setattr("paperful.llm.preflight.validate_llm_for_ask", lambda _c: None)
    monkeypatch.setattr("paperful.llm.get_client", lambda _c: "client")
    _cmd(cfg, "q2")
    index_jobs.rag_questions(
        cfg,
        "q2",
        collection="BBNJ",
        whole_library=False,
        year_from=None,
        year_to=None,
        item_keys=None,
        item_types=None,
        use_llm=True,
        limit=2,
        dry_run=False,
    )
    rec = commands.read_command(cfg, "q2")
    assert rec["result"]["questions"] == 1
    assert rec["result"]["llm"] is True
    assert written == [1]

    _cmd(cfg, "q3")
    index_jobs.rag_questions(
        cfg,
        "q3",
        collection="",
        whole_library=True,
        year_from=None,
        year_to=None,
        item_keys=None,
        item_types=None,
        use_llm=False,
        limit=None,
        dry_run=True,
    )
    assert commands.read_command(cfg, "q3")["result"]["dry_run"] is True

    _cmd(cfg, "q4")
    index_jobs.rag_questions(
        cfg,
        "q4",
        collection="",
        whole_library=False,
        year_from=None,
        year_to=None,
        item_keys=["ITEM1"],
        item_types=None,
        use_llm=False,
        limit=None,
        dry_run=True,
    )
    assert commands.read_command(cfg, "q4")["result"]["items"] == 1


def test_extract_sections_fallback_grobid_and_write(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.extract_sections_fields = ("methods", "results")
    jobs.extract_sections_fn = None
    _cmd(cfg, "s0")
    with pytest.raises(ValueError, match="scope required"):
        index_jobs.extract_sections(
            cfg,
            "s0",
            collection="",
            whole_library=False,
            year_from=None,
            year_to=None,
            item_keys=None,
            item_types=None,
            use_llm=False,
            use_grobid=False,
            limit=None,
            dry_run=True,
            force=False,
        )
    closed = []

    class Grobid:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(
        "paperful.grobid_client.grobid_client_from_config", lambda _c: Grobid()
    )
    monkeypatch.setattr("paperful.llm.preflight.validate_llm_for_verb", lambda _c: None)
    monkeypatch.setattr("paperful.llm.get_client", lambda _c: "llm")
    written = []
    monkeypatch.setattr(
        "paperful.sections.command.extract_scope",
        lambda *_a, **_k: [
            SimpleNamespace(fields={"methods": "m", "results": None}),
        ],
    )
    monkeypatch.setattr(
        "paperful.sections.command.write_item", lambda *_a, **_k: written.append(1)
    )
    _cmd(cfg, "s1")
    index_jobs.extract_sections(
        cfg,
        "s1",
        collection="BBNJ",
        whole_library=False,
        year_from=None,
        year_to=None,
        item_keys=None,
        item_types=None,
        use_llm=True,
        use_grobid=True,
        limit=1,
        dry_run=False,
        force=True,
    )
    rec = commands.read_command(cfg, "s1")
    assert rec["result"]["grobid"] is True
    assert rec["result"]["fields_present"] == 1
    assert closed == [True]
    assert written == [1]


def test_ask_batch_fallback_without_zotero_note(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    jobs.ask_batch_fn = None
    _cmd(cfg, "b1")

    class Pack:
        stamp = "s1"
        questions = 2
        answered = 2
        skipped = 0
        failed = 0
        focus = "none"
        model = "stub"

    folder = tmp_path / "pack"
    folder.mkdir()
    (folder / "answers.md").write_text("ok", encoding="utf-8")
    monkeypatch.setattr("paperful.llm.preflight.validate_llm_for_ask", lambda _c: None)
    monkeypatch.setattr("paperful.llm.preflight.validate_embedder", lambda _c: None)
    monkeypatch.setattr("paperful.llm.get_client", lambda _c: "c")
    monkeypatch.setattr("paperful.rag.prompt.parse_focus", lambda v: v or "none")
    monkeypatch.setattr(
        "paperful.rag.index.Index.open", lambda _c: SimpleNamespace()
    )
    monkeypatch.setattr("paperful.rag.index.ledger_path", lambda _c: tmp_path / "l")

    class FakeLedger:
        def __init__(self, *_a, **_k):
            pass

    monkeypatch.setattr("paperful.rag.ledger.Ledger", FakeLedger)
    monkeypatch.setattr("paperful.rag.retrieve.scope_keys", lambda *_a, **_k: ["k"])
    monkeypatch.setattr("paperful.rag.batch.run_batch", lambda *_a, **_k: Pack())
    monkeypatch.setattr("paperful.rag.batch.write_pack", lambda *_a, **_k: folder)
    index_jobs.ask_batch(
        cfg,
        "b1",
        questions=["q1"],
        collection="BBNJ",
        year_from=None,
        year_to=None,
        focus=None,
        dest="disk",
        apply=False,
    )
    rec = commands.read_command(cfg, "b1")
    assert rec["result"]["answered"] == 2
    assert rec["result"]["note"] is False


def test_rag_answered_fallback(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    jobs.rag_answered_fn = None
    _cmd(cfg, "a1")

    class Pack:
        stamp = "s"
        questions = 1
        answered = 1
        partial = 0
        not_found = 0
        failed = 0

    monkeypatch.setattr("paperful.llm.preflight.validate_llm_for_ask", lambda _c: None)
    monkeypatch.setattr("paperful.llm.preflight.validate_embedder", lambda _c: None)
    monkeypatch.setattr("paperful.llm.get_client", lambda _c: "c")
    monkeypatch.setattr(
        "paperful.rag.index.Index.open", lambda _c: SimpleNamespace()
    )
    monkeypatch.setattr("paperful.rag.index.ledger_path", lambda _c: tmp_path / "l")

    class FakeLedger:
        def __init__(self, *_a, **_k):
            pass

    monkeypatch.setattr("paperful.rag.ledger.Ledger", FakeLedger)
    monkeypatch.setattr("paperful.rag.retrieve.scope_keys", lambda *_a, **_k: ["k"])
    monkeypatch.setattr("paperful.rag.answered.run_answered", lambda *_a, **_k: Pack())
    monkeypatch.setattr(
        "paperful.rag.answered.write_pack", lambda *_a, **_k: tmp_path / "p"
    )
    index_jobs.rag_answered(
        cfg,
        "a1",
        collection="BBNJ",
        year_from=None,
        year_to=None,
        item_keys=None,
        item_types=None,
        questions=[("q", "a", None)],
        after_item="",
        top_k=4,
        force=False,
    )
    rec = commands.read_command(cfg, "a1")
    assert rec["result"]["answered"] == 1


def test_summarize_fallback_empty_and_ok(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    jobs.summarize_fn = None
    monkeypatch.setattr("paperful.llm.preflight.validate_llm_for_verb", lambda _c: None)
    monkeypatch.setattr("paperful.catalogue.open_library", lambda _c: SimpleNamespace())
    monkeypatch.setattr(
        "paperful.scope.load_scope",
        lambda *_a, **_k: SimpleNamespace(items=[], label="empty"),
    )
    monkeypatch.setattr("paperful.summarize.order_items", lambda items, _o: items)
    _cmd(cfg, "sum0")
    index_jobs.summarize(
        cfg,
        "sum0",
        collection="",
        year_from=None,
        year_to=None,
        limit=None,
        max_new=None,
        dest="notes",
        order="library",
        force=False,
    )
    rec = commands.read_command(cfg, "sum0")
    assert rec["status"] == "failed"
    assert rec["result"]["error"] == "no items"

    item = SimpleNamespace(key="ITEM1")
    monkeypatch.setattr(
        "paperful.scope.load_scope",
        lambda *_a, **_k: SimpleNamespace(items=[item, SimpleNamespace(key="ITEM2")], label="BBNJ"),
    )

    class Batch:
        fatal = None
        summarized = 1
        failed = 0
        skipped = 0
        not_reached = 0

    monkeypatch.setattr("paperful.summarize.summarize_items", lambda *_a, **_k: Batch())
    _cmd(cfg, "sum1")
    index_jobs.summarize(
        cfg,
        "sum1",
        collection="BBNJ",
        year_from=2010,
        year_to=2020,
        limit=1,
        max_new=2,
        dest="notes",
        order="library",
        force=False,
        item_keys=["ITEM1"],
    )
    rec = commands.read_command(cfg, "sum1")
    assert rec["result"]["summarized"] == 1
    assert rec["result"]["queued"] == 1


def test_synthesize_fallback_dry_run_and_skips(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    jobs.synthesize_fn = None
    monkeypatch.setattr("paperful.llm.preflight.validate_llm_for_verb", lambda _c: None)
    monkeypatch.setattr(
        "paperful.catalogue.open_library",
        lambda _c: SimpleNamespace(resolve_collection=lambda n: SimpleNamespace(key=n)),
    )
    monkeypatch.setattr(
        "paperful.scope.load_scope",
        lambda *_a, **_k: SimpleNamespace(
            items=[SimpleNamespace(key="A", year=2020, first_author="Ada")],
            label="BBNJ",
        ),
    )

    class Prepared:
        slug = "bbnj"
        sources = [SimpleNamespace(origin="disk")]
        missing = []
        chunks = ["c1"]

    monkeypatch.setattr(
        "paperful.synthesize.prepare_synthesis", lambda *_a, **_k: Prepared()
    )
    _cmd(cfg, "syn0")
    index_jobs.synthesize(
        cfg,
        "syn0",
        collection="BBNJ",
        year_from=2018,
        year_to=2020,
        limit=5,
        dest="disk",
        dry_run=True,
        force=False,
    )
    rec = commands.read_command(cfg, "syn0")
    assert rec["result"]["dry_run"] is True
    assert rec["result"]["chunks"] == 1

    empty = Prepared()
    empty.sources = []
    monkeypatch.setattr(
        "paperful.synthesize.prepare_synthesis", lambda *_a, **_k: empty
    )
    _cmd(cfg, "syn1")
    index_jobs.synthesize(
        cfg,
        "syn1",
        collection="BBNJ",
        year_from=None,
        year_to=None,
        limit=None,
        dest="disk",
        dry_run=False,
        force=False,
    )
    assert commands.read_command(cfg, "syn1")["result"]["skipped"] == "no_summaries"

    filled = Prepared()
    monkeypatch.setattr(
        "paperful.synthesize.prepare_synthesis", lambda *_a, **_k: filled
    )
    monkeypatch.setattr(
        "paperful.synthesize.report_is_current", lambda *_a, **_k: True
    )
    _cmd(cfg, "syn2")
    index_jobs.synthesize(
        cfg,
        "syn2",
        collection="BBNJ",
        year_from=None,
        year_to=None,
        limit=None,
        dest="disk",
        dry_run=False,
        force=False,
    )
    assert commands.read_command(cfg, "syn2")["result"]["skipped"] == "current"

    monkeypatch.setattr(
        "paperful.synthesize.report_is_current", lambda *_a, **_k: False
    )
    monkeypatch.setattr("paperful.llm.get_client", lambda _c: "c")
    monkeypatch.setattr(
        "paperful.synthesize.write_synthesis",
        lambda *_a, **_k: SimpleNamespace(n_chunks=3),
    )
    _cmd(cfg, "syn3")
    index_jobs.synthesize(
        cfg,
        "syn3",
        collection="BBNJ",
        year_from=None,
        year_to=None,
        limit=None,
        dest="disk",
        dry_run=False,
        force=True,
    )
    assert commands.read_command(cfg, "syn3")["result"]["chunks"] == 3

    with pytest.raises(ValueError, match="collection"):
        index_jobs.synthesize(
            cfg,
            "syn4",
            collection="",
            year_from=None,
            year_to=None,
            limit=None,
            dest="zotero",
            dry_run=False,
            force=False,
        )
