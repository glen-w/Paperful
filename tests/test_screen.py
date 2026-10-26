"""Tests for paperful screen (fingerprints, status, CLI)."""

from __future__ import annotations

import httpx

from paperful.screen import (
    crossref_update_codes,
    match_fingerprint,
    scan_text_fingerprints,
    tokens_in_window,
    FingerprintRow,
)


def test_tokens_in_window_ordered_proximity():
    text = "we use vanishing gradient problem in deep nets"
    assert tokens_in_window(text, ["vanishing", "gradient", "problem"], 5)
    assert not tokens_in_window(text, ["gradient", "vanishing"], 3)


def test_match_fingerprint_and_proximity():
    assert match_fingerprint("hello neural network world", '"neural network"')
    assert match_fingerprint("a b c d e", '"b c"~3')
    assert match_fingerprint("foo bar AND baz", "foo AND baz")
    assert not match_fingerprint("foo only", "foo AND baz")


def test_scan_tortured_requires_min_or_obvious():
    rows = [
        FingerprintRow('"alpha one"', "a"),
        FingerprintRow('"alpha two"', "b"),
        FingerprintRow('"alpha three"', "c"),
        FingerprintRow('"alpha four"', "d"),
        FingerprintRow('"sign to clamor"', "signal-to-noise"),
    ]
    text4 = "alpha one alpha two alpha three alpha four"
    assert not scan_text_fingerprints(text4, rows, family="tortured", tortured_min=5)
    text5 = text4 + " alpha five extra"
    rows5 = rows + [FingerprintRow('"alpha five"', "e")]
    assert scan_text_fingerprints(text5, rows5, family="tortured", tortured_min=5)
    assert scan_text_fingerprints(
        "we report sign to clamor ratio",
        rows,
        family="tortured",
        tortured_min=5,
    )


def test_crossref_update_codes_retraction():
    msg = {
        "update-to": [
            {"type": "retraction", "DOI": "10.1/x"},
            {"type": "expression_of_concern", "DOI": "10.1/y"},
        ]
    }
    codes = crossref_update_codes(msg)
    assert "retracted" in codes
    assert "expression_of_concern" in codes


def test_load_fingerprints_from_cache(tmp_path, monkeypatch):
    from paperful.config import Config
    from paperful.screen import load_fingerprints

    cfg = Config()
    cfg.state_dir = tmp_path / "state"
    cfg.email = "test@example.org"
    cfg.screen_fingerprint_max_age_days = 14
    cache = cfg.state_dir / "pps" / "fingerprints" / "suspect.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(
        '{"family":"suspect","fetched_at":9999999999,"rows":[["\\"foo bar\\"","expected"]]}',
        encoding="utf-8",
    )
    client = httpx.Client()
    rows = load_fingerprints(client, cfg, "suspect")
    client.close()
    assert len(rows) == 1
    assert rows[0].expression == '"foo bar"'


def test_load_fingerprints_offline_uses_cache(tmp_path):
    from paperful.config import Config
    from paperful.screen import load_fingerprints

    cfg = Config()
    cfg.state_dir = tmp_path / "state"
    cache = cfg.state_dir / "pps" / "fingerprints" / "tortured.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(
        '{"family":"tortured","fetched_at":1,"rows":[["sign to clamor","snr"]]}',
        encoding="utf-8",
    )
    rows = load_fingerprints(None, cfg, "tortured", offline=True)
    assert len(rows) == 1
    assert "clamor" in rows[0].expression


def test_load_fingerprints_fingerprint_dir_csv(tmp_path):
    from paperful.config import Config
    from paperful.screen import load_fingerprints

    cfg = Config()
    cfg.state_dir = tmp_path / "state"
    folder = tmp_path / "pps-fingerprints"
    folder.mkdir()
    (folder / "tortured.csv").write_text(
        "Fingerprint,Expected\n\"sign to clamor\",signal-to-noise\n",
        encoding="utf-8",
    )
    cfg.screen_fingerprint_dir = folder
    rows = load_fingerprints(None, cfg, "tortured", offline=True)
    assert len(rows) == 1


def test_lookup_doi_status_crossref_and_openalex(cfg, monkeypatch):
    from paperful.screen import lookup_doi_status

    def fake_crossref(client, doi, email):
        return ["retracted"]

    def fake_oa(client, doi, email):
        return False

    monkeypatch.setattr("paperful.screen.lookup_crossref_status", fake_crossref)
    monkeypatch.setattr("paperful.screen.lookup_openalex_retracted", fake_oa)
    client = httpx.Client()
    codes = lookup_doi_status(client, cfg, "10.1000/example", refresh=True)
    client.close()
    assert codes == ["retracted"]


def test_pubpeer_lookup_batch(monkeypatch):
    from paperful.screen import pubpeer_lookup

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(
            200,
            json={
                "feedbacks": [
                    {
                        "id": "10.1000/a",
                        "total_comments": 2,
                        "url": "https://pubpeer.com/publications/abc",
                    }
                ]
            },
        )

    monkeypatch.setenv("PUBPEER_DEVKEY", "test-key")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = pubpeer_lookup(client, ["10.1000/a", "10.1000/b"])
    client.close()
    assert out["10.1000/a"]["total_comments"] == 2


def test_apply_screen_writes_tag_and_note(cfg):
    from unittest.mock import MagicMock

    from paperful.screen import ScreenFinding, apply_screen
    from tests.conftest import make_item

    backend = MagicMock()
    item = make_item(key="K1")
    findings = [
        ScreenFinding(
            itemKey="K1",
            code="retracted",
            title=item.title,
            detail="status",
            doi="10.1000/test.doi",
        )
    ]
    n = apply_screen(backend, cfg, [item], findings)
    assert n == 1
    backend.replace_prefixed_tag.assert_called_once()
    backend.create_or_update_note.assert_called_once()
    args = backend.create_or_update_note.call_args[0]
    assert args[2] == cfg.screen_tag


