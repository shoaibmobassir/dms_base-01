"""Firm sign-in (production plan 08, step C) against a fake IdP.

A real RSA key signs real ID tokens; only the IdP's HTTP endpoints (discovery,
JWKS, token) are replaced. Covers the happy path, CSRF, sign-out, revocation,
idle timeout, and the ways an ID token or login can be forged or replayed.
"""
from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jose import jwk, jwt

from app.api.main import app
from app.auth import oidc
from app.config import settings
from app.db.connection import connect

ISSUER = "https://idp.test"
CLIENT_ID = "precentis-test"
MEMBER = "MEM-00001"


def _email_of(member_id: str) -> str:
    with connect() as conn:
        row = conn.execute("SELECT email FROM members WHERE member_id = %s", (member_id,)).fetchone()
    assert row and row["email"], f"{member_id} needs an email (seed_ci_minimal.py / corpus)"
    return row["email"]


def _keypair(kid: str):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = jwk.construct(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo), "RS256").to_dict()
    public.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return pem, public


PEM, PUBLIC_JWK = _keypair("k1")
OTHER_PEM, _ = _keypair("k1")  # same kid, different key → signature must fail


class FakeIdP:
    def __init__(self):
        self.claims_override: dict = {}
        self.sign_with = PEM
        self.alg = "RS256"
        self.kid = "k1"
        self.nonce: str | None = None

    def get_json(self, url: str) -> dict:
        if url.endswith("/.well-known/openid-configuration"):
            return {
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/jwks",
            }
        if url.endswith("/jwks"):
            return {"keys": [PUBLIC_JWK]}
        raise AssertionError(url)

    def post_form(self, url: str, data: dict) -> dict:
        assert url == f"{ISSUER}/token" and data["code_verifier"] and data["client_secret"] == "s3cret"
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT_ID, "sub": "idp-user-1", "email": _email_of(MEMBER), "email_verified": True,
                  "nonce": self.nonce, "iat": now, "exp": now + 300}
        claims.update(self.claims_override)
        key = self.sign_with if self.alg.startswith("RS") else "shared-secret"
        return {"id_token": jwt.encode(claims, key, algorithm=self.alg, headers={"kid": self.kid})}


@pytest.fixture
def idp(monkeypatch, seeded):
    fake = FakeIdP()
    oidc._cache.clear()
    monkeypatch.setattr(oidc, "_get_json", fake.get_json)
    monkeypatch.setattr(oidc, "_post_form", fake.post_form)
    for name, value in {
        "auth_enabled": True, "oidc_issuer": ISSUER, "oidc_client_id": CLIENT_ID, "oidc_client_secret": "s3cret",
        "oidc_redirect_uri": "http://testserver/api/auth/callback", "session_cookie_secure": False,
    }.items():
        monkeypatch.setattr(settings, name, value)
    yield fake
    oidc._cache.clear()


