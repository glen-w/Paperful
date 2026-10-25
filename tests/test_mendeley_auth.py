"""Mendeley OAuth + HTTP edge cases against a mocked api.mendeley.com (no live network).

Adapter-field checklist: docs/templates/adapter-field-assessment.md (M2, M3, M4).
"""

from __future__ import annotations

import json
import os
import socket
import stat
import threading
import time
import urllib.request

import httpx
import pytest

from paperful import mendeley
from paperful.library import LibraryError
from paperful.mendeley import MendeleyAuthError, MendeleyClient, _next_link, _retry_after
from tests.conftest import mock_client

TOKEN_FILE = "mendeley-oauth.json"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("PAPERFUL_MENDELEY_CLIENT_ID", "PAPERFUL_MENDELEY_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def sleeps(monkeypatch):
    calls: list[float] = []
    monkeypatch.setattr(mendeley.time, "sleep", lambda s: calls.append(s))
    return calls


def _write_tokens(cfg, **tokens):
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    (cfg.state_dir / TOKEN_FILE).write_text(json.dumps(tokens), encoding="utf-8")


def _stored(cfg):
    return json.loads((cfg.state_dir / TOKEN_FILE).read_text(encoding="utf-8"))


def _token_reply(access="new-access", refresh="new-refresh", expires_in=3600):
    body = {"access_token": access, "expires_in": expires_in}
    if refresh is not None:
        body["refresh_token"] = refresh
    return httpx.Response(200, json=body)


class Api:
    """Counts calls; 401s any bearer that is not ``valid``."""

    def __init__(self, valid="new-access", refresh_reply=None):
        self.valid = valid
        self.refresh_reply = refresh_reply or _token_reply()
        self.calls: list[tuple[str, str, str]] = []
        self.token_posts: list[dict[str, str]] = []
        self.statuses: list[int] = []  # scripted overrides for the next non-token calls

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        auth = request.headers.get("authorization", "")
        if path == "/oauth/token":
            self.token_posts.append(dict(httpx.QueryParams(request.content.decode())))
            return self.refresh_reply
        self.calls.append((request.method, path, auth))
        if self.statuses:
            status = self.statuses.pop(0)
            if status == 429:
                return httpx.Response(429, headers={"Retry-After": "2"}, text="slow")
            if status != 200:
                return httpx.Response(status, text=f"scripted {status}")
        if auth != f"Bearer {self.valid}":
            return httpx.Response(401, text="expired")
        if path == "/profiles/me":
            return httpx.Response(200, json={"id": "p1", "display_name": "Ada"})
        if path == "/files" and request.method == "POST":
            return httpx.Response(201, json={"id": "F1"})
        if path.startswith("/files/"):
            return httpx.Response(200, content=b"%PDF-direct")
        if path == "/things":
            return httpx.Response(200, json=[{"n": 1}])
        return httpx.Response(404, text="unhandled")


def _client(cfg, api, **tokens) -> MendeleyClient:
    _write_tokens(
        cfg,
        **(tokens or {"access_token": "old", "refresh_token": "old-refresh", "expires_at": time.time() + 3600}),
    )
    return MendeleyClient(cfg, http=mock_client(api))


# --- ensure_token / refresh ------------------------------------------------------


def test_fresh_token_is_used_without_any_http(cfg):
    api = Api()
    client = _client(cfg, api, access_token="cached", expires_at=time.time() + 600)
    assert client.ensure_token() == "cached"
    assert api.token_posts == [] and api.calls == []


def test_token_near_expiry_is_refreshed_and_rotated(cfg):
    api = Api()
    client = _client(cfg, api, access_token="old", refresh_token="r1", expires_at=time.time() + 30)
    assert client.ensure_token() == "new-access"
    assert api.token_posts[0]["grant_type"] == "refresh_token"
    assert api.token_posts[0]["refresh_token"] == "r1"
    assert api.token_posts[0]["redirect_uri"] == cfg.mendeley_redirect_uri
    stored = _stored(cfg)
    assert stored["refresh_token"] == "new-refresh" and stored["expires_at"] > time.time() + 3000


def test_refresh_keeps_old_refresh_token_when_server_omits_it(cfg):
    api = Api(refresh_reply=_token_reply(refresh=None))
    client = _client(cfg, api, access_token="old", refresh_token="keep-me", expires_at=0)
    client.ensure_token()
    assert _stored(cfg)["refresh_token"] == "keep-me"


@pytest.mark.parametrize("content", [None, "not json", "[1, 2]"])
def test_missing_or_corrupt_token_file_gives_setup_instructions(cfg, content):
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    if content is not None:
        (cfg.state_dir / TOKEN_FILE).write_text(content, encoding="utf-8")
    client = MendeleyClient(cfg, http=mock_client(Api()))
    with pytest.raises(MendeleyAuthError) as exc:
        client.ensure_token()
    text = str(exc.value)
    assert "not authorised" in text and "session login mendeley" in text
    assert cfg.mendeley_redirect_uri in text


def test_refresh_rejected_by_server_is_an_auth_error(cfg):
    api = Api(refresh_reply=httpx.Response(400, text="invalid_grant"))
    client = _client(cfg, api, access_token="old", refresh_token="revoked", expires_at=0)
    with pytest.raises(MendeleyAuthError, match="token exchange 400"):
        client.ensure_token()
    assert _stored(cfg)["refresh_token"] == "revoked"  # a failed refresh never clobbers the stored token


def test_exchange_sends_basic_auth_from_config_and_env(cfg, monkeypatch):
    seen: dict = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return _token_reply()

    cfg.mendeley_client_id, cfg.mendeley_client_secret = "cfg-id", "cfg-secret"
    client = MendeleyClient(cfg, http=mock_client(handler))
    client._exchange({"grant_type": "refresh_token", "refresh_token": "r"})
    assert seen["auth"] == "Basic " + __import__("base64").b64encode(b"cfg-id:cfg-secret").decode()
    monkeypatch.setenv("PAPERFUL_MENDELEY_CLIENT_ID", "env-id")
    monkeypatch.setenv("PAPERFUL_MENDELEY_CLIENT_SECRET", "env-secret")
    client._exchange({"grant_type": "refresh_token", "refresh_token": "r"})
    assert seen["auth"] == "Basic " + __import__("base64").b64encode(b"env-id:env-secret").decode()


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_stored_tokens_are_mode_0600(cfg):
    api = Api()
    client = _client(cfg, api, access_token="old", refresh_token="r", expires_at=0)
    (cfg.state_dir / TOKEN_FILE).chmod(0o644)
    client.ensure_token()
    mode = stat.S_IMODE((cfg.state_dir / TOKEN_FILE).stat().st_mode)
    assert mode == 0o600


# --- 401 → refresh → retry ---------------------------------------------------------


def test_get_refreshes_once_on_401_then_retries(cfg):
    api = Api()
    client = _client(cfg, api)
    assert client.get("/things", accept="application/json") == [{"n": 1}]
    assert [c[2] for c in api.calls] == ["Bearer old", "Bearer new-access"]
    assert len(api.token_posts) == 1


def test_persistent_401_after_refresh_raises_library_error(cfg):
    api = Api(valid="never-matches")
    client = _client(cfg, api)
    with pytest.raises(LibraryError, match="→ 401"):
        client.get("/things", accept="application/json")
    assert len(api.calls) == 2 and len(api.token_posts) == 1


def test_download_refreshes_on_401_and_follows_redirect_without_bearer(cfg, tmp_path):
    seen: dict[str, str | None] = {}

    def handler(request):
        if request.url.host == "api.mendeley.com" and request.url.path == "/oauth/token":
            return _token_reply()
        if request.url.host == "api.mendeley.com":
            if request.headers.get("authorization") != "Bearer new-access":
                return httpx.Response(401, text="expired")
            return httpx.Response(303, headers={"Location": "https://bucket.s3.test/f.pdf"})
        seen["bucket_auth"] = request.headers.get("authorization")
        return httpx.Response(200, content=b"%PDF-bucket")

    _write_tokens(cfg, access_token="old", refresh_token="r", expires_at=time.time() + 3600)
    client = MendeleyClient(cfg, http=mock_client(handler))
    dest = client.download_file("FID", tmp_path / "deep" / "dir" / "f.pdf")
    assert dest.read_bytes() == b"%PDF-bucket"
    assert seen["bucket_auth"] is None


def test_download_redirect_without_location_and_http_errors(cfg, tmp_path, sleeps):
    def handler(request):
        if request.url.path == "/files/NOLOC":
            return httpx.Response(302)
        if request.url.path == "/files/BAD":
            return httpx.Response(500, text="kaput")
        if request.url.path == "/files/S3FAIL":
            return httpx.Response(303, headers={"Location": "https://bucket.s3.test/x"})
        if request.url.host == "bucket.s3.test":
            return httpx.Response(403, text="forbidden by bucket")
        if request.url.path == "/files/DIRECT":
            return httpx.Response(200, content=b"%PDF-direct")
        return httpx.Response(404)

    _write_tokens(cfg, access_token="t", expires_at=time.time() + 3600)
    client = MendeleyClient(cfg, http=mock_client(handler))
    with pytest.raises(LibraryError, match="without Location"):
        client.download_file("NOLOC", tmp_path / "a.pdf")
    with pytest.raises(LibraryError, match="→ 500"):
        client.download_file("BAD", tmp_path / "b.pdf")
    with pytest.raises(LibraryError, match="download 403"):
        client.download_file("S3FAIL", tmp_path / "c.pdf")
    assert client.download_file("DIRECT", tmp_path / "d.pdf").read_bytes() == b"%PDF-direct"
    assert not (tmp_path / "a.pdf").exists() and not (tmp_path / "c.pdf").exists()


def test_upload_refreshes_on_401_and_sends_document_link(cfg, tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 body")
    seen: list[httpx.Request] = []

    def handler(request):
        if request.url.path == "/oauth/token":
            return _token_reply()
        seen.append(request)
        if request.headers.get("authorization") != "Bearer new-access":
            return httpx.Response(401, text="expired")
        return httpx.Response(201, json={"id": "F9"})

    _write_tokens(cfg, access_token="old", refresh_token="r", expires_at=time.time() + 3600)
    client = MendeleyClient(cfg, http=mock_client(handler))
    assert client.upload_file("DOC1", pdf) == {"id": "F9"}
    assert len(seen) == 2
    assert 'rel="document"' in seen[-1].headers["link"] and "/documents/DOC1" in seen[-1].headers["link"]
    assert seen[-1].headers["content-disposition"] == 'attachment; filename="paper.pdf"'


@pytest.mark.parametrize(
    ("status", "text", "expect"),
    [(400, "File ALREADY exists", {"id": None, "duplicate": True}), (500, "boom", None), (400, "bad pdf", None)],
)
def test_upload_duplicate_vs_failure(cfg, tmp_path, status, text, expect):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"x")
    _write_tokens(cfg, access_token="t", expires_at=time.time() + 3600)
    client = MendeleyClient(cfg, http=mock_client(lambda r: httpx.Response(status, text=text)))
    if expect is None:
        with pytest.raises(LibraryError, match=f"upload {status}"):
            client.upload_file("D", pdf)
    else:
        assert client.upload_file("D", pdf) == expect


def test_upload_empty_success_body_returns_null_id(cfg, tmp_path):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"x")
    _write_tokens(cfg, access_token="t", expires_at=time.time() + 3600)
    client = MendeleyClient(cfg, http=mock_client(lambda r: httpx.Response(200)))
    assert client.upload_file("D", pdf) == {"id": None}


