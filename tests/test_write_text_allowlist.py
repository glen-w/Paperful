"""Freeze the modules that still call Path.write_text.

Ledgers append through paperful.fsio. A new file on this list has to be an
export or a scratch file, or it has to move onto fsio.
"""

from __future__ import annotations

from pathlib import Path

ALLOW = frozenset(
    {
        "paperful/acronyms.py",
        "paperful/attach.py",
        "paperful/authors_report.py",
        "paperful/authorwatch.py",
        "paperful/capture.py",
        "paperful/capture_host.py",
        "paperful/catalogue.py",
        "paperful/collections_add.py",
        "paperful/cookies.py",
        "paperful/coverage.py",
        "paperful/critique.py",
        "paperful/critique_forensics.py",
        "paperful/critique_vale.py",
        "paperful/dedupe.py",
        "paperful/doctor.py",
        "paperful/e2e_nba.py",
        "paperful/endnote.py",
        "paperful/export_cmd.py",
        "paperful/fetch_wins.py",
        "paperful/fsio.py",
        "paperful/glossary_cmd.py",
        "paperful/grey_probe.py",
        "paperful/handoff.py",
        "paperful/inbox_match.py",
        "paperful/ingest_dois.py",
        "paperful/keepup.py",
        "paperful/library.py",
        "paperful/mendeley.py",
        "paperful/network/run.py",
        "paperful/network/store.py",
        "paperful/pack.py",
        "paperful/playbooks_cmd.py",
        "paperful/precedent.py",
        "paperful/rag/answered.py",
        "paperful/rag/batch.py",
        "paperful/rag/thread.py",
        "paperful/reachout.py",
        "paperful/refs_gap.py",
        "paperful/report_cmd.py",
        "paperful/rewrite.py",
        "paperful/run_config.py",
        "paperful/screen.py",
        "paperful/sections/grobid.py",
        "paperful/session.py",
        "paperful/snapshot.py",
        "paperful/snowball/authors.py",
        "paperful/snowball/briefing.py",
        "paperful/snowball/citation_graph.py",
        "paperful/snowball/command.py",
        "paperful/snowball/digest.py",
        "paperful/snowball/europepmc.py",
        "paperful/snowball/fill.py",
        "paperful/snowball/graph_library.py",
        "paperful/snowball/local_cites.py",
        "paperful/snowball/local_openalex.py",
        "paperful/snowball/profile.py",
        "paperful/snowball/searxng.py",
        "paperful/snowball/stop.py",
        "paperful/snowball/watch.py",
        "paperful/sources/htmlpdf.py",
        "paperful/stuff.py",
        "paperful/summarize.py",
        "paperful/sync.py",
        "paperful/synthesize.py",
        "paperful/twenty.py",
        "paperful/ui/jobs.py",
        "paperful/ui/rag_form.py",
        "paperful/ui/wanted_jobs.py",
        "paperful/versions.py",
    }
)


def test_write_text_does_not_spread():
    root = Path(__file__).resolve().parents[1] / "paperful"
    found = {
        str(path.relative_to(root.parent))
        for path in root.rglob("*.py")
        if ".write_text(" in path.read_text(encoding="utf-8")
    }
    extra = found - ALLOW
    assert not extra, "move these onto fsio or extend ALLOW: " + ", ".join(sorted(extra))
