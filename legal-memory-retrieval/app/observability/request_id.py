"""Per-request correlation id.

Accepts a client X-Request-ID when it is a short token, otherwise generates one.
Stored on a ContextVar so sync agent logs can include it without threading the
value through every call. The header is echoed on the response.
"""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

from opentelemetry import trace

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
client_ip_var: ContextVar[str] = ContextVar("client_ip", default="")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_HEADER = b"x-request-id"


def current_request_id() -> str:
    """Return the active request id, or an empty string outside a request."""
    return request_id_var.get()


def current_client_ip() -> str:
    """Client address of the active request (proxy-resolved when uvicorn runs with --proxy-headers)."""
    return client_ip_var.get()


def accept_request_id(raw: str | None) -> str:
    """Use a safe client token, or mint a new id."""
    candidate = (raw or "").strip()
    if candidate and _REQUEST_ID_RE.fullmatch(candidate):
        return candidate
    return str(uuid.uuid4())


class RequestIDMiddleware:
    """ASGI middleware. Does not buffer the body, so SSE streams stay live."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        raw = ""
        for key, value in scope.get("headers") or []:
            if key.lower() == _HEADER:
                raw = value.decode("latin-1", errors="replace")
                break
        request_id = accept_request_id(raw)
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["request_id"] = request_id
        token = request_id_var.set(request_id)
        client = scope.get("client")
        ip_token = client_ip_var.set(client[0] if client else "")
        span = trace.get_current_span()
        if span is not None:
            span.set_attribute("request_id", request_id)

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((_HEADER, request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)
            client_ip_var.reset(ip_token)
