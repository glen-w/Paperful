"""Source adapters against httpx.MockTransport - no network."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from paperful.sources import (
    REGISTRY,
    arxiv,
    biorxiv,
    core,
    direct,
    europepmc,
    openalex,
    scihub,
    semanticscholar,
    unpaywall,
)
from paperful.sources import base as base_mod
from paperful.sources.base import Outcome, http_json
from tests.conftest import PDF_BYTES, make_item

FIX = Path(__file__).parent / "fixtures"


def _json(payload, status=200):
    return httpx.Response(
        status,
        content=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )


def test_registry_has_every_planned_source_and_scihub_is_opt_in():
    from paperful.config import DEFAULT_SOURCES

    assert set(REGISTRY) == {
        "unpaywall",
        "openalex",
        "arxiv",
        "biorxiv",
        "europepmc",
        "semanticscholar",
        "core",
        "scholar",
        "direct",
        "ezproxy",
        "htmlpdf",
        "scihub",
    }
    assert "scihub" not in DEFAULT_SOURCES
    assert DEFAULT_SOURCES[-1] == "htmlpdf"
    assert DEFAULT_SOURCES.index("core") == DEFAULT_SOURCES.index("semanticscholar") + 1
    assert DEFAULT_SOURCES.index("ezproxy") < DEFAULT_SOURCES.index("htmlpdf")
    assert DEFAULT_SOURCES.index("biorxiv") < DEFAULT_SOURCES.index("semanticscholar")
    assert DEFAULT_SOURCES.index("europepmc") < DEFAULT_SOURCES.index("semanticscholar")
    assert all(s in REGISTRY for s in DEFAULT_SOURCES)
    assert "scihub" in REGISTRY


# ---- unpaywall ---------------------------------------------------------------


def test_unpaywall_returns_best_then_alternates(ctx_factory):
    def handler(req):
        assert (
            req.url.host == "api.unpaywall.org"
            and req.url.params["email"] == "test@example.org"
        )
        return _json(
            {
                "best_oa_location": {
                    "url_for_pdf": "https://pub.test/best.pdf",
                    "url_for_landing_page": "https://pub.test/land",
                },
                "oa_locations": [
                    {"url_for_pdf": "https://pub.test/best.pdf"},
                    {"url_for_pdf": None},
                    {"url_for_pdf": "https://repo.test/copy.pdf"},
                ],
            }
        )

    cand = unpaywall.find(make_item(), ctx_factory(handler))
    assert cand.outcome is Outcome.FOUND
    assert cand.urls == ["https://pub.test/best.pdf", "https://repo.test/copy.pdf"]
    assert cand.referer == "https://pub.test/land"


def test_unpaywall_skips_without_doi_or_email(ctx_factory, cfg):
    assert (
        unpaywall.find(make_item(doi=None), ctx_factory(lambda r: _json({}))).outcome
        is Outcome.SKIPPED
    )
    cfg.email = ""
    assert (
        unpaywall.find(make_item(), ctx_factory(lambda r: _json({}))).outcome
        is Outcome.SKIPPED
    )


def test_unpaywall_404_and_no_pdf_are_not_found(ctx_factory):
    assert (
        unpaywall.find(make_item(), ctx_factory(lambda r: httpx.Response(404))).outcome
        is Outcome.NOT_FOUND
    )
    miss = unpaywall.find(
        make_item(), ctx_factory(lambda r: _json({"oa_locations": []}))
    )
    assert miss.outcome is Outcome.NOT_FOUND and miss.note == "no OA location"


def test_unpaywall_follows_html_landing(ctx_factory):
    def handler(req):
        if req.url.host == "api.unpaywall.org":
            return _json(
                {
                    "best_oa_location": {
                        "url_for_pdf": None,
                        "url": "https://repo.test/art",
                        "url_for_landing_page": "https://repo.test/art",
                    }
                }
            )
        html = '<html><head><meta name="citation_pdf_url" content="https://repo.test/art.pdf"></head></html>'
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    cand = unpaywall.find(make_item(), ctx_factory(handler))
    assert cand.outcome is Outcome.FOUND
    assert cand.url == "https://repo.test/art.pdf"
    assert cand.note == "landing"


def test_unpaywall_uses_url_that_looks_like_pdf(ctx_factory):
    cand = unpaywall.find(
        make_item(),
        ctx_factory(
            lambda r: _json(
                {
                    "oa_locations": [
                        {"url_for_pdf": None, "url": "https://repo.test/copy.pdf"}
                    ]
                }
            )
        ),
    )
    assert cand.urls == ["https://repo.test/copy.pdf"]


# ---- openalex ----------------------------------------------------------------


def test_openalex_uses_doi_url_and_collects_pdf_urls(ctx_factory):
    def handler(req):
        assert "works/https://doi.org/10.1000/test.doi" in str(req.url)
        return _json(
            {
                "best_oa_location": {
                    "pdf_url": "https://a.test/1.pdf",
                    "landing_page_url": "https://a.test/",
                },
                "locations": [{"pdf_url": None}, {"pdf_url": "https://b.test/2.pdf"}],
            }
        )

    cand = openalex.find(make_item(), ctx_factory(handler))
    assert cand.urls == ["https://a.test/1.pdf", "https://b.test/2.pdf"]


# ---- semantic scholar --------------------------------------------------------


def test_semanticscholar_prefers_doi_then_arxiv(ctx_factory):
    seen = []

    def handler(req):
        seen.append(req.url.path)
        return _json(
            {"openAccessPdf": {"url": "https://s2.test/p.pdf", "status": "GREEN"}}
        )

    ctx = ctx_factory(handler)
    assert semanticscholar.find(make_item(), ctx).url == "https://s2.test/p.pdf"
    assert (
        semanticscholar.find(make_item(doi=None, arxiv_id="2101.00001"), ctx).outcome
        is Outcome.FOUND
    )
    assert seen == [
        "/graph/v1/paper/DOI:10.1000/test.doi",
        "/graph/v1/paper/ARXIV:2101.00001",
    ]
    assert semanticscholar.find(make_item(doi=None), ctx).outcome is Outcome.SKIPPED


def test_semanticscholar_no_pdf(ctx_factory):
    assert (
        semanticscholar.find(
            make_item(), ctx_factory(lambda r: _json({"openAccessPdf": None}))
        ).outcome
        is Outcome.NOT_FOUND
    )


def test_semanticscholar_resolves_handle_landing(ctx_factory):
    title = make_item().title
    pdf = "https://dspace.test/server/api/core/bitstreams/x/content"

    def handler(req):
        if "semanticscholar.org" in req.url.host:
            return _json(
                {
                    "openAccessPdf": {
                        "url": "https://dspace.test/handle/1874/1",
                        "status": "GREEN",
                    }
                }
            )
        if req.url.path.endswith("/pid/find"):
            return _json(
                {
                    "name": title,
                    "_links": {
                        "bundles": {
                            "href": "https://dspace.test/server/api/core/items/i1/bundles"
                        }
                    },
                }
            )
        if req.url.path.endswith("/bundles"):
            return _json(
                {
                    "_embedded": {
                        "bundles": [
                            {
                                "name": "ORIGINAL",
                                "_links": {
                                    "bitstreams": {
                                        "href": "https://dspace.test/b/bitstreams"
                                    }
                                },
                            }
                        ]
                    }
                }
            )
        if req.url.path.endswith("/bitstreams"):
            return _json(
                {
                    "_embedded": {
                        "bitstreams": [
                            {"name": "p.pdf", "_links": {"content": {"href": pdf}}}
                        ]
                    }
                }
            )
        return httpx.Response(404)

    cand = semanticscholar.find(make_item(), ctx_factory(handler))
    assert cand.url == pdf
    assert cand.referer == "https://dspace.test/handle/1874/1"


# ---- arxiv -------------------------------------------------------------------


def test_arxiv_direct_by_id_or_datacite_doi(ctx_factory):
    ctx = ctx_factory(lambda r: httpx.Response(500))  # must not be called
    assert (
        arxiv.find(make_item(arxiv_id="2101.00001"), ctx).url
        == "https://arxiv.org/pdf/2101.00001"
    )
    assert (
        arxiv.find(make_item(doi="10.48550/arxiv.2101.00002"), ctx).url
        == "https://arxiv.org/pdf/2101.00002"
    )
    assert arxiv.find(make_item(item_type="webpage"), ctx).outcome is Outcome.SKIPPED


def test_arxiv_title_search_requires_close_match(ctx_factory):
    feed = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
      <entry><id>http://arxiv.org/abs/1706.03762v5</id><title>Attention Is All You Need</title></entry>
      <entry><id>http://arxiv.org/abs/2101.00001v1</id><title>A sufficiently long test title about marine governance</title></entry>
    </feed>"""
    ctx = ctx_factory(lambda r: httpx.Response(200, content=feed.encode()))
    cand = arxiv.find(make_item(doi=None), ctx)
    assert cand.url == "https://arxiv.org/pdf/2101.00001"
    ctx2 = ctx_factory(lambda r: httpx.Response(200, content=feed.encode()))
    assert (
        arxiv.find(
            make_item(doi=None, title="Something else entirely, unrelated words here"),
            ctx2,
        ).outcome
        is Outcome.NOT_FOUND
    )


