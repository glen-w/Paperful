"""Crossref title lookup against a mocked API."""

import json

import httpx

from paperful.resolve import crossref_lookup, short_title
from tests.conftest import mock_client


def _works(*items):
    return httpx.Response(200, content=json.dumps({"message": {"items": list(items)}}).encode())


def _work(doi, title, year=None):
    w = {"DOI": doi, "title": [title]}
    if year:
        w["issued"] = {"date-parts": [[year]]}
    return w


def test_confident_match_sends_mailto_and_author():
    seen = {}

    def handler(req):
        seen.update(req.url.params)
        return _works(_work("10.1/GOOD", "Marine genetic resources beyond national jurisdiction", 2019))

    m = crossref_lookup(mock_client(handler), "Marine genetic resources beyond national jurisdiction", author="Smith", year=2019, email="me@x.org")
    assert m and m.doi == "10.1/good" and m.score >= 0.9 and m.year == 2019
    assert seen["mailto"] == "me@x.org" and seen["query.author"] == "Smith"


def test_weak_match_and_year_mismatch_rejected():
    client = mock_client(lambda r: _works(_work("10.1/x", "Something completely different about fisheries", 2019)))
    assert crossref_lookup(client, "Marine genetic resources beyond national jurisdiction") is None
    client2 = mock_client(lambda r: _works(_work("10.1/x", "Marine genetic resources beyond national jurisdiction", 2005)))
    # exact title but 14 years off -> score penalised below the 0.95 bar
    assert crossref_lookup(client2, "Marine genetic resources beyond national jurisdiction", year=2019, min_score=0.95) is None


def test_short_title_retry_when_subtitle_glued_on():
    calls = []

    def handler(req):
        q = req.url.params["query.bibliographic"]
        calls.append(q)
        if q.startswith("Marine genetic resources beyond national jurisdiction."):
            return _works(_work("10.1/other", "Unrelated"))
        return _works(_work("10.1/short", "Marine genetic resources beyond national jurisdiction"))

    title = "Marine genetic resources beyond national jurisdiction. A very long subtitle that Crossref does not index at all"
    m = crossref_lookup(mock_client(handler), title)
    assert m and m.doi == "10.1/short"
    assert len(calls) == 2 and calls[1] == "Marine genetic resources beyond national jurisdiction"


def test_short_title_heuristics():
    assert short_title("Main title here please: and a subtitle") == "Main title here please"
    assert short_title("Too short: subtitle") is None
    assert short_title("Version 2.0 of the plan is here") == "Version 2.0 of the plan is here"


def test_too_short_title_and_api_errors_return_none():
    client = mock_client(lambda r: httpx.Response(500))
    assert crossref_lookup(client, "Short") is None
    assert crossref_lookup(client, "A perfectly reasonable title of some length") is None
    bad_json = mock_client(lambda r: httpx.Response(200, content=b"<html>"))
    assert crossref_lookup(bad_json, "A perfectly reasonable title of some length") is None
