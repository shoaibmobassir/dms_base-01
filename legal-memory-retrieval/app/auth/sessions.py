"""Browser sessions: opaque random tokens in an HttpOnly cookie, hashes in Postgres.

A session has an absolute lifetime and an idle timeout, and can be revoked (sign-out
or an administrator deprovisioning a member). State-changing requests must echo the
session's CSRF token in ``X-CSRF-Token``; the token is readable by the SPA from a
separate, non-HttpOnly cookie (double submit), and verified against the stored hash.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Response

from app.config import settings
from app.db.connection import connect

SESSION_COOKIE = "precentis_session"
CSRF_COOKIE = "precentis_csrf"
_TOUCH_EVERY = timedelta(minutes=1)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass
class Session:
    member_id: str
    csrf_hash: str


def create(response: Response, member_id: str, *, subject: str | None, ip: str | None, user_agent: str | None) -> None:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions (session_hash, member_id, csrf_hash, idp_subject, expires_at, ip, user_agent)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (_sha(token), member_id, _sha(csrf), subject, now + timedelta(hours=settings.session_ttl_hours),
             ip, (user_agent or "")[:300]),
        )
        conn.commit()
    max_age = settings.session_ttl_hours * 3600
    secure = settings.session_cookie_secure
    # Lax (not Strict): the IdP redirect back to /api/auth/callback is a cross-site
    # top-level navigation and must carry the cookie on the following SPA load.
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=secure, samesite="lax", path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=secure, samesite="lax", path="/")


def load(token: str | None) -> Session | None:
    """The live session for a cookie value, or None (unknown, expired, idle, revoked)."""
    if not token:
        return None
    now = datetime.now(UTC)
    with connect() as conn:
        row = conn.execute(
            """
            SELECT member_id, csrf_hash, last_seen_at FROM auth_sessions
            WHERE session_hash = %s AND revoked_at IS NULL AND expires_at > %s
              AND last_seen_at > %s
            """,
            (_sha(token), now, now - timedelta(minutes=settings.session_idle_minutes)),
        ).fetchone()
        if row is None:
            return None
        if now - row["last_seen_at"] > _TOUCH_EVERY:
            conn.execute("UPDATE auth_sessions SET last_seen_at = %s WHERE session_hash = %s", (now, _sha(token)))
            conn.commit()
    return Session(member_id=row["member_id"], csrf_hash=row["csrf_hash"])


def csrf_ok(session: Session, header_value: str | None) -> bool:
    return bool(header_value) and hmac.compare_digest(_sha(header_value), session.csrf_hash)


def revoke(token: str | None) -> str | None:
    if not token:
        return None
    with connect() as conn:
        row = conn.execute(
            "UPDATE auth_sessions SET revoked_at = now() WHERE session_hash = %s AND revoked_at IS NULL RETURNING member_id",
            (_sha(token),),
        ).fetchone()
        conn.commit()
    return row["member_id"] if row else None


def revoke_all(member_id: str) -> int:
    with connect() as conn:
        n = conn.execute(
            "UPDATE auth_sessions SET revoked_at = now() WHERE member_id = %s AND revoked_at IS NULL", (member_id,)
        ).rowcount
        conn.commit()
    return n


def clear_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
