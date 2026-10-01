"""Firm sign-in with OpenID Connect (authorization code + PKCE, confidential client).

Works with any standards-compliant IdP (Microsoft Entra ID, Okta, Google Workspace).
The IdP's discovery document and signing keys are fetched and cached; ID tokens are
verified for signature, issuer, audience, expiry and nonce, and the member is matched
by *verified* email. MFA and conditional access are the IdP's job.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from jose import jwt
from jose.exceptions import JWTError

from app.config import settings
from app.db.connection import connect

LOGIN_TTL = timedelta(minutes=10)
_CACHE_TTL = 3600
_cache: dict[str, tuple[float, Any]] = {}


class OIDCError(Exception):
    """Sign-in failed; the message is safe to log, not to show verbatim to users."""


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# ── HTTP (patched in tests) ───────────────────────────────────────────────────


def _get_json(url: str) -> dict:
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _post_form(url: str, data: dict[str, str]) -> dict:
    resp = httpx.post(url, data=data, timeout=10, headers={"Accept": "application/json"})
    if resp.status_code >= 400:
        raise OIDCError(f"token endpoint returned {resp.status_code}")
    return resp.json()


def _cached(key: str, loader) -> Any:
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    value = loader()
    _cache[key] = (time.time() + _CACHE_TTL, value)
    return value


def discovery() -> dict:
    issuer = settings.oidc_issuer.rstrip("/")
    return _cached(f"disc:{issuer}", lambda: _get_json(f"{issuer}/.well-known/openid-configuration"))


def _jwks(force: bool = False) -> dict:
    uri = discovery()["jwks_uri"]
    if force:
        _cache.pop(f"jwks:{uri}", None)
    return _cached(f"jwks:{uri}", lambda: _get_json(uri))


# ── Login flow ────────────────────────────────────────────────────────────────


def _safe_next(next_path: str | None) -> str:
    # Only same-site SPA paths: never an absolute URL (open-redirect) or protocol-relative.
    if next_path and next_path.startswith("/ui") and not next_path.startswith("//") and "\\" not in next_path:
        return next_path
    return "/ui/"


def begin_login(next_path: str | None) -> str:
    """Create a single-use login request; return the IdP authorization URL."""
    if not settings.oidc_enabled:
        raise OIDCError("OIDC is not configured")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    with connect() as conn:
        conn.execute("DELETE FROM oidc_login_requests WHERE expires_at < now()")
        conn.execute(
            """
            INSERT INTO oidc_login_requests (state_hash, code_verifier, nonce, next_path, expires_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (_sha(state), verifier, nonce, _safe_next(next_path), datetime.now(UTC) + LOGIN_TTL),
        )
        conn.commit()
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_uri,
        "scope": settings.oidc_scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{discovery()['authorization_endpoint']}?{urlencode(params)}"


@dataclass
class SignedIn:
    member_id: str
    email: str
    subject: str
    next_path: str


def complete_login(code: str, state: str) -> SignedIn:
    """Exchange the code, verify the ID token, and map it to a member."""
    with connect() as conn:
        row = conn.execute(
            "DELETE FROM oidc_login_requests WHERE state_hash = %s AND expires_at > now() RETURNING *",
            (_sha(state),),
        ).fetchone()
        conn.commit()
    if row is None:
        raise OIDCError("unknown or expired login state")

    tokens = _post_form(discovery()["token_endpoint"], {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.oidc_redirect_uri,
        "client_id": settings.oidc_client_id,
        "client_secret": settings.oidc_client_secret,
        "code_verifier": row["code_verifier"],
    })
    id_token = tokens.get("id_token")
    if not id_token:
        raise OIDCError("no id_token in token response")
    claims = verify_id_token(id_token, row["nonce"])

    email = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    # Entra ID omits email_verified for work accounts; its emails are tenant-managed.
    verified = claims.get("email_verified", "login.microsoftonline.com" in settings.oidc_issuer)
    if not email or verified is False:
        raise OIDCError("id_token has no verified email")
    with connect() as conn:
        member = conn.execute("SELECT member_id FROM members WHERE lower(email) = %s", (email,)).fetchone()
    if member is None:
        raise OIDCError(f"no member with email {email}")
    return SignedIn(member_id=member["member_id"], email=email, subject=str(claims["sub"]), next_path=row["next_path"])


def verify_id_token(id_token: str, nonce: str) -> dict:
    try:
        header = jwt.get_unverified_header(id_token)
    except JWTError as exc:
        raise OIDCError("malformed id_token") from exc
    if header.get("alg") in (None, "none") or header.get("alg", "").startswith("HS"):
        raise OIDCError("id_token must be signed with an asymmetric key")

    def key_for(jwks: dict) -> dict | None:
        return next((k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")), None)

    key = key_for(_jwks()) or key_for(_jwks(force=True))  # key rotation
    if key is None:
        raise OIDCError("id_token signed with an unknown key")
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=[header["alg"]],
            audience=settings.oidc_client_id,
            issuer=discovery().get("issuer", settings.oidc_issuer),
            options={"verify_at_hash": False},
        )
    except JWTError as exc:
        raise OIDCError(f"id_token rejected: {exc}") from exc
    if claims.get("nonce") != nonce:
        raise OIDCError("id_token nonce mismatch")
    return claims
