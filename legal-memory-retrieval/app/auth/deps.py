from __future__ import annotations

import hashlib
import os

from fastapi import Header, HTTPException, status

from app.config import settings

# When AUTH_ENABLED=false (default for local dev), auth is bypassed.
_AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _load_keystore() -> dict[str, str]:
    """Load {hashed_key: member_id} from DB at request time (simple, no caching needed at this scale)."""
    from app.db.connection import connect

    try:
        with connect() as conn:
            rows = conn.execute("SELECT member_id, key_hash FROM api_keys").fetchall()
            return {r["key_hash"]: r["member_id"] for r in rows}
    except Exception:
        return {}


def resolve_member(
    x_api_key: str | None = Header(default=None),
    x_member_id: str | None = Header(default=None),
) -> str | None:
    """
    Resolve the calling member from request headers.

    When AUTH_ENABLED=false: trusts X-Member-Id header directly (dev mode).
    When AUTH_ENABLED=true:  validates X-Api-Key, returns the member it belongs to.
                             X-Member-Id must match the key's member or be omitted.
    """
    if not _AUTH_ENABLED:
        return x_member_id  # dev mode: trust header, None = admin/anonymous

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Api-Key header required",
        )

    keystore = _load_keystore()
    hashed = _hash_key(x_api_key)
    member_id = keystore.get(hashed)

    if member_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    # If the caller also supplied an explicit member override, it must match the key.
    if x_member_id and x_member_id != member_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="X-Member-Id does not match API key identity",
        )

    return member_id