# ---- biorxiv / medrxiv -------------------------------------------------------


def test_biorxiv_builds_pdf_from_latest_version(ctx_factory):
    seen = []

    def handler(req):
        seen.append(req.url.path)
        if "details/biorxiv/" in req.url.path:
            return _json(
                {
                    "collection": [
                        {"doi": "10.1101/2020.01.10.901900", "version": "1"},
                        {"doi": "10.1101/2020.01.10.901900", "version": "2"},
                    ]
                }
            )
        return _json({"collection": []})

    cand = biorxiv.find(
        make_item(doi="10.1101/2020.01.10.901900"), ctx_factory(handler)
    )
    assert cand.outcome is Outcome.FOUND
    assert (
        cand.url
        == "https://www.biorxiv.org/content/10.1101/2020.01.10.901900v2.full.pdf"
    )
    assert cand.alternates == [
        "https://www.biorxiv.org/content/10.1101/2020.01.10.901900.full.pdf"
    ]
    assert cand.note == "biorxiv v2"
    assert seen == ["/details/biorxiv/10.1101/2020.01.10.901900"]


def test_biorxiv_falls_back_to_medrxiv_and_url_doi(ctx_factory):
    def handler(req):
        if "details/biorxiv/" in req.url.path:
            return _json({"collection": []})
        return _json(
            {"collection": [{"doi": "10.1101/2020.03.09.20033217", "version": "1"}]}
        )

    cand = biorxiv.find(
        make_item(doi="10.1101/2020.03.09.20033217"), ctx_factory(handler)
    )
    assert (
        cand.url.startswith("https://www.medrxiv.org/content/")
        and cand.note == "medrxiv v1"
    )

    cand2 = biorxiv.find(
        make_item(
            doi=None, url="https://www.biorxiv.org/content/10.1101/2020.01.10.901900v1"
        ),
        ctx_factory(
            lambda r: _json(
                {"collection": [{"doi": "10.1101/2020.01.10.901900", "version": "1"}]}
            )
        ),
    )
    assert cand2.outcome is Outcome.FOUND