def _sign_in(idp: FakeIdP, next_path: str = "/ui/matters") -> tuple[TestClient, str]:
    browser = TestClient(app, follow_redirects=False)
    start = browser.get(f"/api/auth/login?next={next_path}")
    assert start.status_code == 302
    q = parse_qs(urlparse(start.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["client_id"] == [CLIENT_ID]
    idp.nonce = q["nonce"][0]
    done = browser.get(f"/api/auth/callback?code=abc&state={q['state'][0]}")
    return browser, done.headers["location"]


def test_sign_in_creates_http_only_session(idp):
    browser, location = _sign_in(idp)
    assert location == "/ui/matters"
    raw = browser.cookies
    assert raw.get("precentis_session") and raw.get("precentis_csrf")
    me = browser.get("/api/auth/session").json()["person"]
    assert me["member_id"] == "MEM-00001"
    assert browser.get("/api/matters?limit=1").status_code == 200


def test_session_cookie_flags(idp, monkeypatch):
    monkeypatch.setattr(settings, "session_cookie_secure", True)
    browser = TestClient(app, follow_redirects=False)
    q = parse_qs(urlparse(browser.get("/api/auth/login").headers["location"]).query)
    idp.nonce = q["nonce"][0]
    resp = browser.get(f"/api/auth/callback?code=abc&state={q['state'][0]}")
    session_cookie = next(h for h in resp.headers.get_list("set-cookie") if h.startswith("precentis_session="))
    assert "HttpOnly" in session_cookie and "Secure" in session_cookie and "SameSite=lax" in session_cookie


def test_writes_require_csrf(idp):
    browser, _ = _sign_in(idp)
    matter = browser.get("/api/matters?status=Open&limit=1").json()["items"][0]["matter_id"]
    assert browser.put(f"/api/matters/{matter}/pin").status_code == 403
    csrf = browser.cookies.get("precentis_csrf")
    assert browser.put(f"/api/matters/{matter}/pin", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert browser.put(f"/api/matters/{matter}/pin", headers={"X-CSRF-Token": "forged"}).status_code == 403
    browser.delete(f"/api/matters/{matter}/pin", headers={"X-CSRF-Token": csrf})


def test_member_header_cannot_override_session(idp):
    browser, _ = _sign_in(idp)
    assert browser.get("/api/matters?limit=1", headers={"X-Member-Id": "MEM-00016"}).status_code == 403


def test_sign_out_revokes(idp):
    browser, _ = _sign_in(idp)
    csrf = browser.cookies.get("precentis_csrf")
    assert browser.post("/api/auth/logout").status_code == 403  # CSRF required
    assert browser.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    browser.cookies.clear()
    assert browser.get("/api/matters?limit=1").status_code == 401


def test_stolen_cookie_dies_after_sign_out(idp):
    browser, _ = _sign_in(idp)
    token = browser.cookies.get("precentis_session")
    browser.post("/api/auth/logout", headers={"X-CSRF-Token": browser.cookies.get("precentis_csrf")})
    thief = TestClient(app)
    thief.cookies.set("precentis_session", token)
    assert thief.get("/api/matters?limit=1").status_code == 401


def test_admin_revokes_all_sessions(idp):
    browser, _ = _sign_in(idp)
    admin = TestClient(app)
    # dev-style admin call is impossible with auth on; use a key for the service/admin caller
    import hashlib
    import secrets

    raw = secrets.token_urlsafe(16)
    with connect() as conn:
        conn.execute("INSERT INTO api_keys (member_id, key_hash) VALUES ('MEM-00011', %s)", (hashlib.sha256(raw.encode()).hexdigest(),))
        conn.commit()
    try:
        assert admin.post("/api/auth/members/MEM-00001/revoke-sessions", headers={"X-Api-Key": raw}).json()["revoked"] >= 1
        assert browser.get("/api/matters?limit=1").status_code == 401
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM api_keys WHERE key_hash = %s", (hashlib.sha256(raw.encode()).hexdigest(),))
            conn.commit()


def test_idle_session_expires(idp):
    browser, _ = _sign_in(idp)
    token = browser.cookies.get("precentis_session")
    with connect() as conn:
        conn.execute(
            "UPDATE auth_sessions SET last_seen_at = now() - make_interval(mins => %s) WHERE session_hash = encode(sha256(%s::bytea), 'hex')",
            (settings.session_idle_minutes + 1, token.encode()),
        )
        conn.commit()
    assert browser.get("/api/matters?limit=1").status_code == 401


@pytest.mark.parametrize(
    "tamper",
    [
        {"claims_override": {"nonce": "wrong"}},
        {"claims_override": {"aud": "someone-else"}},
        {"claims_override": {"iss": "https://evil.test"}},
        {"claims_override": {"exp": int(time.time()) - 60}},
        {"claims_override": {"email_verified": False}},
        {"claims_override": {"email": "stranger@elsewhere.test"}},
        {"sign_with": OTHER_PEM},  # right kid, wrong key
        {"kid": "unknown"},
        {"alg": "HS256"},  # symmetric token must be refused
    ],
)
def test_bad_id_tokens_rejected(idp, tamper):
    for attr, value in tamper.items():
        setattr(idp, attr, value)
    browser, location = _sign_in(idp)
    assert location == "/ui/?signin=failed"
    assert browser.cookies.get("precentis_session") is None


def test_login_state_is_single_use(idp):
    browser = TestClient(app, follow_redirects=False)
    q = parse_qs(urlparse(browser.get("/api/auth/login").headers["location"]).query)
    idp.nonce = q["nonce"][0]
    first = browser.get(f"/api/auth/callback?code=abc&state={q['state'][0]}")
    replay = TestClient(app, follow_redirects=False).get(f"/api/auth/callback?code=abc&state={q['state'][0]}")
    assert first.headers["location"] != "/ui/?signin=failed"
    assert replay.headers["location"] == "/ui/?signin=failed"


@pytest.mark.parametrize("target", ["https://evil.test/", "//evil.test/x", "/api/matters", "/ui\\@evil.test"])
def test_no_open_redirect(idp, target):
    _, location = _sign_in(idp, next_path=target)
    assert location == "/ui/"


def test_production_requires_oidc_and_secure_cookies():
    from app.config import Settings

    problems = " ".join(Settings(allow_api_key_browser_login=True, session_cookie_secure=False).production_problems())
    assert "OIDC_ISSUER" in problems and "ALLOW_API_KEY_BROWSER_LOGIN" in problems and "SESSION_COOKIE_SECURE" in problems


def test_sign_in_audited(idp):
    with connect() as conn:
        before = conn.execute("SELECT COALESCE(max(seq),0) AS s FROM audit_events").fetchone()["s"]
    _sign_in(idp)
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM audit_events WHERE action = 'auth.sign_in' AND seq > %s ORDER BY seq DESC LIMIT 1", (before,)
        ).fetchone()
    assert row["member_id"] == "MEM-00001" and row["outcome"] == "success"
