"""``paperful.urls`` probe helpers without network."""

from __future__ import annotations

import httpx

from paperful.urls import UrlTarget, probe_target, targets_for_item
from tests.conftest import make_item


def test_targets_for_item_parent_and_linked_pdf():
    item = make_item(url="https://example.org/parent")
    children = [
        {
            "key": "ATT1",
            "data": {
                "itemType": "attachment",
                "linkMode": "linked_url",
                "url": "https://example.org/file.pdf",
                "contentType": "application/pdf",
            },
        }
    ]
    targets = targets_for_item(item, children)
    roles = {t.role for t in targets}
    assert "parent" in roles
    assert "linked_pdf" in roles


def test_probe_target_head_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-type": "application/pdf"})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    finding = probe_target(
        client, UrlTarget("K1", "https://example.org/a.pdf", "parent")
    )
    assert finding.code == "ok"
    client.close()


def test_probe_target_redirect_with_get_body():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                request=httpx.Request("HEAD", "https://example.org/old"),
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html>ok page with enough content to avoid soft 404</html>",
            request=httpx.Request("GET", "https://example.org/new"),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    finding = probe_target(
        client, UrlTarget("K1", "https://example.org/old", "parent")
    )
    assert finding.code in {"ok", "redirect", "soft_404"}
    client.close()
