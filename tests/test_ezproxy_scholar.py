"""EZProxy + Google Scholar source unit tests (offline)."""

from __future__ import annotations

from pathlib import Path

import httpx

from scihub_dl.cookies import load_netscape_cookies
from scihub_dl.sources import ezproxy, scholar
from scihub_dl.sources.base import Outcome
from tests.conftest import PDF_BYTES, make_item, mock_client


def test_proxify_and_login_detection():
    base = "https://scpo.idm.oclc.org/login?url="
    assert ezproxy.proxify("https://doi.org/10.1/x", base).startswith(base)
    assert ezproxy.looks_like_login(
        httpx.Response(200, text="<html>Central Authentication Service</html>", request=httpx.Request("GET", "https://federation.sciences-po.fr/cas/login"))
    )
    assert not ezproxy.looks_like_login(
        httpx.Response(200, text="<html><meta name='citation_pdf_url' content='https://x/a.pdf'></html>", request=httpx.Request("GET", "https://www-sciencedirect-com.scpo.idm.oclc.org/science/article/pii/S1"))
    )


def test_extract_pdf_urls_sciencedirect():
    html = """
    <html><head><meta name="citation_pdf_url" content="/science/article/pii/S0964569126000761/pdfft"></head>
    <body><a href="/science/article/pii/S0964569126000761/pdfft?download=true">Download PDF</a></body></html>
    """
    base = "https://www-sciencedirect-com.scpo.idm.oclc.org/science/article/pii/S0964569126000761"
    urls = ezproxy.extract_pdf_urls(html, base)
    assert any("pdfft" in u for u in urls)
    assert any("S0964569126000761" in u for u in urls)


def test_ezproxy_skips_without_config(ctx_factory, cfg):
    cfg.ezproxy_base = ""
    assert ezproxy.find(make_item(), ctx_factory(lambda r: httpx.Response(200))).outcome is Outcome.SKIPPED


def test_ezproxy_finds_pdf_via_proxy(ctx_factory, cfg, tmp_path):
    cfg.ezproxy_base = "https://scpo.idm.oclc.org/login?url="
    cookie_file = tmp_path / "ezproxy-cookies.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".scpo.idm.oclc.org\tTRUE\t/\tTRUE\t0\tsession\tabc\n"
    )
    cfg.ezproxy_cookies = cookie_file
    html = '<html><head><meta name="citation_pdf_url" content="https://www-sciencedirect-com.scpo.idm.oclc.org/science/article/pii/S1/pdfft"></head></html>'

    def handler(req):
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    ctx = ctx_factory(handler)
    # inject cookies into client like make_client does
    for c in load_netscape_cookies(cookie_file).jar:
        ctx.client.cookies.set(c.name, c.value, domain=c.domain, path=c.path)
    cand = ezproxy.find(make_item(), ctx)
    assert cand.outcome is Outcome.FOUND
    assert "pdfft" in cand.url


def test_ezproxy_session_expired(ctx_factory, cfg, tmp_path):
    cfg.ezproxy_base = "https://scpo.idm.oclc.org/login?url="
    cookie_file = tmp_path / "c.txt"
    cookie_file.write_text(".scpo.idm.oclc.org\tTRUE\t/\tFALSE\t0\tx\ty\n")
    cfg.ezproxy_cookies = cookie_file

    def handler(req):
        return httpx.Response(
            200,
            text="Entrez votre identifiant et votre mot de passe.",
            request=httpx.Request("GET", "https://federation.sciences-po.fr/cas/login"),
        )

    ctx = ctx_factory(handler)
    for c in load_netscape_cookies(cookie_file).jar:
        ctx.client.cookies.set(c.name, c.value, domain=c.domain, path=c.path)
    cand = ezproxy.find(make_item(), ctx)
    assert cand.outcome is Outcome.ERROR and "session expired" in cand.note


def test_netscape_cookie_loader(tmp_path):
    p = tmp_path / "c.txt"
    p.write_text("#HttpOnly_.scpo.idm.oclc.org\tTRUE\t/\tTRUE\t0\tsid\tsecret\n")
    cookies = load_netscape_cookies(p)
    assert any(c.name == "sid" and c.value == "secret" for c in cookies.jar)


def test_scholar_extracts_pdf_sidebar():
    html = """
    <div class="gs_r"><div class="gs_or_ggsm"><a href="https://repository.example.edu/paper.pdf">[PDF]</a></div></div>
    <a href="https://scholar.google.com/scholar_url?url=https%3A%2F%2Fopen.example.org%2Fa.pdf&hl=en">[PDF]</a>
    """
    urls = scholar.extract_pdf_links(html, "https://scholar.google.com/scholar")
    assert "https://repository.example.edu/paper.pdf" in urls
    assert any("open.example.org" in u for u in urls)


def test_scholar_captcha_is_error(ctx_factory):
    def handler(req):
        return httpx.Response(200, text="<html>captcha</html>", request=httpx.Request("GET", "https://www.google.com/sorry/index"))

    assert scholar.find(make_item(), ctx_factory(handler)).outcome is Outcome.ERROR


def test_scholar_not_found(ctx_factory):
    def handler(req):
        return httpx.Response(200, text='<div class="gs_r">no pdfs here</div>')

    assert scholar.find(make_item(), ctx_factory(handler)).outcome is Outcome.NOT_FOUND
