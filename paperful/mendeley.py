"""Mendeley REST adapter (api.mendeley.com). No official SDK — it is unmaintained."""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .attach import AttachResult, attach_failure_code
from .config import Config
from .interop.types import mendeley_to_zotero, zotero_to_mendeley
from .library import LibraryError
from .resolve import extract_arxiv_id, extract_doi, extract_pmid, normalize_doi
from .zot import UNCOLLECTED, Collection, Item, build_collection_tree, parse_year

API = "https://api.mendeley.com"
AUTHORIZE = f"{API}/oauth/authorize"
TOKEN = f"{API}/oauth/token"
ACCEPT_DOC = "application/vnd.mendeley-document.1+json"
ACCEPT_FOLDER = "application/vnd.mendeley-folder.1+json"
ACCEPT_FILE = "application/vnd.mendeley-file.1+json"
ACCEPT_ANN = "application/vnd.mendeley-annotation.1+json"
_NOTE_MARK = "paperful-note:"
_SUMMARY_PREFIX = "paperful-summary"
_LINK_NEXT = re.compile(r'<([^>]+)>\s*;\s*rel="next"', re.I)


class MendeleyAuthError(LibraryError):
    pass


def token_path(cfg: Config) -> Path:
    return cfg.state_dir / "mendeley-oauth.json"


def client_id_of(cfg: Config) -> str:
    import os

    return (
        os.environ.get("PAPERFUL_MENDELEY_CLIENT_ID") or cfg.mendeley_client_id or ""
    ).strip()


def client_secret_of(cfg: Config) -> str:
    import os

    return (
        os.environ.get("PAPERFUL_MENDELEY_CLIENT_SECRET")
        or cfg.mendeley_client_secret
        or ""
    ).strip()


