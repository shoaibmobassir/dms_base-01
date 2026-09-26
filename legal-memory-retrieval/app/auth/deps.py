from __future__ import annotations

import hashlib
import logging

from fastapi import Header, HTTPException, Request, status

from app.config import settings

logger = logging.getLogger(__name__)


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _member_for_key(raw_key: str) -> str | None:
    """Return the member that owns ``raw_key``, or None if the key is unknown.

    Database failures propagate as 503: an outage must not look like a bad key.
    """
    from app.db.connection import connect

    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT member_id FROM api_keys WHERE key_hash = %s",
                (_hash_key(raw_key),),
            ).fetchone()
    except Exception as exc:
        logger.error("API key lookup failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication backend unavailable",
        ) from exc
    return row["member_id"] if row else None


def _audit_denied(reason: str, member_id: str | None = None) -> None:
    from app.audit import events as audit

    audit.record("auth.request", member_id=member_id, outcome="denied", detail={"reason": reason})


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def resolve_member(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_member_id: str | None = Header(default=None),
    x_csrf_token: str | None = Header(default=None),
) -> str | None:
    """
    Resolve the calling member.

    AUTH_ENABLED=false (development): trusts X-Member-Id; no header = anonymous admin.
    AUTH_ENABLED=true:
      1. Browser session cookie (firm OIDC sign-in). Writes must carry X-CSRF-Token.
      2. X-Api-Key (service callers).
      X-Member-Id is never an identity; if sent, it must match the resolved member.
    """
    if not settings.auth_enabled:
        return x_member_id  # dev mode: trust header, None = admin/anonymous

    from app.auth import sessions

    token = request.cookies.get(sessions.SESSION_COOKIE)
    if token and not x_api_key:
        session = sessions.load(token)
        if session is None:
            _audit_denied("expired or revoked session")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired — sign in again")
        if request.method not in SAFE_METHODS and not sessions.csrf_ok(session, x_csrf_token):
            _audit_denied("missing or invalid CSRF token", member_id=session.member_id)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing or invalid")
        member_id = session.member_id
    else:
        if not x_api_key:
            _audit_denied("no session or api key")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sign-in required",
            )
        member_id = _member_for_key(x_api_key)
        if member_id is None:
            _audit_denied("invalid api key")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

    # If the caller also supplied an explicit member override, it must match.
    if x_member_id and x_member_id != member_id:
        _audit_denied("member header does not match identity", member_id=member_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="X-Member-Id does not match the signed-in identity",
        )

    return member_id
