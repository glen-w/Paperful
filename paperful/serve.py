"""Localhost HTTP: JSON capability API plus the server-rendered workbench.

JSON routes (health, doctor, collections, last-run, dry-run refs-gap / ask)
do not write the library. Workbench forms write only after a review token
(Grab fetches to disk; Attach and Apply write the catalogue). Optional extra:
``paperful[serve]``.
"""

from __future__ import annotations

from typing import Any

from . import __version__
from .config import Config

SERVE_HINT = "paperful serve needs FastAPI. Install with: uv sync --extra serve"


def fastapi_available() -> bool:
    try:
        import fastapi  # noqa: F401
    except ImportError:
        return False
    return True


def create_app(cfg: Config) -> Any:
    """ASGI app. Import FastAPI only when the extra is installed."""
    from fastapi import FastAPI

    from .agent_ops import collections_tree, doctor_payload, last_run, run_ask, run_refs_gap

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
        )

    from .ui.app import mount_ui

    mount_ui(app, cfg)

    return app


def run_server(cfg: Config, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    if not fastapi_available():
        raise RuntimeError(SERVE_HINT)
    import uvicorn

    uvicorn.run(create_app(cfg), host=host, port=port)
