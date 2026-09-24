"""Request body size limits, enforced while the body streams in.

FastAPI parses multipart forms before the endpoint runs, spooling files to disk, so
an endpoint-level check is too late to stop a request from filling the disk. This
middleware counts bytes as they arrive (it does not trust Content-Length) and
answers 413 as soon as the limit is crossed.
"""
from __future__ import annotations

import json

from app.config import settings

MB = 1024 * 1024
UPLOAD_PREFIXES = ("/api/uploads/batches",)
DEFAULT_LIMIT = 10 * MB


class _TooLarge(Exception):
    pass


def limit_for(path: str) -> int:
    if path.startswith(UPLOAD_PREFIXES):
        # multipart framing overhead on top of the file bytes
        return settings.max_upload_batch_mb * MB + MB
    return DEFAULT_LIMIT


class BodySizeLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return

        limit = limit_for(scope["path"])
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _reject(send, limit)
            return

        received = 0
        started = False

        async def counting_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _TooLarge()
            return message

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _TooLarge:
            if not started:
                await _reject(send, limit)


async def _reject(send, limit: int) -> None:
    body = json.dumps({"detail": f"Request body larger than {limit // MB} MB"}).encode()
    await send({
        "type": "http.response.start",
        "status": 413,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})