class MendeleyClient:
    """OAuth2 authorization-code client with rotating refresh tokens."""

    def __init__(self, cfg: Config, http: httpx.Client | None = None):
        self.cfg = cfg
        self.http = http or httpx.Client(timeout=60.0, follow_redirects=True)
        self._own_http = http is None
        self._tokens: dict[str, Any] | None = None
        self._lock = threading.Lock()

    def close(self) -> None:
        if self._own_http:
            self.http.close()

    def ping(self) -> dict[str, Any]:
        profile = self.get("/profiles/me", accept="application/vnd.mendeley-profile.1+json")
        if not isinstance(profile, dict):
            raise MendeleyAuthError("Mendeley /profiles/me did not return a profile")
        return {
            "display_name": profile.get("display_name") or profile.get("email") or "?",
            "profile_id": profile.get("id"),
            "supports_write": True,
        }

    def ensure_token(self) -> str:
        with self._lock:
            tokens = self._load()
            now = time.time()
            expires = float(tokens.get("expires_at") or 0)
            if tokens.get("access_token") and expires - 60 > now:
                return str(tokens["access_token"])
            if tokens.get("refresh_token"):
                tokens = self._refresh(tokens)
                return str(tokens["access_token"])
            raise MendeleyAuthError(
                "Mendeley is not authorised. Register an app at "
                "https://dev.mendeley.com/myapps.html (redirect "
                f"{self.cfg.mendeley_redirect_uri}), set [mendeley] client_id / "
                "client_secret (or PAPERFUL_MENDELEY_CLIENT_ID / "
                "PAPERFUL_MENDELEY_CLIENT_SECRET), then run "
                "`paperful session login mendeley`."
            )

    def login(self, *, open_browser: bool = True) -> dict[str, Any]:
        cid = client_id_of(self.cfg)
        secret = client_secret_of(self.cfg)
        if not cid or not secret:
            raise MendeleyAuthError(
                "Set [mendeley] client_id and client_secret (or the "
                "PAPERFUL_MENDELEY_CLIENT_* environment variables)."
            )
        redirect = self.cfg.mendeley_redirect_uri
        parsed = urlparse(redirect)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (80 if parsed.scheme == "http" else 443)
        path = parsed.path or "/"
        state = secrets.token_urlsafe(16)
        box: dict[str, str] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                q = parse_qs(urlparse(self.path).query)
                if urlparse(self.path).path.rstrip("/") != path.rstrip("/"):
                    self.send_error(404)
                    return
                if q.get("state", [""])[0] != state:
                    self.send_error(400, "state mismatch")
                    return
                if "error" in q:
                    box["error"] = q.get("error_description", q["error"])[0]
                else:
                    box["code"] = q.get("code", [""])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><p>You can close this window and return to paperful.</p></body></html>"
                )

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

        server = HTTPServer((host, port), Handler)
        url = (
            AUTHORIZE
            + "?"
            + urlencode(
                {
                    "client_id": cid,
                    "redirect_uri": redirect,
                    "response_type": "code",
                    "scope": "all",
                    "state": state,
                }
            )
        )
        if open_browser:
            webbrowser.open(url)
        server.handle_request()
        server.server_close()
        if box.get("error"):
            raise MendeleyAuthError(box["error"])
        code = box.get("code")
        if not code:
            raise MendeleyAuthError("Mendeley did not return an authorization code")
        tokens = self._exchange(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
            }
        )
        self._store(tokens)
        return tokens

    def get(self, path: str, *, accept: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, accept=accept, params=params)

    def paginate(self, path: str, *, accept: str, params: dict[str, Any] | None = None) -> list[Any]:
        query = dict(params or {})
        query.setdefault("limit", 500)
        url: str | None = path if path.startswith("http") else API + path
        out: list[Any] = []
        first = True
        while url:
            resp = self._raw(
                "GET", url, accept=accept, params=query if first else None
            )
            data = resp.json()
            if isinstance(data, list):
                out.extend(data)
            elif isinstance(data, dict):
                out.append(data)
            url = _next_link(resp.headers.get("link") or resp.headers.get("Link") or "")
            first = False
        return out

    def post(self, path: str, *, accept: str, content_type: str, body: Any) -> Any:
        return self._request(
            "POST", path, accept=accept, content_type=content_type, json_body=body
        )

    def patch(self, path: str, *, accept: str, content_type: str, body: Any) -> Any:
        return self._request(
            "PATCH", path, accept=accept, content_type=content_type, json_body=body
        )

    def delete(self, path: str, *, accept: str = "*/*") -> None:
        self._request("DELETE", path, accept=accept)

    def download_file(self, file_id: str, dest: Path) -> Path:
        """GET /files/{id} 303s to object storage. Do not forward the Bearer token."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = f"{API}/files/{file_id}"
        token = self.ensure_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "*/*"}
        resp = self.http.get(url, headers=headers, follow_redirects=False)
        if resp.status_code == 401:
            with self._lock:
                tokens = self._load()
                if tokens.get("refresh_token"):
                    self._refresh(tokens)
            token = self.ensure_token()
            headers["Authorization"] = f"Bearer {token}"
            resp = self.http.get(url, headers=headers, follow_redirects=False)
        if resp.status_code == 429:
            time.sleep(_retry_after(resp))
            resp = self.http.get(url, headers=headers, follow_redirects=False)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location") or resp.headers.get("location")
            if not location:
                raise LibraryError(
                    f"Mendeley file {file_id} redirected without Location"
                )
            # S3/CDN rejects a forwarded Authorization header.
            file_resp = self.http.get(location, follow_redirects=True)
            if file_resp.status_code >= 400:
                raise LibraryError(
                    f"Mendeley file download {file_resp.status_code}: "
                    f"{file_resp.text[:300]}"
                )
            dest.write_bytes(file_resp.content)
            return dest
        if resp.status_code >= 400:
            raise LibraryError(
                f"Mendeley GET {url} → {resp.status_code}: {resp.text[:400]}"
            )
        dest.write_bytes(resp.content)
        return dest

    def upload_file(self, document_id: str, pdf_path: Path) -> dict[str, Any]:
        token = self.ensure_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": ACCEPT_FILE,
            "Content-Type": "application/pdf",
            "Content-Disposition": f'attachment; filename="{pdf_path.name}"',
            "Link": f'<{API}/documents/{document_id}>; rel="document"',
        }
        data = pdf_path.read_bytes()
        resp = self.http.post(f"{API}/files", headers=headers, content=data)
        if resp.status_code == 401:
            token = self.ensure_token()
            headers["Authorization"] = f"Bearer {token}"
            resp = self.http.post(f"{API}/files", headers=headers, content=data)
        if resp.status_code == 400 and "already" in (resp.text or "").lower():
            return {"id": None, "duplicate": True}
        if resp.status_code == 429:
            time.sleep(_retry_after(resp))
            resp = self.http.post(f"{API}/files", headers=headers, content=data)
        if resp.status_code not in (200, 201):
            raise LibraryError(f"Mendeley file upload {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {"id": None}

    def _request(
        self,
        method: str,
        path: str,
        *,
        accept: str,
        params: dict[str, Any] | None = None,
        content_type: str | None = None,
        json_body: Any = None,
    ) -> Any:
        url = path if path.startswith("http") else API + path
        resp = self._raw(
            method,
            url,
            accept=accept,
            params=params,
            content_type=content_type,
            json_body=json_body,
        )
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def _raw(
        self,
        method: str,
        url: str,
        *,
        accept: str,
        params: dict[str, Any] | None = None,
        content_type: str | None = None,
        json_body: Any = None,
    ) -> httpx.Response:
        token = self.ensure_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": accept}
        if content_type:
            headers["Content-Type"] = content_type
        kwargs: dict[str, Any] = {"headers": headers}
        if params:
            kwargs["params"] = params
        if json_body is not None:
            kwargs["content"] = json.dumps(json_body)
        resp = self.http.request(method, url, **kwargs)
        if resp.status_code == 401:
            with self._lock:
                tokens = self._load()
                if tokens.get("refresh_token"):
                    self._refresh(tokens)
            token = self.ensure_token()
            headers["Authorization"] = f"Bearer {token}"
            resp = self.http.request(method, url, **kwargs)
        if resp.status_code == 429:
            time.sleep(_retry_after(resp))
            resp = self.http.request(method, url, **kwargs)
        if resp.status_code >= 400:
            raise LibraryError(f"Mendeley {method} {url} → {resp.status_code}: {resp.text[:400]}")
        return resp

    def _exchange(self, body: dict[str, str]) -> dict[str, Any]:
        cid, secret = client_id_of(self.cfg), client_secret_of(self.cfg)
        resp = self.http.post(
            TOKEN,
            data=body,
            auth=(cid, secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code >= 400:
            raise MendeleyAuthError(f"token exchange {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        data["expires_at"] = time.time() + int(data.get("expires_in") or 3600)
        return data

    def _refresh(self, tokens: dict[str, Any]) -> dict[str, Any]:
        fresh = self._exchange(
            {
                "grant_type": "refresh_token",
                "refresh_token": str(tokens["refresh_token"]),
                "redirect_uri": self.cfg.mendeley_redirect_uri,
            }
        )
        if not fresh.get("refresh_token"):
            fresh["refresh_token"] = tokens.get("refresh_token")
        self._store(fresh)
        return fresh

    def _load(self) -> dict[str, Any]:
        if self._tokens:
            return self._tokens
        path = token_path(self.cfg)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self._tokens = data if isinstance(data, dict) else {}
        return self._tokens

    def _store(self, tokens: dict[str, Any]) -> None:
        self._tokens = tokens
        path = token_path(self.cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(tokens), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass


def _next_link(header: str) -> str | None:
    for part in header.split(","):
        m = _LINK_NEXT.search(part)
        if m:
            return m.group(1)
    return None


def _retry_after(resp: httpx.Response) -> float:
    raw = resp.headers.get("Retry-After") or "5"
    try:
        return min(60.0, max(1.0, float(raw)))
    except ValueError:
        return 5.0


class MendeleyBackend:
    """Live Mendeley library via REST. Folders map to paperful collections."""

    def __init__(self, cfg: Config, client: MendeleyClient | None = None):
        self.cfg = cfg
        self.client = client or MendeleyClient(cfg)
        self._collections: dict[str, Collection] | None = None
        self._folder_docs: dict[str, set[str]] | None = None
        self._docs: dict[str, dict[str, Any]] | None = None

    def ping(self) -> dict[str, Any]:
        return self.client.ping()

    def supports_write(self) -> bool:
        return True

    def flush_writes(self) -> Path | None:
        return None

    def collections(self) -> dict[str, Collection]:
        if self._collections is None:
            self._load_folders()
        return self._collections or {}

    def resolve_collection(self, spec: str) -> Collection:
        from .zot import _squash

        cols = self.collections()
        spec_norm = spec.strip().strip("/")
        if spec_norm in cols:
            return cols[spec_norm]
        wanted = _squash(spec_norm)
        for c in cols.values():
            if wanted in (_squash(c.path), _squash(c.raw_path)):
                return c
        matches = [c for c in cols.values() if c.name.lower() == spec_norm.lower()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            paths = ", ".join(sorted(c.path for c in matches))
            raise LookupError(f"Folder name '{spec}' is ambiguous; use a path: {paths}")
        raise LookupError(f"No folder matching '{spec}'")

    def subtree_keys(self, root: Collection) -> list[str]:
        cols = self.collections()
        out = [root.key]
        frontier = [root.key]
        while frontier:
            parent = frontier.pop()
            for c in cols.values():
                if c.parent == parent:
                    out.append(c.key)
                    frontier.append(c.key)
        return out

    def collection_counts(self) -> dict[str, tuple[int, int]]:
        cols = self.collections()
        docs = self._documents()
        membership = self._folder_membership()
        counts: dict[str, tuple[int, int]] = {}
        for key, col in cols.items():
            keys: set[str] = set()
            for sub in self.subtree_keys(col):
                keys |= membership.get(sub, set())
            missing = sum(1 for k in keys if not (docs.get(k) or {}).get("file_attached"))
            counts[key] = (len(keys), missing)
        return counts

    def items_lacking_pdf(
        self, collection_keys: list[str] | None, upgrade_linked: bool = False
    ) -> list[Item]:
        del upgrade_linked
        return [it for it in self.items_in_scope(collection_keys) if not it.has_pdf]

    def items_in_scope(self, collection_keys: list[str] | None) -> list[Item]:
        cols = self.collections()
        docs = self._documents()
        membership = self._folder_membership()
        selected: set[str] | None = None
        allowed: set[str] | None = None
        if collection_keys is not None:
            selected = set(collection_keys)
            allowed = set()
            for ck in collection_keys:
                allowed |= membership.get(ck, set())
        items: list[Item] = []
        for doc_id, doc in docs.items():
            if allowed is not None and doc_id not in allowed:
                continue
            items.append(_item_from_doc(doc, cols, membership, selected))
        items.sort(
            key=lambda i: (
                i.collection_paths[0] if i.collection_paths else "~",
                i.label.lower(),
            )
        )
        return items

    def count_linked_url_only(self, collection_keys: list[str] | None) -> int:
        del collection_keys
        return 0

    def get_item(self, key: str) -> Item | None:
        try:
            doc = self.client.get(f"/documents/{key}", accept=ACCEPT_DOC, params={"view": "all"})
        except LibraryError:
            return None
        if not isinstance(doc, dict):
            return None
        membership = self._folder_membership()
        return _item_from_doc(doc, self.collections(), membership, None)

    def raw_item(self, key: str) -> dict[str, Any] | None:
        try:
            doc = self.client.get(f"/documents/{key}", accept=ACCEPT_DOC, params={"view": "all"})
        except LibraryError:
            return None
        return _raw_from_doc(doc) if isinstance(doc, dict) else None

    def children(self, key: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            files = self.client.get("/files", accept=ACCEPT_FILE, params={"document_id": key})
        except LibraryError:
            files = []
        for f in files or []:
            if not isinstance(f, dict):
                continue
            mime = (f.get("mime_type") or "").lower()
            out.append(
                {
                    "key": f.get("id"),
                    "data": {
                        "itemType": "attachment",
                        "contentType": mime or "application/pdf",
                        "linkMode": "imported_file",
                        "filename": f.get("file_name") or f.get("filename"),
                        "md5": f.get("filehash"),
                    },
                }
            )
        try:
            anns = self.client.get(
                "/annotations", accept=ACCEPT_ANN, params={"document_id": key}
            )
        except LibraryError:
            anns = []
        for ann in anns or []:
            if not isinstance(ann, dict):
                continue
            kind = (ann.get("type") or "").lower()
            text = ann.get("text") or ""
            if kind not in {"note", ""} and not text:
                continue
            if kind in {"highlight", "sticky_note"} and not text:
                continue
            tag = _tag_from_note_text(text)
            out.append(
                {
                    "key": ann.get("id"),
                    "data": {
                        "itemType": "note",
                        "note": text if "<" in text else f"<p>{text}</p>",
                        "tags": [{"tag": tag}] if tag else [],
                    },
                }
            )
        doc = (self._docs or {}).get(key)
        if not isinstance(doc, dict):
            try:
                got = self.client.get(
                    f"/documents/{key}", accept=ACCEPT_DOC, params={"view": "all"}
                )
            except LibraryError:
                got = None
            doc = got if isinstance(got, dict) else None
        notes_html = (doc or {}).get("notes")
        if notes_html and str(notes_html).strip():
            html = str(notes_html)
            if "<" not in html:
                html = f"<p>{html}</p>"
            out.append(
                {
                    "key": f"{key}-notes",
                    "data": {
                        "itemType": "note",
                        "note": html,
                        "tags": [{"tag": "mendeley-notes"}],
                    },
                }
            )
        return [ch for ch in out if ch.get("key")]

    def export_pdf(self, item: Item, dest: Path) -> Path | None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            files = self.client.get(
                "/files", accept=ACCEPT_FILE, params={"document_id": item.key}
            )
        except LibraryError:
            return None
        for f in files or []:
            if not isinstance(f, dict):
                continue
            mime = (f.get("mime_type") or "").lower()
            name = (f.get("file_name") or f.get("filename") or "").lower()
            if mime != "application/pdf" and not name.endswith(".pdf"):
                continue
            fid = f.get("id")
            if not fid:
                continue
            try:
                return self.client.download_file(str(fid), dest)
            except Exception:
                return None
        return None

    def attach(
        self,
        item_key: str,
        pdf_path: Path,
        title: str | None = None,
        note: str | None = None,
    ) -> AttachResult:
        del title, note
        if not pdf_path.is_file():
            return AttachResult(False, reason=f"file missing: {pdf_path}", code="other")
        try:
            result = self.client.upload_file(item_key, pdf_path)
        except LibraryError as exc:
            msg = str(exc)
            return AttachResult(False, reason=msg, code=attach_failure_code(msg))
        if result.get("duplicate"):
            return AttachResult(True, attachment_key=None, reason="unchanged", code="unchanged")
        return AttachResult(
            True,
            attachment_key=str(result.get("id") or ""),
            reason="success",
            code="success",
        )

    def apply_patch(self, item_key: str, fields: dict[str, Any]) -> None:
        body: dict[str, Any] = {}
        mapping = {
            "doi": "doi",
            "title": "title",
            "date": "year",
            "publicationTitle": "source",
        }
        for name, value in fields.items():
            dest = mapping.get(name, name)
            if dest == "doi":
                ids = {"doi": value}
                body["identifiers"] = ids
            elif dest == "year":
                text = str(value)
                m = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", text)
                if m:
                    body["year"] = int(m.group(1))
            else:
                body[dest] = value
        if not body:
            return
        self.client.patch(
            f"/documents/{item_key}",
            accept=ACCEPT_DOC,
            content_type=ACCEPT_DOC,
            body=body,
        )
        self._docs = None

    def merge_into(self, keep_key: str, drop_key: str) -> dict[str, Any]:
        raise LibraryError(
            "Mendeley cannot merge items through paperful. "
            "dedupe --apply needs Zotero so the PDF and notes stay on one item."
        )

    def trash_item(self, item_key: str) -> None:
        self.client.post(
            f"/documents/{item_key}/trash",
            accept=ACCEPT_DOC,
            content_type=ACCEPT_DOC,
            body={},
        )
        self._docs = None

    def find_child_note_keys(self, item_key: str, tag: str) -> list[str]:
        want = tag.strip().lower()
        out: list[str] = []
        for ch in self.children(item_key):
            data = ch.get("data") or {}
            if data.get("itemType") != "note":
                continue
            tags = [t.get("tag", "").lower() for t in data.get("tags") or []]
            if want in tags:
                key = ch.get("key")
                if key:
                    out.append(str(key))
        return out

    def read_child_note(self, item_key: str, tag: str) -> str | None:
        keys = self.find_child_note_keys(item_key, tag)
        if not keys:
            return None
        for ch in self.children(item_key):
            if ch.get("key") == keys[0]:
                return str((ch.get("data") or {}).get("note") or "") or None
        return None

    def create_or_update_note(self, item_key: str, html: str, tag: str) -> str:
        marked = _mark_note(html, tag)
        existing = self.find_child_note_keys(item_key, tag)
        if existing:
            self.client.patch(
                f"/annotations/{existing[0]}",
                accept=ACCEPT_ANN,
                content_type=ACCEPT_ANN,
                body={"text": marked},
            )
            return existing[0]
        created = self.client.post(
            "/annotations",
            accept=ACCEPT_ANN,
            content_type=ACCEPT_ANN,
            body={
                "document_id": item_key,
                "type": "note",
                "text": marked,
                "privacy_level": "private",
            },
        )
        if isinstance(created, dict) and created.get("id"):
            return str(created["id"])
        raise LibraryError("Mendeley did not create a note annotation")

    def find_collection_note_keys(self, collection_key: str, tag: str) -> list[str]:
        want = tag.strip().lower()
        out: list[str] = []
        for it in self.items_in_scope([collection_key]):
            if it.item_type != "document":
                continue
            tags = []
            raw = self.raw_item(it.key)
            if raw:
                tags = [
                    str(t.get("tag", "")).lower()
                    for t in ((raw.get("data") or {}).get("tags") or [])
                    if isinstance(t, dict)
                ]
            if want in tags:
                out.append(it.key)
        return out

    def create_or_update_collection_note(
        self, collection_key: str, html: str, tags: list[str]
    ) -> str:
        lookup = (tags[-1] if tags else "paperful-report").strip().lower()
        existing = self.find_collection_note_keys(collection_key, lookup)
        payload = {
            "title": lookup,
            "type": "generic",
            "tags": tags,
        }
        if existing:
            self.client.patch(
                f"/documents/{existing[0]}",
                accept=ACCEPT_DOC,
                content_type=ACCEPT_DOC,
                body=payload,
            )
            self.create_or_update_note(existing[0], html, lookup)
            return existing[0]
        created = self.client.post(
            "/documents",
            accept=ACCEPT_DOC,
            content_type=ACCEPT_DOC,
            body=payload,
        )
        if not isinstance(created, dict) or not created.get("id"):
            raise LibraryError("Mendeley did not create a report document")
        new_id = str(created["id"])
        self.client.post(
            f"/folders/{collection_key}/documents",
            accept=ACCEPT_FOLDER,
            content_type=ACCEPT_FOLDER,
            body={"id": new_id},
        )
        self.create_or_update_note(new_id, html, lookup)
        self._docs = None
        return new_id

    def ensure_collection_path(self, path: str) -> str:
        parts = [p for p in path.strip("/").split("/") if p]
        if not parts:
            raise LibraryError(f"empty folder path {path!r}")
        parent: str | None = None
        built: list[str] = []
        for part in parts:
            built.append(part)
            sofar = "/".join(built)
            self._collections = None
            found = next((c for c in self.collections().values() if c.path == sofar), None)
            if found is not None:
                parent = found.key
                continue
            body: dict[str, Any] = {"name": part}
            if parent:
                body["parent_id"] = parent
            created = self.client.post(
                "/folders",
                accept=ACCEPT_FOLDER,
                content_type=ACCEPT_FOLDER,
                body=body,
            )
            if not isinstance(created, dict) or not created.get("id"):
                raise LibraryError(f"Mendeley did not return a folder id for {sofar}")
            parent = str(created["id"])
            self._collections = None
            self._folder_docs = None
        if parent is None:
            raise LibraryError(f"could not resolve folder {path!r}")
        return parent

    def create_parent(self, data: dict[str, Any]) -> str:
        body = zotero_payload_to_mendeley(data)
        created = self.client.post(
            "/documents",
            accept=ACCEPT_DOC,
            content_type=ACCEPT_DOC,
            body=body,
        )
        if not isinstance(created, dict) or not created.get("id"):
            raise LibraryError("Mendeley did not return an id for the new document")
        new_id = str(created["id"])
        for ck in data.get("collections") or []:
            if ck:
                try:
                    self.client.post(
                        f"/folders/{ck}/documents",
                        accept=ACCEPT_FOLDER,
                        content_type=ACCEPT_FOLDER,
                        body={"id": new_id},
                    )
                except LibraryError:
                    continue
        self._docs = None
        self._folder_docs = None
        return new_id

    def _load_folders(self) -> None:
        raw = self.client.paginate("/folders", accept=ACCEPT_FOLDER)
        shaped = []
        for folder in raw:
            if not isinstance(folder, dict):
                continue
            parent = folder.get("parent_id") or None
            if parent == "root":
                parent = None
            shaped.append(
                {
                    "key": folder.get("id"),
                    "data": {
                        "key": folder.get("id"),
                        "name": folder.get("name") or "",
                        "parentCollection": parent,
                    },
                }
            )
        self._collections = build_collection_tree(shaped)

    def _documents(self) -> dict[str, dict[str, Any]]:
        if self._docs is None:
            rows = self.client.paginate(
                "/documents", accept=ACCEPT_DOC, params={"view": "all"}
            )
            self._docs = {
                str(d["id"]): d for d in rows if isinstance(d, dict) and d.get("id")
            }
        return self._docs

    def _folder_membership(self) -> dict[str, set[str]]:
        if self._folder_docs is None:
            mapping: dict[str, set[str]] = {k: set() for k in self.collections()}
            used_uuids = False
            for doc_id, doc in self._documents().items():
                uuids = doc.get("folder_uuids") if isinstance(doc, dict) else None
                if not isinstance(uuids, list) or not uuids:
                    continue
                used_uuids = True
                for fid in uuids:
                    if fid:
                        mapping.setdefault(str(fid), set()).add(doc_id)
            if not used_uuids:
                for key in self.collections():
                    try:
                        rows = self.client.paginate(
                            f"/folders/{key}/documents", accept=ACCEPT_DOC
                        )
                    except LibraryError:
                        rows = []
                    ids: set[str] = set()
                    for row in rows:
                        if isinstance(row, dict) and row.get("id"):
                            ids.add(str(row["id"]))
                        elif isinstance(row, str):
                            ids.add(row)
                    mapping[key] = ids
            self._folder_docs = mapping
        return self._folder_docs


def zotero_payload_to_mendeley(data: dict[str, Any]) -> dict[str, Any]:
    authors = []
    for c in data.get("creators") or []:
        if not isinstance(c, dict):
            continue
        if c.get("creatorType") not in (None, "", "author"):
            continue
        last = (c.get("lastName") or c.get("name") or "").strip()
        first = (c.get("firstName") or "").strip()
        if last:
            authors.append({"last_name": last, "first_name": first})
    identifiers: dict[str, str] = {}
    doi = normalize_doi(data.get("DOI") or data.get("doi") or "")
    if doi:
        identifiers["doi"] = doi
    extra = data.get("extra") or ""
    pmid = extract_pmid(extra)
    if pmid:
        identifiers["pmid"] = pmid
    arxiv = extract_arxiv_id(data.get("url") or "") or extract_arxiv_id(extra)
    if arxiv:
        identifiers["arxiv"] = arxiv
    year = parse_year(data.get("date"))
    body: dict[str, Any] = {
        "title": data.get("title") or "",
        "type": zotero_to_mendeley(str(data.get("itemType") or "document")),
        "authors": authors,
        "abstract": data.get("abstractNote") or "",
        "source": data.get("publicationTitle") or "",
        "websites": [data["url"]] if data.get("url") else [],
        "tags": [
            t.get("tag") if isinstance(t, dict) else t
            for t in (data.get("tags") or [])
            if (t.get("tag") if isinstance(t, dict) else t)
        ],
    }
    if year:
        body["year"] = year
    if identifiers:
        body["identifiers"] = identifiers
    return {k: v for k, v in body.items() if v not in ("", [], None)}


def _item_from_doc(
    doc: dict[str, Any],
    cols: dict[str, Collection],
    membership: dict[str, set[str]],
    selected: set[str] | None,
) -> Item:
    ident = doc.get("identifiers") or {}
    if not isinstance(ident, dict):
        ident = {}
    extra_bits = []
    pmid = ident.get("pmid")
    if pmid:
        extra_bits.append(f"PMID: {pmid}")
    doi = normalize_doi(ident.get("doi") or "") or extract_doi(doc.get("source") or "")
    websites = doc.get("websites") or []
    url = websites[0] if websites else None
    arxiv = ident.get("arxiv") or extract_arxiv_id(url or "")
    authors = doc.get("authors") or []
    surnames = [
        str(a.get("last_name") or "").strip()
        for a in authors
        if isinstance(a, dict)
    ]
    surnames = [s for s in surnames if s]
    first = surnames[0] if surnames else None
    paths = []
    doc_id = str(doc.get("id") or "")
    for ck, members in membership.items():
        if doc_id in members and ck in cols and (selected is None or ck in selected):
            paths.append(cols[ck].path)
    if not paths:
        paths = [UNCOLLECTED]
    year = doc.get("year")
    if not isinstance(year, int):
        year = parse_year(str(year) if year else None)
    date = None
    if year:
        month = doc.get("month")
        day = doc.get("day")
        if month and day:
            date = f"{year}-{int(month):02d}-{int(day):02d}"
        else:
            date = str(year)
    tags = doc.get("tags") or []
    extra = "\n".join(extra_bits)
    if tags and isinstance(tags, list):
        pass
    return Item(
        key=doc_id,
        item_type=mendeley_to_zotero(str(doc.get("type") or "generic")),
        title=(doc.get("title") or "").strip() or "(untitled)",
        doi=doi,
        arxiv_id=arxiv,
        url=(url or "").strip() or None,
        year=year,
        first_author=first,
        collection_paths=sorted(set(paths)),
        doi_source="field" if doi else "none",
        library_doi=doi,
        pmid=str(pmid) if pmid else None,
        extra=extra,
        publication_title=(doc.get("source") or "").strip() or None,
        date=date,
        has_pdf=bool(doc.get("file_attached")),
        has_linked_url=False,
        date_added=(doc.get("created") or None),
        creator_count=len(authors) if isinstance(authors, list) else 0,
        abstract=(doc.get("abstract") or "").strip() or None,
        creator_surnames=surnames,
    )


def _raw_from_doc(doc: dict[str, Any]) -> dict[str, Any]:
    ident = doc.get("identifiers") if isinstance(doc.get("identifiers"), dict) else {}
    creators = []
    for a in doc.get("authors") or []:
        if isinstance(a, dict):
            creators.append(
                {
                    "creatorType": "author",
                    "firstName": a.get("first_name") or "",
                    "lastName": a.get("last_name") or "",
                }
            )
    websites = doc.get("websites") or []
    tags = [{"tag": t} for t in (doc.get("tags") or []) if isinstance(t, str)]
    extra = ""
    if ident.get("pmid"):
        extra = f"PMID: {ident['pmid']}"
    data = {
        "itemType": mendeley_to_zotero(str(doc.get("type") or "generic")),
        "title": doc.get("title") or "",
        "creators": creators,
        "abstractNote": doc.get("abstract") or "",
        "date": str(doc.get("year") or ""),
        "DOI": ident.get("doi") or "",
        "url": websites[0] if websites else "",
        "extra": extra,
        "publicationTitle": doc.get("source") or "",
        "tags": tags,
        "collections": [],
        "dateAdded": doc.get("created"),
        "dateModified": doc.get("last_modified"),
        "key": doc.get("id"),
    }
    fields = {
        k: v
        for k, v in doc.items()
        if k
        not in {
            "id",
            "title",
            "type",
            "authors",
            "abstract",
            "year",
            "identifiers",
            "websites",
            "source",
            "tags",
            "created",
            "last_modified",
        }
    }
    data.update({k: v for k, v in fields.items() if k not in data})
    return {
        "key": doc.get("id"),
        "version": doc.get("last_modified"),
        "data": data,
    }


def _mark_note(html: str, tag: str) -> str:
    marker = f"{_NOTE_MARK}{tag}"
    if marker in html:
        return html
    return f"<!-- {marker} -->\n{html}"


def _tag_from_note_text(text: str) -> str:
    m = re.search(rf"{re.escape(_NOTE_MARK)}([A-Za-z0-9:_-]+)", text or "")
    if m:
        return m.group(1)
    if _SUMMARY_PREFIX in (text or ""):
        return _SUMMARY_PREFIX
    return ""
