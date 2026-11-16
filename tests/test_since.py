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
    keepup_rows,
    prior_holdings,
    prior_urls,
    probe_item,
    scope_matcher,
    snapshot_rows,
    status_rows,
    url_rows,
    version_rows,
    write_pack,
)
from paperful.urls import UrlFinding, UrlTarget
from paperful.versions import VersionProposal
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
        "paperful.screen.doi_status",
        lambda client, cfg, doi, max_age=None: (
            ["retracted"] if doi in state["retracted"] else [],
            not state["status_down"],
        ),
    )
    monkeypatch.setattr(
        "paperful.versions.classify_versions", lambda items, resolve: state["versions"]
    )
    monkeypatch.setattr(
        "paperful.versions.resolver_for", lambda client, email: lambda doi: None
    )
    state["seen"] = seen
    state["status_down"] = False
    state["versions"] = []
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
    assert "healed misses not compared" in pack["notes"][-1]
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

    newest = find_baseline(tmp_path, scope_matcher("library"))
    assert newest and newest.finished_at.startswith("2026-11-01")
    assert newest.label == "2026-11-01"  # no witness: the date names it
    older = find_baseline(tmp_path, scope_matcher("library"), before=date(2026, 10, 15))
    assert older and older.finished_at.startswith("2026-10-01")
    assert (
        find_baseline(tmp_path, scope_matcher("library"), before=date(2026, 9, 1))
        is None
    )


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

    def probe(item, skip):
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


def _proposal(key: str) -> VersionProposal:
    return VersionProposal(
        item_key=key,
        title=f"Preprint {key}",
        preprint_doi="10.1101/pre",
        arxiv_id=None,
        published_doi=f"10.1000/{key.lower()}",
        source="crossref",
        confidence="high",
        title_score=1.0,
        before={},
        after={},
        primary_pdf="",
        sibling_key=None,
    )


def test_version_of_record_is_new_only_against_the_last_versions_pack(tmp_path):
    packs = tmp_path / "version-packs"
    packs.mkdir()
    body = {
        "scope": "library",
        "created_at": "2026-11-05T00:00:00+00:00",
        "proposals": [{"item_key": "KNOWN001"}],
    }
    (packs / "20261105T000000Z-library.json").write_text(json.dumps(body))
    seen, vs = prior_holdings(tmp_path, scope_matcher("library"))
    rows = version_rows(
        [_proposal("KNOWN001"), _proposal("FRESH001")], seen, vs["versions"]
    )
    assert [row["itemKey"] for row in rows] == ["FRESH001"]
    assert rows[0]["compared_to"] == "versions 2026-11-05"
    assert rows[0]["doi"] == "10.1000/fresh001"
    assert "screen" not in vs  # no screen report: the retraction label says so