# --- 429 / Retry-After ---------------------------------------------------------------


def test_rate_limit_waits_then_retries_in_get_download_and_upload(cfg, tmp_path, sleeps):
    api = Api(valid="t")
    client = _client(cfg, api, access_token="t", expires_at=time.time() + 3600)
    api.statuses = [429]
    assert client.get("/things", accept="application/json") == [{"n": 1}]
    api.statuses = [429]
    assert client.download_file("X", tmp_path / "x.pdf").read_bytes() == b"%PDF-direct"
    api.statuses = [429]
    pdf = tmp_path / "u.pdf"
    pdf.write_bytes(b"x")
    assert client.upload_file("D", pdf) == {"id": "F1"}
    assert sleeps == [2.0, 2.0, 2.0]


@pytest.mark.parametrize(
    ("header", "expected"),
    [("0", 1.0), ("2", 2.0), ("999", 60.0), ("abc", 5.0), (None, 5.0), ("-4", 1.0)],
)
def test_retry_after_is_clamped(header, expected):
    resp = httpx.Response(429, headers={"Retry-After": header} if header is not None else {})
    assert _retry_after(resp) == expected


# --- pagination / request shapes --------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("", None),
        ('<https://api.mendeley.com/x?page=2>; rel="next"', "https://api.mendeley.com/x?page=2"),
        ('<https://a/prev>; rel="prev", <https://a/next>; rel="next"', "https://a/next"),
        ('<https://a/last>; rel="last"', None),
        ('<https://a/next> ; REL="next"', "https://a/next"),
        ("garbage", None),
    ],
)
def test_next_link_parsing(header, expected):
    assert _next_link(header) == expected


