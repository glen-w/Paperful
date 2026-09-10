import httpx
import pytest

from paperful import download as dl
from paperful.download import DownloadError, fetch_pdf, looks_like_pdf
from tests.conftest import PDF_BYTES, mock_client


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(dl.time, "sleep", lambda *_: None)


def test_looks_like_pdf_allows_leading_junk():
    assert looks_like_pdf(b"%PDF-1.7 ...")
    assert looks_like_pdf(b"\n\n  %PDF-1.4")
    assert not looks_like_pdf(b"<html><body>Access denied</body></html>")


def test_fetch_pdf_happy_path():
    client = mock_client(
        lambda req: httpx.Response(
            200, content=PDF_BYTES, headers={"content-type": "application/pdf"}
        )
    )
    got = fetch_pdf(
        client, "https://x.test/a.pdf", referer="https://x.test/", min_bytes=1000
    )
    assert got.content == PDF_BYTES
    assert got.md5 and got.final_url == "https://x.test/a.pdf"


def test_fetch_pdf_sends_referer_and_accept():
    seen = {}

    def handler(req):
        seen.update(req.headers)
        return httpx.Response(200, content=PDF_BYTES)

    fetch_pdf(
        mock_client(handler),
        "https://x.test/a.pdf",
        referer="https://landing.test/",
        min_bytes=10,
    )
    assert seen["referer"] == "https://landing.test/"
    assert "application/pdf" in seen["accept"]


def test_fetch_pdf_rejects_html_landing_page():
    client = mock_client(
        lambda req: httpx.Response(
            200,
            content=b"<html>paywall</html>" * 500,
            headers={"content-type": "text/html"},
        )
    )
    with pytest.raises(DownloadError, match="not a PDF"):
        fetch_pdf(client, "https://x.test/a.pdf")


def test_fetch_pdf_rejects_too_small():
    client = mock_client(lambda req: httpx.Response(200, content=b"%PDF-1.4 tiny"))
    with pytest.raises(DownloadError, match="too small"):
        fetch_pdf(client, "https://x.test/a.pdf", min_bytes=1000)


def test_fetch_pdf_4xx_is_immediate_error():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(403)

    with pytest.raises(DownloadError, match="HTTP 403"):
        fetch_pdf(mock_client(handler), "https://x.test/a.pdf")
    assert len(calls) == 1


def test_fetch_pdf_retries_on_503_then_succeeds():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503, headers={"Retry-After": "1"})
        return httpx.Response(200, content=PDF_BYTES)

    got = fetch_pdf(
        mock_client(handler), "https://x.test/a.pdf", min_bytes=10, retries=3
    )
    assert got.content == PDF_BYTES and len(calls) == 3


def test_fetch_pdf_gives_up_after_retries_on_network_error():
    def handler(req):
        raise httpx.ConnectError("boom", request=req)

    with pytest.raises(DownloadError, match="ConnectError"):
        fetch_pdf(mock_client(handler), "https://x.test/a.pdf", retries=2)


def test_fetch_pdf_size_cap(monkeypatch):
    monkeypatch.setattr(dl, "MAX_PDF_BYTES", 5000)
    client = mock_client(lambda req: httpx.Response(200, content=PDF_BYTES))
    with pytest.raises(DownloadError, match="size cap"):
        fetch_pdf(client, "https://x.test/a.pdf", min_bytes=10)
