"""``paperful since``: read-only diff against the last run report."""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from paperful import cli, cli_runtime
from paperful.since import (
    NOTHING_CHANGED,
    SCHEMA,
    SINCE_PACK_KEYS,
    Baseline,
    find_baseline,
    healed_rows,
    probe_item,
    write_pack,
)
from paperful.sources import REGISTRY, Candidate, Context, Outcome
from tests.conftest import make_item, mock_client

FIX = Path(__file__).parent / "fixtures" / "since_pack_v1"
runner = CliRunner()
RETRACTED = {"10.1000/retracted", "10.1000/oldretracted"}


def _items():
    return [
        make_item(
            key="HEALED01",
            title="A paper that became open access",
            doi="10.1000/healed",
        ),
        make_item(
            key="STILL001", title="A paper that is still closed", doi="10.1000/still"
        ),
        make_item(
            key="GOTPDF01",
            title="A miss the operator filled by hand",
            doi="10.1000/got",
            has_pdf=True,
        ),
        make_item(
            key="HELD0001",
            title="A held paper later retracted",
            doi="10.1000/retracted",
            has_pdf=True,
        ),
        make_item(
            key="OLDRETR1",
            title="A retraction already reported",
            doi="10.1000/oldretracted",
            has_pdf=True,
        ),
    ]


class ReadOnlyBackend:
    """Only the read ``since`` needs. Any write attempt is an AttributeError."""

    def __init__(self, items):
        self._items = items

    def items_in_scope(self, keys):
        return list(self._items)


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        f'email = "t@example.org"\nout_dir = "{(tmp_path / "out").as_posix()}"\n'
        f'state_dir = "{(tmp_path / "state").as_posix()}"\nsources = ["unpaywall", "direct"]\n'
    )
    return p


def _save(tmp_path, fixture: str, name: str) -> None:
    runs = tmp_path / "state" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIX / fixture, runs / name)


@pytest.fixture
def wired(monkeypatch):
    """Fake backend, fake status lookup, and an HTTP client that logs every URL."""
    seen: list[str] = []
    state = {"items": _items(), "oa": {"10.1000/healed"}, "retracted": set(RETRACTED)}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        doi = request.url.path.removeprefix("/v2/")
        if request.url.host == "api.unpaywall.org" and doi in state["oa"]:
            loc = {"url_for_pdf": f"https://oa.example.org/{doi}.pdf"}
            return httpx.Response(200, json={"best_oa_location": loc})
        return httpx.Response(404, json={})

    monkeypatch.setattr(
        cli_runtime,
        "_connect",
        lambda cfg, quiet=False: ReadOnlyBackend(state["items"]),
    )
    monkeypatch.setattr(cli_runtime, "_scope_keys", lambda b, c, lib: (None, "library"))
    monkeypatch.setattr(
        "paperful.pipeline.make_client", lambda cfg: mock_client(handler)
    )
    monkeypatch.setattr(
        "paperful.screen.lookup_doi_status",
        lambda client, cfg, doi, refresh=False: (
            ["retracted"] if refresh and doi in state["retracted"] else []
        ),
    )
    state["seen"] = seen
    return state


def _run(cfg_file, *extra):
    return runner.invoke(
        cli.app, ["since", "--library", "--config", str(cfg_file), *extra]
    )


def _pack(tmp_path) -> dict:
    folders = sorted((tmp_path / "state" / "since").iterdir())
    body = json.loads((folders[-1] / "since.json").read_text(encoding="utf-8"))
    assert (folders[-1] / "since.md").is_file()
    body["created_at"] = ""
    return body


