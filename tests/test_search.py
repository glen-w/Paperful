"""Web grey search (SearXNG) — ranking, store, apply, CLI. Offline FakeSearXNG."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from paperful import cli
from paperful.config import Config, DEFAULT_SOURCES, load_config
from paperful.search.apply import apply_candidates, mark_exists
from paperful.search.rank import build_query, fanout_queries, parse_hosts, score_hit
from paperful.snowball.searxng import search_query
from paperful.search.run import run_search
from paperful.search.store import (
    HIT_KEYS,
    META_KEYS,
    SCHEMA,
    SUMMARY_KEYS,
    SearchError,
    load_run,
)

runner = CliRunner()

PDF = "https://portals.iucn.org/library/sites/library/files/documents/2018-gjerde.pdf"
LANDING = "https://www.iucn.org/resources/publication/gjerde-high-seas-2018"
SCHOLAR = "https://scholar.google.com/scholar?q=gjerde"
PUBLISHER = "https://www.sciencedirect.com/science/article/pii/S000000"
UNDOCS = "https://undocs.org/en/A/CONF.232/2023/4"
WIKI = "https://en.wikipedia.org/wiki/BBNJ"


class FakeSearXNG:
    """Mix of PDF, IUCN HTML, Scholar junk, and a publisher platform."""

    def __call__(self, query: str) -> dict:
        return {
            "results": [
                {"url": PDF, "title": "Gjerde IUCN 2018 high seas governance"},
                {"url": LANDING, "title": "IUCN Gjerde high seas landing 2018"},
                {"url": SCHOLAR, "title": "Scholar junk Gjerde"},
                {"url": PUBLISHER, "title": "Elsevier paywall"},
                {"url": UNDOCS, "title": "PrepCom undocs A/CONF.232/2023/4"},
                {"url": WIKI, "title": "BBNJ Wikipedia"},
            ]
        }


class StubLib:
    def __init__(self, items=None, write=True):
        self.created: list[dict] = []
        self._items = list(items or [])
        self._write = write

    def supports_write(self) -> bool:
        return self._write

    def ensure_collection_path(self, path: str) -> str:
        return "CKEY"

    def create_parent(self, payload: dict) -> str:
        self.created.append(payload)
        return f"K{len(self.created)}"

    def items_in_scope(self, _scope):
        return list(self._items)


def _cfg(tmp_path: Path) -> Config:
    cfg = Config(email="t@example.org", out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.out_dir.mkdir(parents=True)
    cfg.searxng_base_url = "http://searx.test"
    return cfg


def _probe(url: str) -> dict:
    if str(url).lower().endswith(".pdf") or "pdf?symbol=" in str(url):
        return {"kind": "pdf", "content_type": "application/pdf"}
    return {"kind": "landing", "content_type": "text/html"}


def test_search_not_a_run_source():
    assert "search" not in DEFAULT_SOURCES


def test_doctor_searxng_amber_when_unset(tmp_path: Path, monkeypatch):
    from paperful.doctor import run_checks

    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)
    cfg = Config(email="t@example.org", out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.searxng_base_url = ""
    rows = {c.name: c for c in run_checks(cfg, zl=None, probe=False)}
    assert rows["SearXNG"].status == "amber"
    assert rows["Grey playbooks"].status == "green"
    cfg.searxng_base_url = "http://searx.test"
    rows = {c.name: c for c in run_checks(cfg, zl=None, probe=False)}
    assert rows["SearXNG"].status == "green"


def test_fanout_includes_quoted_and_unhosted():
    qs = fanout_queries(["Kristina", "Gjerde", "IUCN"], filetype="pdf", hosts=["iucn.org"])
    blob = " ".join(qs)
    assert any("filetype:pdf" in q for q in qs)
    assert any('"Kristina Gjerde"' in q for q in qs)
    assert any("site:iucn.org" in q for q in qs)
    assert any("site:" not in q and "Kristina" in q for q in qs)
    assert "filetype:pdf" in blob


def test_search_query_pages_until_limit(tmp_path: Path, monkeypatch):
    def fake_http(_base, _query, *, pageno=1):
        start = (pageno - 1) * 20
        if pageno > 4:
            return {"results": []}
        return {
            "results": [
                {
                    "url": f"https://portals.iucn.org/library/files/gjerde-{start + i}.pdf",
                    "title": f"Gjerde {start + i}",
                }
                for i in range(20)
            ]
        }

    monkeypatch.setattr("paperful.snowball.searxng._http_search", fake_http)
    cfg = _cfg(tmp_path)
    rows = search_query(cfg, "Kristina Gjerde", limit=50, cache_dir=tmp_path / "sx")
    assert len(rows) == 50
    assert rows[0]["url"].endswith("gjerde-0.pdf")
    assert rows[49]["url"].endswith("gjerde-49.pdf")


def test_keeps_fifty_grey_hits(tmp_path: Path):
    class ManyGrey:
        def __call__(self, query: str) -> dict:
            rows = [
                {
                    "url": f"https://portals.iucn.org/library/sites/library/files/documents/gjerde-{i}.pdf",
                    "title": f"Gjerde IUCN high seas {i} 2018",
                }
                for i in range(80)
            ]
            rows.append({"url": SCHOLAR, "title": "Scholar junk"})
            return {"results": rows}

    cfg = _cfg(tmp_path)
    bundle = run_search(
        cfg,
        ["Kristina", "Gjerde"],
        max_hits=50,
        probe=False,
        getter=ManyGrey(),
        run_id="fifty-web",
    )
    assert bundle["summary"]["kept"] == 50
    assert bundle["summary"]["blocked"] >= 1
    assert all("scholar.google" not in (r.get("url") or "") for r in bundle["candidates"])
    lib = StubLib()
    result = apply_candidates(cfg, bundle["candidates"], "Gjerde tribute/grey", backend=lib)
    assert result["created"] == 50
    assert len(lib.created) == 50
    assert all((row.get("url") or "").endswith(".pdf") for row in lib.created)


def test_build_query_filetype_and_hosts():
    q = build_query(["Gjerde", "IUCN"], filetype="pdf", hosts=["iucn.org", "undocs.org"])
    assert "filetype:pdf" in q
    assert "site:iucn.org" in q and "site:undocs.org" in q
    none = build_query(["Gjerde"], filetype="none")
    assert "filetype:" not in none.lower()


def test_parse_hosts_dedupes():
    assert parse_hosts("iucn.org, www.iucn.org; undocs.org") == ["iucn.org", "undocs.org"]


def test_score_drops_blocked_and_platform():
    books = Config().grey_playbooks
    assert score_hit(SCHOLAR, title="x", playbooks=books)[0] < 0
    assert score_hit(PUBLISHER, title="x", playbooks=books)[0] < 0
    assert score_hit(WIKI, title="x", playbooks=books)[0] < 0
    pdf_score, _, _ = score_hit(PDF, title="Gjerde", query="Gjerde IUCN", playbooks=books)
    land_score, pb, _ = score_hit(LANDING, title="Gjerde", query="Gjerde IUCN", playbooks=books)
    assert pdf_score > land_score
    assert pb == "iucn-dosi"
    undocs_score, undocs_pb, rewritten = score_hit(
        UNDOCS, title="PrepCom", query="Gjerde", playbooks=books
    )
    assert undocs_score > 0
    assert undocs_pb
    assert rewritten != UNDOCS or "pdf" in rewritten.lower()


def test_run_ranks_and_writes_schema(tmp_path: Path):
    cfg = _cfg(tmp_path)
    bundle = run_search(
        cfg,
        ["Gjerde", "IUCN"],
        hosts="iucn.org,undocs.org",
        max_hits=10,
        probe=True,
        run_id="gjerde-web",
        getter=FakeSearXNG(),
        probe_getter=_probe,
    )
    assert bundle["schema"] == SCHEMA
    assert META_KEYS <= bundle["meta"].keys()
    assert SUMMARY_KEYS <= bundle["summary"].keys()
    urls = {row["url"] for row in bundle["candidates"]}
    assert any("iucn.org" in u or "undocs.org" in u for u in urls)
    assert not any("scholar.google" in u for u in urls)
    assert not any("sciencedirect" in u for u in urls)
    for row in bundle["hits"]:
        assert HIT_KEYS <= row.keys() or row.get("status") == "blocked"
    dest = Path(bundle["path"])
    assert (dest / "meta.json").is_file()
    assert (dest / "hits.jsonl").is_file()
    assert (dest / "candidates.jsonl").is_file()
    assert (dest / "summary.json").is_file()
    loaded = load_run(cfg, "gjerde-web")
    assert loaded["run_id"] == "gjerde-web"
    assert bundle["summary"]["blocked"] >= 2


def test_out_dir_override(tmp_path: Path):
    cfg = _cfg(tmp_path)
    dest = tmp_path / "pack"
    bundle = run_search(
        cfg,
        ["Gjerde"],
        run_id="outdir-web",
        dest=dest,
        probe=False,
        getter=FakeSearXNG(),
    )
    assert Path(bundle["path"]) == dest
    assert (dest / "meta.json").is_file()
    assert not (cfg.state_dir / "search" / "outdir-web" / "meta.json").is_file()


def test_unset_searxng_raises_code_2(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)
    cfg = Config(email="t@example.org", out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.state_dir.mkdir(parents=True)
    cfg.searxng_base_url = ""
    try:
        run_search(cfg, ["Gjerde"], getter=FakeSearXNG(), probe=False)
        raise AssertionError("expected SearchError")
    except SearchError as exc:
        assert exc.code == 2


def test_empty_searxng_is_partial(tmp_path: Path):
    cfg = _cfg(tmp_path)
    bundle = run_search(
        cfg,
        ["Gjerde"],
        run_id="empty-web",
        probe=False,
        getter=lambda _q: {"results": []},
    )
    assert bundle["partial"] is True
    assert bundle["summary"]["kept"] == 0


def test_apply_dry_run_vs_write(tmp_path: Path):
    cfg = _cfg(tmp_path)
    bundle = run_search(
        cfg,
        ["Gjerde"],
        hosts="iucn.org",
        run_id="apply-web",
        probe=False,
        getter=FakeSearXNG(),
    )
    lib = StubLib()
    mark_exists(cfg, bundle["candidates"], backend=lib)
    assert all(row.get("status") in {"new", "exists", "blocked"} for row in bundle["candidates"])
    result = apply_candidates(cfg, bundle["candidates"], "Gjerde tribute/grey", backend=lib)
    assert result["created"] >= 1
    assert lib.created
    extra = str(lib.created[0].get("extra") or "")
    assert "web:searxng" in extra or "grey:" in extra
    lib2 = StubLib(write=False)
    try:
        apply_candidates(cfg, bundle["candidates"], "x", backend=lib2)
        raise AssertionError("expected write-api error")
    except Exception as exc:
        assert "write" in str(exc).lower() or "Zotero" in str(exc)


def test_cli_json_and_exit_2(tmp_path: Path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr("paperful.cli_runtime._cfg", lambda _path=None: cfg)
    monkeypatch.setattr(
        "paperful.snowball.searxng.search_query",
        lambda _c, _q, **_k: FakeSearXNG()(_q)["results"],
    )
    res = runner.invoke(
        cli.app,
        ["search", "Gjerde", "IUCN", "--no-probe", "--run-id", "cli-web", "--format", "json"],
    )
    assert res.exit_code == 0, res.output
    body = json.loads(res.stdout)
    assert body["schema"] == "paperful.agent.json.v1"
    assert body["command"] == "search"
    assert body["summary"]["run_id"] == "cli-web"

    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)
    bare = Config(email="t@example.org", out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    bare.state_dir.mkdir(parents=True, exist_ok=True)
    bare.searxng_base_url = ""
    monkeypatch.setattr("paperful.cli_runtime._cfg", lambda _path=None: bare)
    missing = runner.invoke(cli.app, ["search", "Gjerde"])
    assert missing.exit_code == 2, missing.output


def test_cli_apply_needs_collection(tmp_path: Path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr("paperful.cli_runtime._cfg", lambda _path=None: cfg)
    monkeypatch.setattr(
        "paperful.snowball.searxng.search_query",
        lambda _c, _q, **_k: FakeSearXNG()(_q)["results"],
    )
    res = runner.invoke(cli.app, ["search", "Gjerde", "--apply", "--no-probe"])
    assert res.exit_code == 1
    assert "collection" in res.output.lower()


def test_cli_apply_from_saved_run(tmp_path: Path, monkeypatch):
    cfg = _cfg(tmp_path)
    lib = StubLib()
    monkeypatch.setattr("paperful.cli_runtime._cfg", lambda _path=None: cfg)
    from paperful.search.command import run_search_cmd
    from rich.console import Console

    run_search_cmd(
        Console(),
        ["Gjerde"],
        hosts="iucn.org",
        filetype="pdf",
        max_hits=10,
        probe=False,
        fmt="json",
        config=None,
        run_id="saved-web",
        getter=FakeSearXNG(),
        probe_getter=_probe,
        backend=lib,
    )
    assert not lib.created
    run_search_cmd(
        Console(),
        [],
        hosts="",
        filetype="pdf",
        max_hits=10,
        probe=False,
        fmt="json",
        config=None,
        run_id="saved-web",
        apply=True,
        collection="Gjerde tribute/grey",
        backend=lib,
    )
    assert lib.created


def test_cli_apply_writes_stub(tmp_path: Path, monkeypatch):
    cfg = _cfg(tmp_path)
    lib = StubLib()
    monkeypatch.setattr("paperful.cli_runtime._cfg", lambda _path=None: cfg)
    from paperful.search.command import run_search_cmd
    from rich.console import Console

    run_search_cmd(
        Console(),
        ["Gjerde"],
        hosts="iucn.org",
        filetype="pdf",
        max_hits=10,
        probe=False,
        fmt="json",
        config=None,
        apply=True,
        collection="Gjerde tribute/grey",
        getter=FakeSearXNG(),
        probe_getter=_probe,
        backend=lib,
    )
    assert lib.created


def test_search_max_toml(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(
        'email = "me@example.org"\n\n[search]\nmax = 7\nprobe = false\n\n[ui]\nweb_search = "off"\n',
        encoding="utf-8",
    )
    loaded = load_config(p)
    assert loaded.search_max == 7
    assert loaded.search_probe is False
    assert loaded.ui_web_search == "off"


def test_exists_via_lookup(tmp_path: Path):
    cfg = _cfg(tmp_path)
    hit = SimpleNamespace(item_key="EXISTING")

    def lookup(**_kwargs):
        return hit

    bundle = run_search(
        cfg,
        ["Gjerde"],
        hosts="iucn.org",
        probe=False,
        getter=FakeSearXNG(),
        lookup=lookup,
        run_id="exists-web",
    )
    assert bundle["summary"]["exists"] >= 1
    assert all(row.get("status") == "exists" for row in bundle["candidates"])
