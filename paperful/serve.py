"""Localhost HTTP: JSON capability API plus the server-rendered workbench.

JSON routes (health, doctor, collections, last-run, dry-run refs-gap / ask)
do not write the library. Workbench forms write only after a review token
(Grab fetches to disk; Attach and Apply write the catalogue). Optional extra:
``paperful[serve]``.

Trust model: bind loopback only unless ``--allow-remote-bind``. By default
there is no HTTP auth — anyone who can reach the port can drive
Grab/Attach/Settings. Setting ``PAPERFUL_UI_TOKEN`` (or ``--ui-token``)
requires a bearer token on every request except ``/health``, which makes a
deliberately exposed bind safer. See SECURITY.md.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from . import __version__
from .config import Config

SERVE_HINT = "paperful serve needs FastAPI. Install with: uv sync --extra serve"
REMOTE_BIND_HINT = (
    "Refusing to bind {host!r} (not loopback). "
    "Pass --allow-remote-bind if you intentionally expose the workbench "
    "(no auth by default; set PAPERFUL_UI_TOKEN so only token holders can "
    "Grab/Attach/change Settings)."
)


def fastapi_available() -> bool:
    try:
        import fastapi  # noqa: F401
    except ImportError:
        return False
    return True


def create_app(cfg: Config, *, ui_token: str | None = None) -> Any:
    """ASGI app. Import FastAPI only when the extra is installed."""
    from fastapi import FastAPI

    from .agent_ops import (
        collections_tree,
        doctor_payload,
        last_run,
        run_ask,
        run_refs_gap,
    )

    app = FastAPI(title="paperful", version=__version__)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__}

    @app.get("/v1/doctor")
    def doctor() -> list[dict[str, Any]]:
        return doctor_payload(cfg)

    @app.get("/v1/collections")
    def collections() -> dict[str, Any]:
        return collections_tree(cfg)

    @app.get("/v1/runs/last")
    def runs_last() -> dict[str, Any]:
        return {"ok": True, "report": last_run(cfg)}

    @app.post("/v1/refs-gap")
    def refs_gap(body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = body or {}
        return run_refs_gap(cfg, str(payload.get("collection") or ""))

    @app.post("/v1/ask")
    def ask(body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = body or {}
        return run_ask(
            cfg,
            str(payload.get("question") or ""),
            str(payload.get("collection") or ""),
            ask_mode=str(payload["ask_mode"]) if payload.get("ask_mode") else None,
        )

    from .ui.app import mount_ui
    from .ui.origin_guard import OriginGuardMiddleware
    from .ui.security_headers import SecurityHeadersMiddleware
    from .ui.token_guard import TokenGuardMiddleware, ui_token_from_env

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(OriginGuardMiddleware)
    token = ui_token_from_env() if ui_token is None else ui_token.strip()
    if token:
        # Added last so it runs first: reject unauthenticated requests
        # before any origin or route handling.
        app.add_middleware(TokenGuardMiddleware, token=token)

    mount_ui(app, cfg)

    return app


def is_loopback_bind_host(host: str) -> bool:
    """True for addresses that only accept connections from this machine."""
    raw = (host or "").strip().lower()
    if raw in {"127.0.0.1", "::1", "localhost"}:
        return True
    try:
        return bool(ipaddress.ip_address(raw).is_loopback)
    except ValueError:
        return False


def run_server(
    cfg: Config,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    allow_remote_bind: bool = False,
    ui_token: str | None = None,
) -> None:
    if not fastapi_available():
        raise RuntimeError(SERVE_HINT)
    if not is_loopback_bind_host(host) and not allow_remote_bind:
        raise RuntimeError(REMOTE_BIND_HINT.format(host=host))
    import uvicorn

    uvicorn.run(create_app(cfg, ui_token=ui_token), host=host, port=port)