def test_biorxiv_skips_non_cshl_dois(ctx_factory):
    ctx = ctx_factory(lambda r: httpx.Response(500))
    assert biorxiv.find(make_item(), ctx).outcome is Outcome.SKIPPED
    assert biorxiv.find(make_item(doi=None, url=None), ctx).outcome is Outcome.SKIPPED


# ---- europepmc ---------------------------------------------------------------


def test_europepmc_prefers_europe_pmc_oa_pdf(ctx_factory):
    def handler(req):
        assert req.url.params["query"] == "DOI:10.1000/test.doi"
        assert req.url.params["resultType"] == "core"
        return _json(
            {
                "resultList": {
                    "result": [
                        {
                            "pmcid": "PMC1817752",
                            "fullTextUrlList": {
                                "fullTextUrl": [
                                    {
                                        "availabilityCode": "OA",
                                        "documentStyle": "pdf",
                                        "site": "Unpaywall",
                                        "url": "https://pub.test/copy.pdf",
                                    },
                                    {
                                        "availabilityCode": "OA",
                                        "documentStyle": "html",
                                        "site": "Europe_PMC",
                                        "url": "https://europepmc.org/articles/PMC1817752",
                                    },
                                    {
                                        "availabilityCode": "OA",
                                        "documentStyle": "pdf",
                                        "site": "Europe_PMC",
                                        "url": "https://europepmc.org/articles/PMC1817752?pdf=render",
                                    },
                                    {
                                        "availabilityCode": "S",
                                        "documentStyle": "pdf",
                                        "site": "Publisher",
                                        "url": "https://paywall.test/x.pdf",
                                    },
                                ]
                            },
                        }
                    ]
                }
            }
        )

    cand = europepmc.find(make_item(), ctx_factory(handler))
    assert cand.urls == [
        "https://europepmc.org/articles/PMC1817752?pdf=render",
        "https://pub.test/copy.pdf",
    ]
    assert cand.note == "PMC1817752"


def test_europepmc_skips_without_doi_and_misses_empty(ctx_factory):
    assert (
        europepmc.find(make_item(doi=None), ctx_factory(lambda r: _json({}))).outcome
        is Outcome.SKIPPED
    )
    assert (
        europepmc.find(
            make_item(), ctx_factory(lambda r: _json({"resultList": {"result": []}}))
        ).outcome
        is Outcome.NOT_FOUND
    )
    assert (
        europepmc.find(
            make_item(),
            ctx_factory(
                lambda r: _json(
                    {
                        "resultList": {
                            "result": [{"fullTextUrlList": {"fullTextUrl": []}}]
                        }
                    }
                )
            ),
        ).outcome
        is Outcome.NOT_FOUND
    )