def test_url_rows_only_reprobe_urls_the_last_report_could_open(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    report = {
        "scope": "library",
        "finished_at": "2026-11-06T00:00:00+00:00",
        "items": [
            {"item_key": "WASOK001", "url": "https://a.example.org/x", "code": "ok"},
            {
                "item_key": "STAYOK01",
                "url": "https://b.example.org/x",
                "code": "redirect",
            },
            {
                "item_key": "WASDEAD1",
                "url": "https://c.example.org/x",
                "code": "hard_dead",
            },
        ],
    }
    (runs / "20261106T000000Z-urls.json").write_text(json.dumps(report))
    assert prior_urls(tmp_path, scope_matcher("other")) is None
    prior, compared_to = prior_urls(tmp_path, scope_matcher("library"))
    targets = [
        UrlTarget("WASOK001", "https://a.example.org/x", "parent"),
        UrlTarget("STAYOK01", "https://b.example.org/x", "parent"),
        UrlTarget("WASDEAD1", "https://c.example.org/x", "parent"),
        UrlTarget("NEVER001", "https://d.example.org/x", "parent"),
    ]
    probed: list[str] = []

    def probe(target):
        probed.append(target.item_key)
        code = "ok" if target.item_key == "STAYOK01" else "hard_dead"
        return UrlFinding(target.item_key, target.url, target.role, code)

    rows = url_rows(targets, {"WASOK001": "T"}, prior, probe, set(), compared_to)
    assert probed == ["WASOK001", "STAYOK01"]
    assert [(r["itemKey"], r["kind"], r["was"]) for r in rows] == [
        ("WASOK001", "hard_dead", "ok")
    ]
    assert rows[0]["compared_to"] == "urls 2026-11-06"
    assert url_rows(targets, {}, prior, probe, {("WASOK001", "hard_dead")}, "") == []


def test_snapshot_rows_probe_snapshot_tier_only():
    items = [
        make_item(key="SNAP0001", has_pdf=True, pdf_tier="snapshot"),
        make_item(key="SNAP0002", has_pdf=True, pdf_tier="snapshot"),
        make_item(key="NATIVE01", has_pdf=True, pdf_tier="native"),
    ]
    probed: list[str] = []

    def probe(item, skip):
        probed.append(item.key)
        if item.key == "SNAP0002":
            return None
        return Candidate(url="https://oa.example.org/s.pdf", source="unpaywall")

    rows = snapshot_rows(items, probe, set())
    assert probed == ["SNAP0001", "SNAP0002"]
    assert [row["itemKey"] for row in rows] == ["SNAP0001"]
    assert rows[0]["suggested_action"] == "paperful run --upgrade-snapshot"
    probed.clear()
    assert (
        snapshot_rows(items, probe, {("SNAP0001", "snapshot_upgrade")}, limit=1) == []
    )
    assert probed == ["SNAP0002"]


def test_keepup_parents_without_a_pdf():
    items = [
        make_item(key="KEEPUP01", doi="10.1000/New"),
        make_item(key="FILLED01", doi="10.1000/filled", has_pdf=True),
        make_item(key="OTHER001", doi="10.1000/other"),
    ]
    applied = {"doi:10.1000/new", "doi:10.1000/filled"}
    rows = keepup_rows(items, applied, set())
    assert [row["itemKey"] for row in rows] == ["KEEPUP01"]
    assert keepup_rows(items, applied, {("KEEPUP01", "keepup_no_pdf")}) == []


def test_cli_joins_version_and_keepup_rows(tmp_path, cfg_file, wired):
    job = tmp_path / "state" / "keepup" / "weekly"
    job.mkdir(parents=True)
    (job / "job.json").write_text("{}")
    (job / "applied.json").write_text(json.dumps({"identities": ["doi:10.1000/still"]}))
    wired["versions"] = [_proposal("HELD0001")]
    wired["retracted"].clear()
    res = _run(cfg_file)
    assert res.exit_code == 0, res.output
    kinds = {(row["itemKey"], row["kind"]) for row in _pack(tmp_path)["holdings"]}
    assert kinds == {("HELD0001", "version_of_record"), ("STILL001", "keepup_no_pdf")}


def test_a_lane_that_already_answered_in_the_baseline_is_not_a_heal():
    """The baseline run had the URL and could not fetch it: nothing changed."""
    rows = [
        {
            "itemKey": "SAME0001",
            "miss_surface": "paywalled",
            "attempts": [
                "unpaywall:not_found(no OA location)",
                "semanticscholar:found(BRONZE)",
                "semanticscholar:download-failed(HTTP 403)",
            ],
        },
        {
            "itemKey": "NEW00001",
            "miss_surface": "paywalled",
            "attempts": ["semanticscholar:not_found"],
        },
    ]
    baseline = Baseline(Path("r.json"), "2026-11-01T09:00:00+00:00", "", rows)
    items = [make_item(key="SAME0001"), make_item(key="NEW00001")]
    skipped: dict[str, frozenset[str]] = {}

    def probe(item, skip):
        skipped[item.key] = skip
        if "semanticscholar" in skip:
            return None
        return Candidate(url="https://oa.example.org/x.pdf", source="semanticscholar")

    healed, _counts = healed_rows(baseline, items, probe, {})
    assert [row["itemKey"] for row in healed] == ["NEW00001"]
    assert skipped == {
        "SAME0001": frozenset({"semanticscholar"}),
        "NEW00001": frozenset(),
    }


def test_one_collection_under_three_labels_is_one_scope(tmp_path):
    """-C takes a name, a path, or a key; the saved label is whatever was typed."""
    keys = {"BBNJ": "COLL0001", "ocean/BBNJ": "COLL0001", "COLL0001": "COLL0001"}

    def resolve(spec: str) -> str:
        if spec not in keys:
            raise LookupError(spec)
        return keys[spec]

    same = scope_matcher("COLL0001", frozenset({"COLL0001"}), resolve)
    assert same({"scope": "BBNJ"})
    assert same({"scope": "x", "witness": {"scope": {"collections": ["ocean/BBNJ"]}}})
    assert not same({"scope": "a collection since deleted"})
    assert not same(
        {
            "scope": "BBNJ, years 2023–2026",
            "witness": {"scope": {"collections": ["BBNJ"], "year_from": 2023}},
        }
    )

    runs = tmp_path / "runs"
    runs.mkdir()
    body = {"scope": "ocean/BBNJ", "finished_at": "2026-11-01T09:00:00+00:00"}
    (runs / "20261101T090000Z-run.json").write_text(json.dumps(body))
    assert find_baseline(tmp_path, same) is not None
    assert find_baseline(tmp_path, scope_matcher("COLL0001")) is None


def test_limit_must_be_positive(cfg_file):
    assert _run(cfg_file, "--limit", "0").exit_code == 2


def test_baseline_keeps_misses_a_retry_run_did_not_revisit(tmp_path):
    """A --retry-failed report lists only what it retried."""
    runs = tmp_path / "runs"
    runs.mkdir()

    def save(stamp, day, items):
        body = {"scope": "library", "finished_at": f"{day}T09:00:00+00:00"}
        (runs / f"{stamp}-run.json").write_text(json.dumps({**body, "items": items}))

    save(
        "20261001T090000Z",
        "2026-10-01",
        [
            {"itemKey": "OLDMISS1", "miss_surface": "paywalled"},
            {"itemKey": "RETRIED1", "miss_surface": "paywalled"},
        ],
    )
    save(
        "20261101T090000Z",
        "2026-11-01",
        [{"itemKey": "RETRIED1", "status": "attached", "miss_surface": "import_ok"}],
    )
    baseline = find_baseline(tmp_path, scope_matcher("library"))
    assert baseline.finished_at.startswith("2026-11-01") and baseline.reports == 2
    rows = {row["itemKey"]: row for row in baseline.items}
    assert rows["RETRIED1"]["status"] == "attached"  # newest row wins
    assert rows["OLDMISS1"]["compared_to"] == "2026-10-01"

    items = [make_item(key="OLDMISS1"), make_item(key="RETRIED1")]
    cand = Candidate(url="https://oa.example.org/x.pdf", source="openalex")
    healed, counts = healed_rows(baseline, items, lambda item, skip: cand, {})
    assert [(r["itemKey"], r["compared_to"]) for r in healed] == [
        ("OLDMISS1", "2026-10-01")
    ]
    assert counts["healed_candidates"] == 1


def test_severity_orders_misses_when_nothing_has_a_cite_count():
    rows = [
        {"itemKey": "AAAA", "miss_surface": "no_oa"},
        {"itemKey": "ZZZZ", "miss_surface": "paywalled"},
    ]
    baseline = Baseline(Path("r.json"), "2026-11-01T09:00:00+00:00", "", rows)
    items = [make_item(key="AAAA", title="A"), make_item(key="ZZZZ", title="Z")]
    probed: list[str] = []
    healed_rows(baseline, items, lambda i, skip: probed.append(i.key), {}, limit=1)
    assert probed == ["ZZZZ"]


def test_status_rows_keep_item_order_across_threads():
    items = [make_item(key=f"K{n:03d}", doi=f"10.1/{n}") for n in range(40)]
    items.append(make_item(key="NODOI", doi=None))
    ticks: list[tuple[int, int]] = []
    rows = status_rows(
        items,
        lambda doi: ["retracted"] if int(doi.split("/")[1]) % 2 else [],
        {("K001", "retracted")},
        "",
        workers=8,
        on_progress=lambda done, total: ticks.append((done, total)),
    )
    assert [row["itemKey"] for row in rows] == [f"K{n:03d}" for n in range(3, 40, 2)]
    assert ticks[-1] == (40, 40)


def test_a_failed_status_lookup_is_said_out_loud(tmp_path, cfg_file, wired):
    """Offline must not read as "Nothing changed"."""
    wired["status_down"] = True
    result = _run(cfg_file)
    assert result.exit_code == 0
    notes = " ".join(_pack(tmp_path)["notes"])
    assert "could not be checked for 5 DOI(s)" in notes


def test_a_lane_error_is_counted_not_read_as_no(cfg, monkeypatch):
    from collections import Counter

    class Down:
        def find(self, item, ctx):
            return Candidate(url="", source="core", outcome=Outcome.ERROR)

    monkeypatch.setitem(REGISTRY, "core", Down())
    errors: Counter[str] = Counter()
    assert (
        probe_item(make_item(), Context(config=cfg, client=None), ["core"], errors)
        is None
    )
    assert errors == {"core": 1}