def test_paginate_sends_params_only_on_first_page_and_accepts_dicts(cfg):
    seen: list[tuple[str, dict]] = []

    def handler(request):
        seen.append((str(request.url), dict(request.url.params)))
        if request.url.path == "/things" and "page" not in request.url.params:
            return httpx.Response(
                200,
                json=[{"n": 1}],
                headers={"Link": '<https://api.mendeley.com/things?page=2>; rel="next"'},
            )
        return httpx.Response(200, json={"n": 2})

    _write_tokens(cfg, access_token="t", expires_at=time.time() + 3600)
    client = MendeleyClient(cfg, http=mock_client(handler))
    assert client.paginate("/things", accept="x", params={"view": "all"}) == [{"n": 1}, {"n": 2}]
    assert seen[0][1] == {"view": "all", "limit": "500"}
    assert seen[1][1] == {"page": "2"}


def test_request_handles_204_and_plain_text(cfg):
    replies = iter([httpx.Response(204), httpx.Response(200, text="plain words")])
    _write_tokens(cfg, access_token="t", expires_at=time.time() + 3600)
    client = MendeleyClient(cfg, http=mock_client(lambda r: next(replies)))
    assert client.delete("/documents/1") is None
    assert client._request("GET", "/x", accept="*/*") == "plain words"