def test_fingerprint_cache_and_csv_edges(cfg, tmp_path):
    from paperful.screen import (
        _fingerprint_stale,
        _read_fingerprint_cache_file,
        fingerprint_cache_age_days,
        load_fingerprints,
        parse_fingerprint_csv,
        tokens_in_window,
    )

    assert tokens_in_window("hello", [], 5) is False
    assert parse_fingerprint_csv("fingerprint,expected\nonlyone\nexpr,val\n")[0].expression == "expr"
    assert load_fingerprints(None, cfg, "nope") == []

    folder = cfg.state_dir / "pps" / "fingerprints"
    folder.mkdir(parents=True)
    bad = folder / "tortured.json"
    bad.write_text("{not-json", encoding="utf-8")
    assert _fingerprint_stale(cfg, "tortured") is True
    assert _read_fingerprint_cache_file(bad) == []
    missing = folder / "gone.json"
    assert _read_fingerprint_cache_file(missing) == []

    csv_path = folder / "scigen.csv"
    csv_path.write_text("fingerprint,expected\nfoo,bar\n", encoding="utf-8")
    rows = _read_fingerprint_cache_file(csv_path)
    assert rows[0].expected == "bar"

    empty_dir = cfg.state_dir / "pps" / "fingerprints"
    (empty_dir / "empty.json").write_text('{"fetched_at": "nope"}\n', encoding="utf-8")
    # no valid fetched_at → skip; plus a good one
    good = folder / "mathgen.json"
    good.write_text(
        '{"fetched_at": 100.0, "rows": [["a", "b"], "skip"]}',
        encoding="utf-8",
    )
    age = fingerprint_cache_age_days(cfg)
    assert age is not None and age > 0

    cfg.screen_fingerprint_dir = tmp_path / "fps"
    cfg.screen_fingerprint_dir.mkdir()
    (cfg.screen_fingerprint_dir / "suspect.json").write_text(
        '{"rows": [["x", "y"]]}', encoding="utf-8"
    )
    local = load_fingerprints(None, cfg, "suspect", offline=True)
    assert local and local[0].expression == "x"


def test_status_lookups_handle_http_errors(cfg):
    from paperful.screen import (
        crossref_update_codes,
        lookup_crossref_status,
        lookup_doi_status,
        lookup_openalex_retracted,
        pdf_text,
        pubpeer_lookup,
        pubpeer_ready,
    )
    from tests.conftest import make_item

    assert "retracted" in crossref_update_codes(
        {"relation": [{"relation-type": "is-retracted-by"}]}
    )
    assert "withdrawn" in crossref_update_codes(
        {"update-to": [{"type": "withdrawal"}]}
    )
    assert "expression_of_concern" in crossref_update_codes(
        {"update-to": [{"type": "expression of concern"}]}
    )

    def handler(req: httpx.Request):
        if "crossref" in req.url.host:
            return httpx.Response(404)
        if "openalex" in req.url.host:
            return httpx.Response(404)
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        assert lookup_crossref_status(client, "10.1000/x", "t@example.org") == []
        assert lookup_openalex_retracted(client, "10.1000/x", "t@example.org") is False
        assert lookup_doi_status(client, cfg, "") == []
        assert pubpeer_lookup(client, []) == {}
        assert pubpeer_ready(cfg) is False
        assert pdf_text(cfg, make_item(), None, None) == ""
    finally:
        client.close()


def test_screen_items_status_and_callbacks(cfg, monkeypatch):
    from paperful.screen import ScreenFinding, screen_item, screen_items
    from tests.conftest import make_item

    cfg.screen_detectors = ["retracted"]
    item = make_item(doi="10.1000/test.doi")
    monkeypatch.setattr(
        "paperful.screen.prepare_identifiers", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "paperful.screen.lookup_doi_status", lambda *_a, **_k: ["retracted"]
    )
    started = []
    seen = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    try:
        rows = screen_items(
            client,
            cfg,
            [item],
            on_start=lambda it: started.append(it.key),
            on_item=lambda it, f: seen.append(len(f)),
        )
        one = screen_item(client, cfg, item)
    finally:
        client.close()
    assert started == [item.key]
    assert seen == [1]
    assert any(f.code == "retracted" for f in rows)
    assert any(isinstance(f, ScreenFinding) and f.code == "retracted" for f in one)


def test_apply_screen_swallows_tag_errors(cfg):
    from paperful.screen import ScreenFinding, apply_screen, _note_body, _tag_summary
    from tests.conftest import make_item

    class Backend:
        def replace_prefixed_tag(self, *_a, **_k):
            raise RuntimeError("tag fail")

        def create_or_update_note(self, *_a, **_k):
            raise RuntimeError("note fail")

    item = make_item(key="K2", doi="10.1000/x")
    findings = [
        ScreenFinding(itemKey="K2", code="retracted", title=item.title, detail="x", doi=item.doi, url="https://ex.org"),
        ScreenFinding(itemKey="K2", code="pubpeer", title=item.title, detail="y"),
    ]
    assert apply_screen(Backend(), cfg, [item, make_item(key="NONE")], findings) == 0
    html = _note_body(findings, item)
    assert "PPS report" in html
    assert "retracted (1)" in _tag_summary(findings) or "retracted" in _tag_summary(
        findings[:1]
    )
