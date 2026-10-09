"""The firm's write layer (plan 17, P2): matters, staffing, timeline, arguments, related
matters, clients and conflict checks, people — plus the domain-event outbox behind live
updates.

Every write: checks access (``app.access``), validates, writes in one transaction with a
``domain_events`` row, commits, then records an audit event. Conflicting edits are refused
with 409 (``row_version``), never merged silently.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg

from app import access


class FirmError(Exception):
    def __init__(self, status: int, detail: str, extra: dict | None = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.extra = extra or {}


def db_today(conn) -> str:
    """Today's date as the database sees it (ISO). Access rules compare dates with the database's ``current_date``, so
    anything stored for them (a matter's start date, a closing date) must come from the same clock — not the app
    server's local date, which differs from UTC for hours each day in some time zones."""
    return one(conn, "SELECT current_date::text AS d")["d"]


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def one(conn, sql: str, params: Any = ()) -> dict | None:
    return conn.execute(sql, params).fetchone()


def emit(conn, topic: str, entity_type: str, entity_id: str, *, actor: str | None, matter_id: str | None = None,
         document_id: str | None = None, payload: dict | None = None) -> None:
    """Record a domain event in the caller's transaction (the live-update stream reads these)."""
    conn.execute(
        """INSERT INTO domain_events (topic, entity_type, entity_id, matter_id, document_id, actor, payload)
           VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)""",
        (topic, entity_type, entity_id, matter_id, document_id, actor, json.dumps(payload or {}, default=str)),
    )


def guard(fn):
    """Turn access errors and rejected values into FirmErrors so routers map one error type."""
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except access.AccessError as exc:
            raise FirmError(exc.status, exc.detail) from exc
        except psycopg.errors.CheckViolation as exc:
            # A value the database refuses is the caller's mistake (422), not a server fault (500).
            raise FirmError(422, "That value is not allowed here") from exc
    wrapped.__name__ = fn.__name__
    wrapped.__doc__ = fn.__doc__
    return wrapped


def require_level(conn, member_id: str | None, matter_id: str, level: str) -> str:
    if one(conn, "SELECT 1 AS ok FROM matters WHERE matter_id = %s", (matter_id,)) is None:
        raise FirmError(404, "Matter not found or access denied")
    return access.require_matter_level(conn, member_id, matter_id, level)


def check_version(current: int, given: int | None, what: str) -> None:
    if given is not None and given != current:
        raise FirmError(409, f"The {what} changed since you loaded it; reload and try again", {"row_version": current})


def refresh_matter_profile(matter_id: str) -> None:
    """Matter text changed: rebuild its search profile in the background."""
    from app.documents.privacy import _refresh_matter_profile

    _refresh_matter_profile(matter_id)
