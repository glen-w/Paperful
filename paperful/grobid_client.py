"""HTTP client for an external GROBID REST server.

See https://github.com/grobidOrg/grobid. Paperful does not start or bundle
the Java service; the operator runs it (Docker) and points ``[grobid].base_url``
at it.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from .llm.validate import (
    DOCKER_GATEWAY_HOST,
    LOCAL_HOSTS,
    _in_docker,
    _ipv4_literal,
    _replace_url_host,
)

DEFAULT_GROBID_BASE_URL = "http://127.0.0.1:8070"


class GrobidError(Exception):
    """GROBID REST call failed."""


class GrobidConfigError(GrobidError):
    """Invalid or incomplete GROBID configuration."""


def resolve_grobid_base_url(url: str | None = None) -> str:
    """URL to call for GROBID (Docker-aware, same idea as Ollama).

    Loopback in ``config.toml`` stays ``127.0.0.1:8070`` on the host. Inside a
    container it is rewritten to ``host.docker.internal`` (or
    ``PAPERFUL_GROBID_HOST``). Remote hostnames are never rewritten.
    """
    raw = (url or "").strip() or DEFAULT_GROBID_BASE_URL
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.hostname:
        return raw

    env_host = (os.environ.get("PAPERFUL_GROBID_HOST") or "").strip()
    docker = _in_docker()
    host = parsed.hostname
    if host in LOCAL_HOSTS:
        if env_host:
            if env_host == DOCKER_GATEWAY_HOST and not docker:
                host = "127.0.0.1"
            else:
                host = env_host
        elif docker:
            host = DOCKER_GATEWAY_HOST

    if docker and host == DOCKER_GATEWAY_HOST:
        ipv4 = _ipv4_literal(DOCKER_GATEWAY_HOST)
        if ipv4:
            host = ipv4

    if host == parsed.hostname:
        return raw
    return _replace_url_host(raw, host)


def grobid_url_is_local(url: str) -> bool:
    """True when the resolved URL is loopback, Compose DNS, or the Docker gateway."""
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    if host in LOCAL_HOSTS:
        return True
    if host == DOCKER_GATEWAY_HOST:
        return True
    ipv4 = _ipv4_literal(DOCKER_GATEWAY_HOST)
    if ipv4 and host == ipv4:
        return True
    # Compose service names have no dots (e.g. ``grobid``).
    if "." not in host:
        return True
    return False


def grobid_egress_is_remote(cfg) -> bool:
    """True when PDF bytes sent to GROBID may leave this machine."""
    resolved = resolve_grobid_base_url(cfg.grobid_base_url)
    return not grobid_url_is_local(resolved)


def validate_grobid_url(url: str, allow_remote: bool) -> str:
    """Return the resolved URL, or raise if it is not local and remote is off."""
    resolved = resolve_grobid_base_url(url)
    parsed = urlparse(resolved)
    if parsed.scheme not in ("http", "https"):
        raise GrobidConfigError(
            f"GROBID URL scheme {parsed.scheme!r} is not supported; use http or https."
        )
    if not parsed.hostname:
        raise GrobidConfigError("GROBID URL must include a hostname.")
    if grobid_url_is_local(resolved):
        return resolved
    if not allow_remote:
        raise GrobidConfigError(
            f"GROBID URL host {parsed.hostname!r} is not local. "
            "Set grobid.allow_remote = true to permit sending PDFs off this machine."
        )
    return resolved


class GrobidClient:
    """Thin httpx wrapper around GROBID ``/api/*`` routes."""

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = 120.0,
        consolidate_header: int = 0,
        consolidate_citations: int = 0,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/") + "/"
        self._owns = client is None
        self.consolidate_header = int(consolidate_header)
        self.consolidate_citations = int(consolidate_citations)
        wall = max(5.0, float(timeout))
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(wall, connect=15.0),
            follow_redirects=True,
        )

    def close(self) -> None:
        if self._owns:
            self._client.close()

    def __enter__(self) -> GrobidClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def health(self) -> bool:
        try:
            resp = self._client.get(self._url("/api/isalive"))
        except httpx.HTTPError:
            return False
        if resp.status_code != 200:
            return False
        return resp.text.strip().lower() in {"true", "ok", "1"}

    def version(self) -> str:
        try:
            resp = self._client.get(self._url("/api/version"))
        except httpx.HTTPError as exc:
            raise GrobidError(type(exc).__name__) from exc
        if resp.status_code >= 400:
            raise GrobidError(f"version HTTP {resp.status_code}")
        return (resp.text or "").strip()

    def process_fulltext(self, pdf: Path) -> str:
        """POST the PDF to ``/api/processFulltextDocument``. Returns TEI XML."""
        if not pdf.is_file():
            raise GrobidError(f"no such file: {pdf}")
        data = {
            "consolidateHeader": str(self.consolidate_header),
            "consolidateCitations": str(self.consolidate_citations),
        }
        try:
            with pdf.open("rb") as fh:
                resp = self._client.post(
                    self._url("/api/processFulltextDocument"),
                    data=data,
                    files={"input": (pdf.name, fh, "application/pdf")},
                )
        except httpx.TimeoutException as exc:
            raise GrobidError("timeout") from exc
        except httpx.HTTPError as exc:
            raise GrobidError(type(exc).__name__) from exc
        if resp.status_code >= 400:
            raise GrobidError(f"processFulltextDocument HTTP {resp.status_code}")
        text = resp.text or ""
        if "<TEI" not in text and "<tei" not in text:
            raise GrobidError("response is not TEI XML")
        return text


def grobid_client_from_config(cfg, *, client: httpx.Client | None = None) -> GrobidClient:
    url = validate_grobid_url(cfg.grobid_base_url, cfg.grobid_allow_remote)
    return GrobidClient(
        url,
        client=client,
        timeout=cfg.grobid_timeout_s,
        consolidate_header=cfg.grobid_consolidate_header,
        consolidate_citations=cfg.grobid_consolidate_citations,
    )
