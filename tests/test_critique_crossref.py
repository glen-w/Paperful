"""Crossref helper used by critique bibliography checks (mocked HTTP)."""

from __future__ import annotations

import httpx

from paperful.critique_checks import _crossref_work, _float_kind


def test_float_kind_prefixes():
    assert _float_kind("Figure") == "fig"
    assert _float_kind("Table.") == "tab"
    assert _float_kind("Equation") == "eq"
    assert _float_kind("Box") == "box"


def test_crossref_work_paths(cfg):
    def handler(req: httpx.Request):
        path = str(req.url)
        if "gone" in path:
            return httpx.Response(404)
        if "bad" in path:
            return httpx.Response(500)
        if "oops" in path:
            return httpx.Response(200, content=b"not-json")
        if "empty" in path:
            return httpx.Response(
                200,
                json={"message": {"author": ["x"], "issued": {"date-parts": [["nope"]]}}},
            )
        return httpx.Response(
            200,
            json={
                "message": {
                    "published-print": {"date-parts": [[2019, 6]]},
                    "author": [{"family": "Smith"}, {"given": "Ada"}],
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        year, names, missing = _crossref_work(client, cfg, "10.1000/ok")
        assert year == 2019
        assert "smith" in names
        assert missing is False
        year, names, missing = _crossref_work(client, cfg, "10.1000/gone")
        assert missing is True
        year, names, missing = _crossref_work(client, cfg, "10.1000/bad")
        assert year is None and missing is False
        year, names, missing = _crossref_work(client, cfg, "10.1000/oops")
        assert year is None
        year, names, missing = _crossref_work(client, cfg, "10.1000/empty")
        assert year is None
    finally:
        client.close()

    boom = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: (_ for _ in ()).throw(httpx.ConnectError("down", request=req))
        )
    )
    try:
        year, names, missing = _crossref_work(boom, cfg, "10.1000/x")
        assert year is None and missing is False
    finally:
        boom.close()