# ---- direct ------------------------------------------------------------------


def test_direct_url_heuristics(ctx_factory):
    ctx = ctx_factory(
        lambda r: httpx.Response(
            200, content=b"<html>", headers={"content-type": "text/html"}
        )
    )
    assert direct.find(make_item(url=None), ctx).outcome is Outcome.SKIPPED
    assert (
        direct.find(make_item(url="https://doi.org/10.1/x"), ctx).outcome
        is Outcome.SKIPPED
    )
    assert (
        direct.find(make_item(url="https://www.youtube.com/watch?v=x"), ctx).outcome
        is Outcome.SKIPPED
    )
    assert (
        direct.find(make_item(url="https://youtu.be/x"), ctx).outcome is Outcome.SKIPPED
    )
    assert (
        direct.find(make_item(url="https://x.test/report.PDF?dl=1"), ctx).url
        == "https://x.test/report.PDF?dl=1"
    )
    assert (
        direct.find(make_item(url="https://x.test/page"), ctx).outcome
        is Outcome.NOT_FOUND
    )


def test_direct_follows_html_pdf_link(ctx_factory):
    html = '<html><head><meta name="citation_pdf_url" content="https://x.test/full.pdf"></head></html>'
    ctx = ctx_factory(
        lambda r: httpx.Response(200, text=html, headers={"content-type": "text/html"})
    )
    cand = direct.find(make_item(url="https://x.test/page"), ctx)
    assert cand.outcome is Outcome.FOUND
    assert cand.url == "https://x.test/full.pdf"
    assert cand.note == "html link"


def test_direct_accepts_pdf_content_type_and_octet_stream_magic(ctx_factory):
    ctx = ctx_factory(
        lambda r: httpx.Response(
            200, content=PDF_BYTES, headers={"content-type": "application/pdf"}
        )
    )
    assert direct.find(make_item(url="https://x.test/dl"), ctx).outcome is Outcome.FOUND
    ctx2 = ctx_factory(
        lambda r: httpx.Response(
            200, content=PDF_BYTES, headers={"content-type": "application/octet-stream"}
        )
    )
    assert (
        direct.find(make_item(url="https://x.test/dl"), ctx2).note == "octet-stream pdf"
    )


def test_direct_unreachable_is_error(ctx_factory):
    def handler(req):
        raise httpx.ConnectError("nope", request=req)

    assert (
        direct.find(make_item(url="https://x.test/dl"), ctx_factory(handler)).outcome
        is Outcome.ERROR
    )


# ---- http_json ---------------------------------------------------------------


def test_http_json_retries_once_on_429(ctx_factory, monkeypatch):
    slept = []
    monkeypatch.setattr(base_mod.time, "sleep", lambda s: slept.append(s))
    calls = []

    def handler(req):
        calls.append(1)
        return (
            httpx.Response(429, headers={"Retry-After": "3"})
            if len(calls) == 1
            else _json({"ok": 1})
        )

    assert http_json(ctx_factory(handler), "https://api.test/x") == {"ok": 1}
    assert slept == [3.0] and len(calls) == 2


# ---- scihub network layer ----------------------------------------------------


def _scihub_handler(pages: dict[str, httpx.Response | Exception]):
    def handler(req):
        resp = pages.get(req.url.host)
        if isinstance(resp, Exception):
            raise resp
        return resp or httpx.Response(500)

    return handler


def test_scihub_found_on_first_mirror(ctx_factory):
    html = (FIX / "scihub_found.html").read_text()
    cand = scihub.find(
        make_item(),
        ctx_factory(_scihub_handler({"m1.test": httpx.Response(200, text=html)})),
    )
    assert cand.outcome is Outcome.FOUND
    assert cand.url.startswith("https://m1.test/storage/") and cand.note == "m1.test"
    assert cand.referer == "https://m1.test/10.1000/test.doi"


def test_scihub_not_found_is_terminal_across_mirrors(ctx_factory):
    html = (FIX / "scihub_not_found.html").read_text()
    calls = []

    def handler(req):
        calls.append(req.url.host)
        return httpx.Response(200, text=html)

    cand = scihub.find(make_item(), ctx_factory(handler))
    assert cand.outcome is Outcome.NOT_FOUND and calls == ["m1.test"]


