"""Optional bearer-token gate for the workbench (off unless a token is set).

Loopback serving stays auth-free by default (see SECURITY.md). When an
operator intentionally exposes the workbench beyond loopback
(``paperful serve --allow-remote-bind``), setting ``PAPERFUL_UI_TOKEN``
(or ``--ui-token``) requires every request except ``/health`` to carry
``Authorization: Bearer <token>`` or ``X-Paperful-Token: <token>``.
This is a single-operator shared secret, not user accounts or sessions.
"""

from __future__ import annotations

import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

TOKEN_ENV = "PAPERFUL_UI_TOKEN"  # noqa: S105 -- name only, not a credential
TOKEN_HEADER = "x-paperful-token"  # noqa: S105 -- name only, not a credential
EXEMPT_PATHS = frozenset({"/health"})


def ui_token_from_env() -> str:
    return (os.environ.get(TOKEN_ENV) or "").strip()


def token_matches(request: Request, expected: str) -> bool:
    auth = (request.headers.get("authorization") or "").strip()
    supplied = ""
    if auth.lower().startswith("bearer "):
        supplied = auth[7:].strip()
    if not supplied:
        supplied = (request.headers.get(TOKEN_HEADER) or "").strip()
    if not supplied or not expected:
        return False
    return secrets.compare_digest(supplied, expected)


class TokenGuardMiddleware(BaseHTTPMiddleware):
    """Reject unauthenticated requests when a UI token is configured."""

    def __init__(self, app, token: str) -> None:  # noqa: ANN001 - Starlette app type
        super().__init__(app)
        self._token = (token or "").strip()

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self._token or request.url.path in EXEMPT_PATHS:
            return await call_next(request)
        if token_matches(request, self._token):
            return await call_next(request)
        return JSONResponse(
            {"ok": False, "error": "unauthorized: missing or bad UI token"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