def test_ping_requires_a_profile_object(cfg):
    _write_tokens(cfg, access_token="t", expires_at=time.time() + 3600)
    client = MendeleyClient(cfg, http=mock_client(lambda r: httpx.Response(200, json=["nope"])))
    with pytest.raises(MendeleyAuthError, match="did not return a profile"):
        client.ping()
    ok = MendeleyClient(
        cfg, http=mock_client(lambda r: httpx.Response(200, json={"id": "p", "email": "a@b.test"}))
    ).ping()
    assert ok == {"display_name": "a@b.test", "profile_id": "p", "supports_write": True}


def test_close_only_closes_owned_clients(cfg):
    borrowed = mock_client(lambda r: httpx.Response(200))
    MendeleyClient(cfg, http=borrowed).close()
    assert not borrowed.is_closed
    owned = MendeleyClient(cfg)
    owned.close()
    assert owned.http.is_closed


# --- login() over a loopback redirect -------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _login_env(cfg, monkeypatch, *, callback_query):
    """Return (client, opened_urls). The fake browser hits the redirect URI itself."""
    port = _free_port()
    cfg.mendeley_redirect_uri = f"http://127.0.0.1:{port}/callback"
    cfg.mendeley_client_id, cfg.mendeley_client_secret = "cid", "secret"
    opened: list[str] = []
    statuses: list[int] = []

    def fake_open(url):
        opened.append(url)
        state = httpx.URL(url).params["state"]
        query = callback_query(state)

        def hit():
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{query}", timeout=5) as r:
                    statuses.append(r.status)
            except urllib.error.HTTPError as exc:
                statuses.append(exc.code)

        threading.Thread(target=hit, daemon=True).start()
        return True

    monkeypatch.setattr(mendeley.webbrowser, "open", fake_open)
    api = Api()
    client = MendeleyClient(cfg, http=mock_client(api))
    return client, opened, api, statuses


def test_login_exchanges_code_and_stores_tokens(cfg, monkeypatch):
    client, opened, api, statuses = _login_env(
        cfg, monkeypatch, callback_query=lambda state: f"/callback?code=THECODE&state={state}"
    )
    tokens = client.login()
    assert tokens["access_token"] == "new-access"
    assert api.token_posts[0]["grant_type"] == "authorization_code"
    assert api.token_posts[0]["code"] == "THECODE"
    assert api.token_posts[0]["redirect_uri"] == cfg.mendeley_redirect_uri
    assert _stored(cfg)["refresh_token"] == "new-refresh"
    url = httpx.URL(opened[0])
    assert url.host == "api.mendeley.com" and url.params["response_type"] == "code"
    assert url.params["client_id"] == "cid" and url.params["scope"] == "all"
    assert url.params["redirect_uri"] == cfg.mendeley_redirect_uri


def test_login_rejects_state_mismatch(cfg, monkeypatch):
    client, _opened, api, _statuses = _login_env(
        cfg, monkeypatch, callback_query=lambda state: "/callback?code=EVIL&state=forged"
    )
    with pytest.raises(MendeleyAuthError, match="did not return an authorization code"):
        client.login()
    assert api.token_posts == []  # a forged callback never reaches the token endpoint
    assert not (cfg.state_dir / TOKEN_FILE).exists()


def test_login_surfaces_provider_error(cfg, monkeypatch):
    client, _o, api, _s = _login_env(
        cfg,
        monkeypatch,
        callback_query=lambda state: f"/callback?error=access_denied&error_description=User+said+no&state={state}",
    )
    with pytest.raises(MendeleyAuthError, match="User said no"):
        client.login()
    assert api.token_posts == []


def test_login_ignores_callback_on_other_paths(cfg, monkeypatch):
    client, _o, api, statuses = _login_env(
        cfg, monkeypatch, callback_query=lambda state: f"/elsewhere?code=X&state={state}"
    )
    with pytest.raises(MendeleyAuthError, match="did not return an authorization code"):
        client.login()
    assert api.token_posts == []


def test_login_requires_client_credentials(cfg):
    client = MendeleyClient(cfg, http=mock_client(Api()))
    with pytest.raises(MendeleyAuthError, match="client_id and client_secret"):
        client.login(open_browser=False)
