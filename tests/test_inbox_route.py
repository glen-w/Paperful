"""Smart inbox collection routing."""

from __future__ import annotations

import json
from pathlib import Path

from paperful.inbox_match import MatchResult, write_proposal
from paperful.inbox_route import (
    SCORE_LAST_SCOPE,
    SCORE_SNOWBALL_DOI,
    route_collection,
)
from paperful.zot import Collection
from tests.conftest import make_item


def _cols(*paths: str) -> dict[str, Collection]:
    out: dict[str, Collection] = {}
    for i, path in enumerate(paths):
        key = f"K{i}"
        out[key] = Collection(
            key=key, name=path.split("/")[-1], parent=None, path=path
        )
    return out


class _Backend:
    def __init__(self, paths: tuple[str, ...] = ("ocean/bbnj", "climate/unfccc")):
        self._cols = _cols(*paths)

    def collections(self):
        return self._cols


def _write_snowball(cfg, *, run_id: str, collection: str, doi: str = "") -> Path:
    dest = cfg.state_dir / "snowball" / run_id
    dest.mkdir(parents=True)
    (dest / "summary.json").write_text(
        json.dumps({"target_collection": collection}) + "\n", encoding="utf-8"
    )
    if doi:
        row = {
            "ids": {"doi": doi},
            "biblio": {"title": "A queued BBNJ paper about marine biodiversity"},
        }
        (dest / "candidates.jsonl").write_text(
            json.dumps(row) + "\n", encoding="utf-8"
        )
    return dest


def test_snowball_doi_hit_routes(cfg):
    _write_snowball(cfg, run_id="r1", collection="ocean/bbnj", doi="10.1000/hit")
    matched = MatchResult(item=None, how="doi", doi="10.1000/hit", title="Hit")
    result = route_collection(cfg, _Backend(), matched)
    assert result.collection == "ocean/bbnj"
    assert result.how == "snowball"
    assert result.confidence == SCORE_SNOWBALL_DOI


def test_watch_inbox_doi_routes(cfg):
    cfg.snowball_target_collection = "ocean/bbnj"
    watch = cfg.state_dir / "snowball" / "watches" / "bbnj"
    watch.mkdir(parents=True)
    (watch / "watch.json").write_text(
        json.dumps({"schema": "paperful.snowball.watch.v1", "profile": ""}) + "\n",
        encoding="utf-8",
    )
    (watch / "inbox.jsonl").write_text(
        json.dumps({"ids": {"doi": "10.1000/watch"}}) + "\n", encoding="utf-8"
    )
    matched = MatchResult(item=None, how="doi", doi="10.1000/watch")
    result = route_collection(cfg, _Backend(), matched)
    assert result.collection == "ocean/bbnj"
    assert result.how == "watch"


def test_last_scope_used_when_snowball_empty(cfg):
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    (cfg.state_dir / "last-run.json").write_text(
        json.dumps({"scope": "ocean/bbnj, years 2021–2026"}) + "\n",
        encoding="utf-8",
    )
    matched = MatchResult(item=None, how="none", title="Unrelated title here")
    result = route_collection(cfg, _Backend(), matched)
    assert result.collection == "ocean/bbnj"
    assert result.how == "last_scope"
    assert result.confidence == SCORE_LAST_SCOPE


def test_filename_title_overlap(cfg):
    matched = MatchResult(item=None, how="none", title="BBNJ implementing agreement")
    result = route_collection(
        cfg,
        _Backend(("bbnj", "unfccc")),
        matched,
        filename="bbnj-agreement.pdf",
    )
    assert result.collection == "bbnj"
    assert result.how == "title"


def test_junk_stem_ignored(cfg):
    matched = MatchResult(item=None, how="none", title="")
    result = route_collection(cfg, _Backend(), matched, filename="download.pdf")
    assert result.collection == ""
    assert result.how == "none"


def test_tie_is_fail_closed(cfg):
    _write_snowball(cfg, run_id="a", collection="ocean/bbnj", doi="10.1000/same")
    _write_snowball(cfg, run_id="b", collection="climate/unfccc", doi="10.1000/same")
    matched = MatchResult(item=None, how="doi", doi="10.1000/same")
    result = route_collection(cfg, _Backend(), matched)
    assert result.collection == ""
    assert result.reason == "conflict"


def test_doi_library_unique_path(cfg):
    item = make_item(
        key="LIB1",
        doi="10.1000/lib",
        collection_paths=["ocean/bbnj"],
        has_pdf=True,
    )
    matched = MatchResult(item=None, how="doi", doi="10.1000/lib")
    result = route_collection(cfg, _Backend(), matched, items=[item])
    assert result.collection == "ocean/bbnj"
    assert result.how == "doi_library"


def test_llm_when_thin_fills_collection(cfg, monkeypatch):
    from tests.test_llm_verbs import StubLLM

    cfg.llm_enabled = True
    cfg.inbox_llm_route = "when_thin"
    stub = StubLLM(
        data={
            "match": True,
            "confidence": 0.88,
            "collection": "ocean/bbnj",
            "reason": "topic fit",
        }
    )
    monkeypatch.setattr("paperful.llm.get_client", lambda _cfg: stub)
    matched = MatchResult(
        item=None,
        how="none",
        title="An untitled excerpt",
        text="general methods and results " * 8,
    )
    result = route_collection(cfg, _Backend(), matched, text=matched.text)
    assert result.how == "llm"
    assert result.collection == "ocean/bbnj"
    assert stub.calls


def test_llm_unknown_path_discarded(cfg, monkeypatch):
    from tests.test_llm_verbs import StubLLM

    cfg.llm_enabled = True
    cfg.inbox_llm_route = "always"
    stub = StubLLM(
        data={
            "match": True,
            "confidence": 0.99,
            "collection": "invented/new",
            "reason": "hallucination",
        }
    )
    monkeypatch.setattr("paperful.llm.get_client", lambda _cfg: stub)
    matched = MatchResult(item=None, how="none", title="A paper", text="excerpt")
    result = route_collection(cfg, _Backend(), matched, text="excerpt")
    assert result.collection == ""
    assert result.reason == "llm path not in library"


def test_route_off_default(cfg):
    assert cfg.inbox_route == "off"
    assert cfg.inbox_llm_route == "off"


def test_proposal_may_include_route_keys(cfg, tmp_path):
    cfg.inbox_dir = str(tmp_path / "drop")
    path = write_proposal(
        cfg,
        {
            "action": "create_parent",
            "pdf": str(tmp_path / "x.pdf"),
            "doi": "10.1000/x",
            "title": "X",
            "year": 2020,
            "how": "doi",
            "collection": "ocean/bbnj",
            "route_how": "snowball",
            "route_confidence": 0.95,
            "route_reason": "snowball 0.95",
            "route_candidates": [
                {"collection": "ocean/bbnj", "score": 0.95, "signal": "snowball"}
            ],
        },
    )
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["route_how"] == "snowball"
    assert body["schema"] == "paperful.inbox.proposal.v1"