def test_scihub_fails_over_and_circuit_breaks(ctx_factory):
    html = (FIX / "scihub_found.html").read_text()
    ctx = ctx_factory(
        _scihub_handler(
            {
                "m1.test": httpx.ConnectError("down"),
                "m2.test": httpx.Response(200, text=html),
            }
        )
    )
    assert scihub.find(make_item(), ctx).outcome is Outcome.FOUND
    assert ctx.mirror_failures["m1.test"] == 1 and ctx.mirror_ok("m1.test")
    scihub.find(make_item(), ctx)
    assert ctx.mirror_failures["m1.test"] == 2 and not ctx.mirror_ok("m1.test")
    # now m1 is skipped without a request
    calls = []

    def handler(req):
        calls.append(req.url.host)
        return httpx.Response(200, text=html)

    ctx.client = httpx.Client(transport=httpx.MockTransport(handler))
    cand = scihub.find(make_item(), ctx)
    assert calls == ["m2.test"] and cand.outcome is Outcome.FOUND


def test_scihub_all_mirrors_down_is_error_with_per_mirror_notes(ctx_factory):
    ctx = ctx_factory(
        _scihub_handler(
            {"m1.test": httpx.Response(502), "m2.test": httpx.Response(403)}
        )
    )
    cand = scihub.find(make_item(), ctx)
    assert cand.outcome is Outcome.ERROR
    assert "m1.test=HTTP 502" in cand.note and "m2.test=HTTP 403" in cand.note


def test_scihub_solves_altcha_then_gets_article(ctx_factory):
    import hashlib

    captcha = (FIX / "scihub_captcha.html").read_text()
    article = (FIX / "scihub_found.html").read_text()
    state = {"solved": False}
    salt, number = "s?expires=1&", 77
    challenge = {
        "algorithm": "SHA-256",
        "salt": salt,
        "maxNumber": 500,
        "signature": "sig",
        "challenge": hashlib.sha256(f"{salt}{number}".encode()).hexdigest(),
    }

    def handler(req):
        if req.url.path.startswith("/captcha/challenge"):
            return _json(challenge)
        if req.url.path.startswith("/captcha/solution"):
            body = json.loads(req.content)
            assert "captcha" in body
            state["solved"] = True
            return _json({"success": True})
        return httpx.Response(200, text=article if state["solved"] else captcha)

    cand = scihub.find(make_item(), ctx_factory(handler))
    assert cand.outcome is Outcome.FOUND and state["solved"]


def test_scihub_unsolvable_captcha_reports_captcha(ctx_factory):
    captcha = (FIX / "scihub_captcha.html").read_text()

    def handler(req):
        if req.url.path.startswith("/captcha/challenge"):
            return httpx.Response(500)
        return httpx.Response(200, text=captcha)

    cand = scihub.find(make_item(), ctx_factory(handler))
    assert cand.outcome is Outcome.CAPTCHA


def test_scihub_direct_pdf_response_and_404(ctx_factory):
    ctx = ctx_factory(
        lambda r: httpx.Response(
            200, content=PDF_BYTES, headers={"content-type": "application/pdf"}
        )
    )
    assert scihub.fetch_from_mirror(ctx, "m1.test", "10.1/x").outcome is Outcome.FOUND
    ctx404 = ctx_factory(lambda r: httpx.Response(404))
    assert (
        scihub.fetch_from_mirror(ctx404, "m1.test", "10.1/x").outcome
        is Outcome.NOT_FOUND
    )


def test_ping_mirrors(ctx_factory):
    def handler(req):
        if req.url.host == "m1.test":
            return httpx.Response(200)
        raise httpx.ConnectError("down", request=req)

    assert scihub.ping_mirrors(ctx_factory(handler)) == [
        ("m1.test", "HTTP 200"),
        ("m2.test", "down (ConnectError)"),
    ]


def test_core_skipped_without_key(ctx_factory):
    ctx = ctx_factory(lambda r: httpx.Response(500))
    ctx.config.core_api_key = ""
    cand = core.find(make_item(), ctx)
    assert cand.outcome is Outcome.SKIPPED


def test_core_finds_download_url(ctx_factory, cfg):
    cfg.core_api_key = "test-key"

    def handler(req):
        assert "core.ac.uk" in (req.url.host or "")
        assert req.headers.get("authorization") == "Bearer test-key"
        return _json(
            {"results": [{"downloadUrl": "https://core.ac.uk/x.pdf", "links": []}]}
        )

    cand = core.find(make_item(), ctx_factory(handler))
    assert cand.outcome is Outcome.FOUND and cand.url.endswith("x.pdf")
