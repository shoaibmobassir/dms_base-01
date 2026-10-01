"""Mask credentials in log records before any handler writes them.

Covers bearer tokens, API keys, OIDC codes/tokens, passwords in connection URLs and
common secret-looking key=value pairs. Installed once at API/worker start.
"""
from __future__ import annotations

import logging
import re

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(x-api-key['\"]?\s*[:=]\s*['\"]?)[^\s'\",]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:api[_-]?key|secret|password|passwd|token|client_secret|code_verifier|id_token|access_token|refresh_token|session)['\"]?\s*[:=]\s*['\"]?)[^\s'\",&]+"), r"\1[REDACTED]"),
    (re.compile(r"([a-z][a-z0-9+.-]*://[^:/\s@]+:)[^@\s/]+@"), r"\1[REDACTED]@"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[REDACTED-JWT]"),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — never drop a log line because of formatting
            return True
        clean = redact(message)
        if clean != message:
            record.msg, record.args = clean, None
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def install() -> None:
    """Attach the filter to every root handler (and future ones via the root logger)."""
    root = logging.getLogger()
    if not any(isinstance(f, RedactingFilter) for f in root.filters):
        root.addFilter(RedactingFilter())
    for handler in root.handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())
