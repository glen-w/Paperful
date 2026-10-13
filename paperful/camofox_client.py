"""HTTP client for an external camofox-browser REST server.

See https://github.com/jo-inc/camofox-browser. Paperful does not start or
bundle the Node server; the operator runs it (npx/Docker) and points
``[camofox].base_url`` at it.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx


class CamofoxError(Exception):
    """camofox REST call failed."""


@dataclass(frozen=True)
class CamofoxLink:
    href: str
    text: str = ""
    ref: str = ""


@dataclass(frozen=True)
class CamofoxDownload:
    filename: str
    url: str = ""
    state: str = ""
    data: bytes | None = None


def camofox_access_key() -> str:
    return os.environ.get("CAMOFOX_ACCESS_KEY", "").strip()


class CamofoxClient:
    """Thin httpx wrapper around camofox tab/session routes."""

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        access_key: str | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/") + "/"
        self._owns = client is None
        headers: dict[str, str] = {}
        key = access_key if access_key is not None else camofox_access_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(timeout),
            headers=headers,
            follow_redirects=True,
        )

    def close(self) -> None:
        if self._owns:
            self._client.close()

    def __enter__(self) -> CamofoxClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def _json(self, resp: httpx.Response) -> dict[str, Any]:
        try:
            data = resp.json()
        except ValueError as exc:
            raise CamofoxError(f"invalid JSON ({resp.status_code})") from exc
        if not isinstance(data, dict):
            raise CamofoxError(f"unexpected JSON ({resp.status_code})")
        return data

    def health(self) -> bool:
        try:
            resp = self._client.get(self._url("/health"))
        except httpx.HTTPError:
            return False
        return resp.status_code == 200

    def create_tab(
        self,
        *,
        user_id: str,
        session_key: str,
        url: str | None = None,
    ) -> str:
        body: dict[str, Any] = {"userId": user_id, "sessionKey": session_key}
        if url:
            body["url"] = url
        try:
            resp = self._client.post(self._url("/tabs"), json=body)
        except httpx.HTTPError as exc:
            raise CamofoxError(type(exc).__name__) from exc
        if resp.status_code >= 400:
            raise CamofoxError(f"create tab HTTP {resp.status_code}")
        data = self._json(resp)
        tab_id = str(data.get("tabId") or "").strip()
        if not tab_id:
            raise CamofoxError("create tab missing tabId")
        return tab_id

    def navigate(self, tab_id: str, *, user_id: str, url: str) -> None:
        try:
            resp = self._client.post(
                self._url(f"/tabs/{tab_id}/navigate"),
                json={"userId": user_id, "url": url},
            )
        except httpx.HTTPError as exc:
            raise CamofoxError(type(exc).__name__) from exc
        if resp.status_code >= 400:
            raise CamofoxError(f"navigate HTTP {resp.status_code}")

    def click(self, tab_id: str, *, user_id: str, ref: str) -> None:
        try:
            resp = self._client.post(
                self._url(f"/tabs/{tab_id}/click"),
                json={"userId": user_id, "ref": ref},
            )
        except httpx.HTTPError as exc:
            raise CamofoxError(type(exc).__name__) from exc
        if resp.status_code >= 400:
            raise CamofoxError(f"click HTTP {resp.status_code}")

    def snapshot(self, tab_id: str, *, user_id: str) -> str:
        try:
            resp = self._client.get(
                self._url(f"/tabs/{tab_id}/snapshot"),
                params={"userId": user_id},
            )
        except httpx.HTTPError as exc:
            raise CamofoxError(type(exc).__name__) from exc
        if resp.status_code >= 400:
            raise CamofoxError(f"snapshot HTTP {resp.status_code}")
        data = self._json(resp)
        return str(data.get("snapshot") or "")

    def links(self, tab_id: str, *, user_id: str) -> list[CamofoxLink]:
        try:
            resp = self._client.get(
                self._url(f"/tabs/{tab_id}/links"),
                params={"userId": user_id},
            )
        except httpx.HTTPError as exc:
            raise CamofoxError(type(exc).__name__) from exc
        if resp.status_code >= 400:
            raise CamofoxError(f"links HTTP {resp.status_code}")
        data = self._json(resp)
        out: list[CamofoxLink] = []
        for row in data.get("links") or []:
            if not isinstance(row, dict):
                continue
            href = str(row.get("href") or "").strip()
            if not href:
                continue
            out.append(
                CamofoxLink(
                    href=href,
                    text=str(row.get("text") or ""),
                    ref=str(row.get("ref") or ""),
                )
            )
        return out

    def fetch_current_resource(self, tab_id: str, *, user_id: str) -> bool:
        try:
            resp = self._client.post(
                self._url(f"/tabs/{tab_id}/fetch-current-resource"),
                json={"userId": user_id},
            )
        except httpx.HTTPError as exc:
            raise CamofoxError(type(exc).__name__) from exc
        return resp.status_code == 200

    def downloads(
        self,
        tab_id: str,
        *,
        user_id: str,
        include_data: bool = True,
        consume: bool = True,
    ) -> list[CamofoxDownload]:
        params: dict[str, str | bool] = {"userId": user_id}
        if include_data:
            params["includeData"] = "true"
        if consume:
            params["consume"] = "true"
        try:
            resp = self._client.get(
                self._url(f"/tabs/{tab_id}/downloads"),
                params=params,
            )
        except httpx.HTTPError as exc:
            raise CamofoxError(type(exc).__name__) from exc
        if resp.status_code >= 400:
            raise CamofoxError(f"downloads HTTP {resp.status_code}")
        data = self._json(resp)
        out: list[CamofoxDownload] = []
        for row in data.get("downloads") or []:
            if not isinstance(row, dict):
                continue
            raw = row.get("data") or row.get("base64") or ""
            blob: bytes | None = None
            if isinstance(raw, str) and raw.strip():
                try:
                    blob = base64.b64decode(raw, validate=False)
                except Exception:
                    blob = None
            out.append(
                CamofoxDownload(
                    filename=str(row.get("filename") or ""),
                    url=str(row.get("url") or ""),
                    state=str(row.get("state") or ""),
                    data=blob,
                )
            )
        return out

    def close_tab(self, tab_id: str, *, user_id: str) -> None:
        try:
            self._client.delete(
                self._url(f"/tabs/{tab_id}"),
                params={"userId": user_id},
            )
        except httpx.HTTPError:
            pass

    def close_session(self, user_id: str) -> None:
        try:
            self._client.delete(self._url(f"/sessions/{user_id}"))
        except httpx.HTTPError:
            pass
