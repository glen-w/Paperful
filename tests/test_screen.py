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
