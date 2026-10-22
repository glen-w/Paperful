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
