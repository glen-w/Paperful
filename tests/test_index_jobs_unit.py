"""``ui.index_jobs`` hook dispatch without HTTP."""

from __future__ import annotations

from paperful.config import Config
from paperful.ui import commands, jobs

# Load ``jobs`` first so ``index_jobs`` finishes initializing (jobs re-imports it).
from paperful.ui import index_jobs  # noqa: E402


def test_rag_ingest_uses_jobs_hook(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cmd_id = "cmd-test-ingest"
    commands.write_command(
        cfg,
        {"id": cmd_id, "command": "rag ingest", "status": "running"},
    )
    seen: list[dict] = []

    def fake(cfg, cmd_id, **kw):
        seen.append(kw)
        return {"dry_run": True, "summary": {"pdf": 1, "chunks": 2}}

    jobs.rag_ingest_fn = fake
    try:
        index_jobs.rag_ingest(
            cfg,
            cmd_id,
            collection="BBNJ",
            year_from=None,
            year_to=None,
            limit=5,
            dry_run=True,
        )
    finally:
        jobs.rag_ingest_fn = None
    assert seen[0]["collection"] == "BBNJ"
    rec = commands.read_command(cfg, cmd_id)
    assert rec["result"]["summary"]["chunks"] == 2


def test_extract_sections_hook_forwards_grobid(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cmd_id = "cmd-sections"
    commands.write_command(
        cfg,
        {"id": cmd_id, "command": "extract_sections", "status": "running"},
    )
    seen: list[dict] = []

    def fake(cfg, cmd_id, **kw):
        seen.append(kw)
        return {"dry_run": True, "items": 1, "fields_present": 2, "grobid": True}

    jobs.extract_sections_fn = fake
    try:
        index_jobs.extract_sections(
            cfg,
            cmd_id,
            collection="BBNJ",
            whole_library=False,
            year_from=None,
            year_to=None,
            item_keys=None,
            item_types=None,
            use_llm=False,
            use_grobid=True,
            limit=3,
            dry_run=True,
            force=False,
        )
    finally:
        jobs.extract_sections_fn = None
    assert seen[0]["use_grobid"] is True
    assert seen[0]["collection"] == "BBNJ"
    rec = commands.read_command(cfg, cmd_id)
    assert rec["result"]["grobid"] is True


def test_critique_job_records_status_detail(tmp_path, monkeypatch):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cmd_id = "cmd-critique-detail"
    commands.write_command(
        cfg, {"id": cmd_id, "verb": "critique", "status": "running"}
    )
    src = tmp_path / "draft.md"
    src.write_text("The cat sat on the mat. " * 20, encoding="utf-8")

    def fake_build(*_a, **kw):
        on_status = kw.get("on_status")
        if on_status:
            on_status("Extracting draft.md…")
        return {
            "counts": {"findings": 0, "by_code": {}, "by_lane": {}},
            "findings": [],
            "pack_dir": str(tmp_path / "pack"),
            "critique_id": "file-draft",
            "input": {"title": "draft.md"},
            "scope": "",
        }

    monkeypatch.setenv("PAPERFUL_OFFLINE", "1")
    monkeypatch.setattr("paperful.critique.build_critique", fake_build)
    prev = jobs.critique_fn
    jobs.critique_fn = None
    try:
        jobs.critique(cfg, cmd_id, staged_path=src)
    finally:
        jobs.critique_fn = prev
    rec = commands.read_command(cfg, cmd_id)
    assert rec["detail"] == "Extracting draft.md…"


def test_summarize_hook_writes_result(tmp_path):
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cmd_id = "cmd-sum"
    commands.write_command(cfg, {"id": cmd_id, "command": "summarize", "status": "running"})

    jobs.summarize_fn = lambda cfg, cmd_id, **kw: {"items": 0, "written": 0}
    try:
        index_jobs.summarize(
            cfg,
            cmd_id,
            collection="",
            year_from=None,
            year_to=None,
            limit=None,
            max_new=None,
            dest="notes",
            order="library",
            force=False,
        )
    finally:
        jobs.summarize_fn = None
    assert commands.read_command(cfg, cmd_id)["result"]["written"] == 0