def _golden(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_pack_keys_match_golden():
    assert _golden("keys.json") == sorted(SINCE_PACK_KEYS)
    assert _golden("pack.json")["schema"] == SCHEMA


def test_one_healed_miss_and_one_new_retraction(tmp_path, cfg_file, wired):
    _save(tmp_path, "run-report.json", "20261101T090000Z-run.json")
    _save(tmp_path, "screen-report.json", "20261102T090000Z-screen.json")
    res = _run(cfg_file)
    assert res.exit_code == 0, res.output
    assert _pack(tmp_path) == _golden("pack.json")
    # Only earlier misses that still lack a PDF are probed, on a metadata lane.
    assert sorted(wired["seen"]) == [
        "https://api.unpaywall.org/v2/10.1000/healed?email=t%40example.org",
        "https://api.unpaywall.org/v2/10.1000/still?email=t%40example.org",
    ]
    assert not list((tmp_path / "out").rglob("*.pdf"))
    assert (tmp_path / "state" / "runs").glob("*-since.json")


def test_nothing_changed_is_exit_0_with_an_empty_pack(tmp_path, cfg_file, wired):
    _save(tmp_path, "run-report.json", "20261101T090000Z-run.json")
    _save(tmp_path, "screen-report.json", "20261102T090000Z-screen.json")
    wired["oa"].clear()
    wired["retracted"].discard("10.1000/retracted")
    res = _run(cfg_file)
    assert res.exit_code == 0, res.output
    assert NOTHING_CHANGED in res.output
    assert _pack(tmp_path) == _golden("empty_pack.json")


def test_no_baseline_says_so_and_still_reports_retractions(tmp_path, cfg_file, wired):
    res = _run(cfg_file)
    assert res.exit_code == 0, res.output
    pack = _pack(tmp_path)
    assert pack["baseline"] is None
    assert pack["healed"] == []
    assert "healed misses not compared" in pack["notes"][0]
    assert {row["itemKey"] for row in pack["holdings"]} == {"HELD0001", "OLDRETR1"}
    assert pack["holdings"][0]["compared_to"] == "no prior screen report"
    assert wired["seen"] == []


def test_a_retraction_is_news_once(tmp_path, cfg_file, wired):
    state_dir = tmp_path / "state"
    first = {
        "kind": "retracted",
        "itemKey": "HELD0001",
        "title": "A held paper later retracted",
        "verb": "screen",
        "compared_to": "no prior screen report",
    }
    write_pack(
        state_dir, "library", None, [first], [], {}, [], stamp="20261103T000000Z"
    )
    write_pack(state_dir, "other", None, [], [], {}, [], stamp="20261104T000000Z")
    wired["retracted"].discard("10.1000/oldretracted")
    assert _run(cfg_file).exit_code == 0
    assert _pack(tmp_path)["holdings"] == []


def test_since_date_picks_an_older_report(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()

    def save(stamp, day, scope="library", flags=None):
        body = {
            "scope": scope,
            "finished_at": f"{day}T09:00:00+00:00",
            "flags": flags or {},
        }
        (runs / f"{stamp}-run.json").write_text(json.dumps(body))

    save("20261001T090000Z", "2026-10-01")
    save("20261101T090000Z", "2026-11-01")
    save("20261102T090000Z", "2026-11-02", scope="other")
    save("20261103T090000Z", "2026-11-03", flags={"dry_run": True})
    (runs / "20261104T090000Z-run.json").write_text("{not json")

    newest = find_baseline(tmp_path, "library")
    assert newest and newest.finished_at.startswith("2026-11-01")
    assert newest.label == "2026-11-01"  # no witness: the date names it
    older = find_baseline(tmp_path, "library", before=date(2026, 10, 15))
    assert older and older.finished_at.startswith("2026-10-01")
    assert find_baseline(tmp_path, "library", before=date(2026, 9, 1)) is None


def test_bad_since_date_exits_1(cfg_file):
    res = _run(cfg_file, "--since", "last week")
    assert res.exit_code == 1
    assert "YYYY-MM-DD" in res.output


def test_requires_scope(cfg_file):
    res = runner.invoke(cli.app, ["since", "--config", str(cfg_file)])
    assert res.exit_code == 1


def test_healed_rows_rank_by_cites_times_severity_then_limit():
    rows = [
        {"itemKey": "LOW", "miss_surface": "no_oa"},
        {"itemKey": "HIGH", "miss_surface": "paywalled"},
        {"itemKey": "GONE", "miss_surface": "paywalled"},
        {"itemKey": "FINE", "status": "attached", "miss_surface": "import_ok"},
    ]
    baseline = Baseline(
        Path("r.json"), "2026-11-01T09:00:00+00:00", "abc123def456", rows
    )
    items = [
        make_item(key="LOW", doi="10.1/low"),
        make_item(key="HIGH", doi="10.1/high"),
        make_item(key="FINE", doi="10.1/fine"),
    ]
    probed: list[str] = []

    def probe(item):
        probed.append(item.key)
        return Candidate(
            url=f"https://oa.example.org/{item.key}.pdf", source="openalex"
        )

    healed, counts = healed_rows(baseline, items, probe, {"LOW": 3, "HIGH": 2})
    assert [row["itemKey"] for row in healed] == ["HIGH", "LOW"]  # 2×4 beats 3×2
    assert healed[0]["compared_to"] == "abc123def456"
    assert counts == {"healed_candidates": 2, "probed": 2}

    probed.clear()
    healed, counts = healed_rows(baseline, items, probe, {"LOW": 3, "HIGH": 2}, limit=1)
    assert probed == ["HIGH"]
    assert counts == {"healed_candidates": 2, "probed": 1}


def test_probe_never_uses_a_lane_that_fetches_bytes(cfg, monkeypatch):
    called: list[str] = []

    class Lane:
        def __init__(self, name, cand=None):
            self.name, self.cand = name, cand

        def find(self, item, ctx):
            called.append(self.name)
            return self.cand or Candidate.miss(self.name, Outcome.NOT_FOUND)

    hit = Candidate(url="https://oa.example.org/a.pdf", source="openalex")
    bytes_hit = Candidate(
        url="https://x.example.org/a.pdf", source="core", content=b"%PDF"
    )
    monkeypatch.setitem(REGISTRY, "htmlpdf", Lane("htmlpdf", hit))
    monkeypatch.setitem(REGISTRY, "unpaywall", Lane("unpaywall"))
    monkeypatch.setitem(REGISTRY, "core", Lane("core", bytes_hit))
    monkeypatch.setitem(REGISTRY, "openalex", Lane("openalex", hit))
    ctx = Context(config=cfg, client=mock_client(lambda r: httpx.Response(500)))

    got = probe_item(make_item(), ctx, ["htmlpdf", "unpaywall", "core", "openalex"])
    assert got is hit
    assert called == ["unpaywall", "core", "openalex"]
    assert probe_item(make_item(), ctx, ["htmlpdf"]) is None
