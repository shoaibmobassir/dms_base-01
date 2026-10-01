"""Security headers for every response, with a Content-Security-Policy per surface.

Inline scripts are allowed only by hash, computed from the HTML files that are
actually served, so a rebuilt SPA never needs a manual CSP edit.
"""
from __future__ import annotations

import base64
import hashlib
import re
from functools import lru_cache
from pathlib import Path

from app.config import settings

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)

# Office hosts that embed add-in task panes.
OFFICE_FRAME_ANCESTORS = (
    "https://*.office.com https://*.office365.com https://*.officeapps.live.com "
    "https://*.microsoft.com https://*.sharepoint.com"
)

BASE_HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"referrer-policy": b"strict-origin-when-cross-origin",
    b"cross-origin-opener-policy": b"same-origin",
    # microphone for voice input (UI roadmap Q5); everything else off
    b"permissions-policy": b"camera=(), geolocation=(), payment=(), usb=(), microphone=(self)",
}


@lru_cache(maxsize=8)
def _script_hashes(path: str, mtime: float) -> str:
    html = Path(path).read_text(encoding="utf-8")
    hashes = []
    for body in _INLINE_SCRIPT.findall(html):
        digest = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode()
        hashes.append(f"'sha256-{digest}'")
    return " ".join(hashes)


def _hashes_for(filename: str) -> str:
    path = STATIC_DIR / filename
    if not path.is_file():
        return ""
    return _script_hashes(str(path), path.stat().st_mtime)


def csp_for(path: str) -> str:
    if path.startswith("/ui/word-taskpane.html"):
        return (
            "default-src 'self'; "
            f"script-src 'self' https://appsforoffice.microsoft.com {_hashes_for('word-taskpane.html')}; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; "
            f"frame-ancestors 'self' {OFFICE_FRAME_ANCESTORS}"
        )
    if path == "/ui" or path.startswith("/ui/"):
        # style 'unsafe-inline': React/Radix set style attributes; scripts stay hash-only.
        return (
            "default-src 'self'; "
            f"script-src 'self' {_hashes_for('index.html')}; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
            "frame-ancestors 'none'"
        )
    if path.startswith(("/docs", "/redoc")):
        return ""  # dev-only Swagger UI loads from a CDN; disabled in production
    return "default-src 'none'; frame-ancestors 'none'"


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in BASE_HEADERS]
                headers += list(BASE_HEADERS.items())
                csp = csp_for(path)
                if csp:
                    headers.append((b"content-security-policy", csp.encode()))
                if settings.env == "production":
                    headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
