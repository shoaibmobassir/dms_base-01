"""Security regressions: static traversal, authentication, chat ownership, ethical wall.

Runs against the seeded demo database (see tests/conftest.py).
"""
from __future__ import annotations

import hashlib
import secrets

import pytest

from app.config import settings
from app.db.connection import connect
from conftest import Wall, as_member


# ── S1: static files ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/ui/..%2f.env", "/ui/%2e%2e/.env", "/ui/..%2f..%2fetc/passwd", "/ui/..%2fapp%2fconfig.py"])
def test_spa_handler_never_serves_files_outside_static(client, path):
    resp = client.get(path)
    assert "DATABASE_URL" not in resp.text
    assert "BaseSettings" not in resp.text
    assert "root:" not in resp.text


# ── S2/S3: authentication ─────────────────────────────────────────────────────


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)


@pytest.fixture
def api_key(seeded):
    raw = f"test-{secrets.token_urlsafe(16)}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    with connect() as conn:
        conn.execute("INSERT INTO api_keys (member_id, key_hash) VALUES ('MEM-00001', %s)", (digest,))
        conn.commit()
    yield raw
    with connect() as conn:
        conn.execute("DELETE FROM api_keys WHERE key_hash = %s", (digest,))
        conn.commit()


def test_auth_required_when_enabled(client, auth_on):
    assert client.get("/api/matters").status_code == 401
    # The dev header alone is not an identity once auth is on.
    assert client.get("/api/matters", headers=as_member("MEM-00001")).status_code == 401


def test_invalid_key_rejected(client, auth_on, seeded):
    assert client.get("/api/matters", headers={"X-Api-Key": "nope"}).status_code == 401


def test_valid_key_resolves_member(client, auth_on, api_key):
    resp = client.get("/api/people/me", headers={"X-Api-Key": api_key})
    assert resp.status_code == 200
    assert resp.json()["person"]["member_id"] == "MEM-00001"


def test_member_header_must_match_key(client, auth_on, api_key):
    resp = client.get("/api/matters", headers={"X-Api-Key": api_key, "X-Member-Id": "MEM-00002"})
    assert resp.status_code == 403


def test_auth_backend_outage_is_503_not_401(client, auth_on, monkeypatch):
    import app.db.connection as db

    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "connect", broken)
    assert client.get("/api/matters", headers={"X-Api-Key": "anything"}).status_code == 503


def test_system_info_reports_auth_mode(client, auth_on):
    # Public, so the SPA can decide between sign-in and persona picker.
    assert client.get("/api/system/info").json()["auth_enabled"] is True


# ── S7: CORS ──────────────────────────────────────────────────────────────────


def test_cors_does_not_reflect_arbitrary_origins(client):
    resp = client.get("/api/system/health", headers={"Origin": "https://evil.example"})
    assert resp.headers.get("access-control-allow-origin") not in ("*", "https://evil.example")


# ── S5: chat ownership ────────────────────────────────────────────────────────


@pytest.fixture
def session_of_member_1(client, seeded):
    s = client.post("/api/chat/sessions", json={}, headers=as_member("MEM-00001")).json()
    yield s
    client.delete(f"/api/chat/sessions/{s['id']}", headers=as_member("MEM-00001"))


def test_chat_session_owner_is_caller_not_body(client, seeded):
    s = client.post("/api/chat/sessions", json={"member_id": "MEM-00002"}, headers=as_member("MEM-00001")).json()
    try:
        assert s["member_id"] == "MEM-00001"
    finally:
        client.delete(f"/api/chat/sessions/{s['id']}", headers=as_member("MEM-00001"))


def test_chat_session_invisible_to_other_members(client, session_of_member_1):
    sid = session_of_member_1["id"]
    other = as_member("MEM-00002")
    assert client.get(f"/api/chat/sessions/{sid}", headers=other).status_code == 404
    assert client.patch(f"/api/chat/sessions/{sid}", json={"title": "x"}, headers=other).status_code == 404
    assert client.delete(f"/api/chat/sessions/{sid}", headers=other).status_code == 404
    assert client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "hi"}, headers=other).status_code == 404
    assert sid not in {s["id"] for s in client.get("/api/chat/sessions", headers=other).json()}
    # Still intact for the owner.
    assert client.get(f"/api/chat/sessions/{sid}", headers=as_member("MEM-00001")).status_code == 200


def test_chat_listing_ignores_member_query_param(client, session_of_member_1):
    resp = client.get("/api/chat/sessions?member_id=MEM-00001", headers=as_member("MEM-00002"))
    assert session_of_member_1["id"] not in {s["id"] for s in resp.json()}


# ── Ethical wall: a restricted matter is invisible outside its team ───────────


def _ids(rows, key="matter_id"):
    return {r[key] for r in rows}


def test_wall_matter_lists(client, walls: list[Wall]):
    for w in walls:
        out, ins = as_member(w.outsider), as_member(w.insider)
        assert w.matter_id not in _ids(client.get("/api/matters?limit=200", headers=out).json()["items"])
        assert w.matter_id in _ids(client.get("/api/matters?limit=200", headers=ins).json()["items"])


@pytest.mark.parametrize("suffix", ["", "/timeline", "/arguments", "/related", "/graph"])
def test_wall_matter_detail_endpoints(client, walls: list[Wall], suffix):
    for w in walls:
        assert client.get(f"/api/matters/{w.matter_id}{suffix}", headers=as_member(w.outsider)).status_code == 404
        assert client.get(f"/api/matters/{w.matter_id}{suffix}", headers=as_member(w.insider)).status_code == 200


@pytest.mark.parametrize("suffix", ["", "/text", "/versions", "/chunks"])
def test_wall_document_endpoints(client, walls: list[Wall], suffix):
    for w in walls:
        assert client.get(f"/api/documents/{w.document_id}{suffix}", headers=as_member(w.outsider)).status_code == 404
        assert client.get(f"/api/documents/{w.document_id}{suffix}", headers=as_member(w.insider)).status_code == 200


def test_wall_document_listing(client, walls: list[Wall]):
    for w in walls:
        resp = client.get(f"/api/documents?matter_id={w.matter_id}", headers=as_member(w.outsider)).json()
        assert resp["total"] == 0 and resp["items"] == []


def test_wall_arguments(client, walls: list[Wall]):
    for w in walls:
        rows = client.get("/api/knowledge/arguments?limit=100", headers=as_member(w.outsider)).json()["items"]
        assert w.matter_id not in _ids(rows)


def test_wall_client_detail(client, walls: list[Wall]):
    for w in walls:
        body = client.get(f"/api/clients/{w.client_id}", headers=as_member(w.outsider)).json()
        assert w.matter_id not in _ids(body["matters"])
        assert w.matter_id not in {n["source_matter_id"] for n in body["notes"]}
        rows = client.get(f"/api/clients/{w.client_id}/matters", headers=as_member(w.outsider)).json()["items"]
        assert w.matter_id not in _ids(rows)


def test_wall_person_detail(client, walls: list[Wall]):
    for w in walls:
        rows = client.get(f"/api/people/{w.insider}", headers=as_member(w.outsider)).json()["matters"]
        assert w.matter_id not in _ids(rows)


def test_wall_deadlines(client, walls: list[Wall]):
    for w in walls:
        rows = client.get("/api/tasks?status=all&limit=100", headers=as_member(w.outsider)).json()["items"]
        assert w.matter_id not in _ids(rows)
        rows = client.get(f"/api/tasks?status=all&matter_id={w.matter_id}", headers=as_member(w.outsider)).json()["items"]
        assert rows == []


def test_wall_search(client, walls: list[Wall]):
    for w in walls:
        results = client.get(f"/api/search?q={w.matter_code}", headers=as_member(w.outsider)).json()["results"]
        assert w.matter_id not in {r["id"] for r in results if r["kind"] == "matter"}
        assert w.matter_code not in {r["meta"] for r in results if r["kind"] == "document"}


def test_wall_home_counts_exclude_restricted(client, walls: list[Wall]):
    w = walls[0]
    everyone = client.get("/api/home/stats").json()["counts"]["matters"]  # dev anonymous = unrestricted
    outsider = client.get("/api/home/stats", headers=as_member(w.outsider)).json()["counts"]["matters"]
    assert outsider < everyone


def test_wall_retrieval(client, walls: list[Wall]):
    """Restricted chunks never enter an outsider's candidate set."""
    w = walls[0]
    with connect() as conn:  # query with the document's own words so any corpus matches
        chunk = conn.execute(
            "SELECT text FROM chunks WHERE document_id = %s AND NOT is_parent ORDER BY chunk_index LIMIT 1", (w.document_id,)
        ).fetchone()
    if not chunk:
        pytest.skip("restricted document has no indexed text")
    body = {"query": " ".join(chunk["text"].split()[:12]), "k": 20}
    out = client.post("/api/retrieval", json=body, headers=as_member(w.outsider)).json()
    ins = client.post("/api/retrieval", json=body, headers=as_member(w.insider)).json()
    hits_key = "hits" if "hits" in out else "results"
    assert w.matter_id not in {h.get("matter_id") for h in out[hits_key]}
    assert w.matter_id in {h.get("matter_id") for h in ins[hits_key]}


def test_wall_ingest_into_restricted_matter(client, walls: list[Wall]):
    w = walls[0]
    resp = client.post(
        "/api/documents/ingest",
        json={"title": "x", "matter_id": w.matter_id, "body": "x", "document_type": "Memo"},
        headers=as_member(w.outsider),
    )
    assert resp.status_code == 404


# ── Ingest path confinement ──────────────────────────────────────────────────


def test_ingest_job_rejects_paths_outside_allowed_roots(client, seeded):
    resp = client.post(
        "/api/documents/ingest/jobs",
        json={"source_root": "/etc", "manifest": "/etc/hosts", "run_immediately": False},
        headers=as_member("MEM-00001"),
    )
    assert resp.status_code == 400
    assert "INGEST_ALLOWED_ROOTS" in resp.json()["detail"]


# ── Plan 07: every router needs an identity; production config guard ────────


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/audit/health"),
        ("get", "/api/reviews/health"),
        ("get", "/api/tabular/health"),
        ("get", "/api/workflows/health"),
        ("get", "/api/drafting/health"),
        ("get", "/api/caselaw/health"),
        ("get", "/api/chat/models"),
        ("post", "/api/word/handoff/ticket"),
    ],
)
def test_routers_without_member_logic_still_require_auth(client, auth_on, method, path):
    if method == "post":
        resp = client.post(path, json={"member_id": "MEM-00001"})
    else:
        resp = client.get(path)
    assert resp.status_code == 401


def test_system_probes_stay_public(client, auth_on):
    assert client.get("/api/system/health").status_code == 200
    assert client.get("/api/system/firm").status_code == 200


def test_handoff_ticket_is_for_the_caller(client, seeded):
    from app.auth.handoff import get_auth_handoff_service

    ticket = client.post(
        "/api/word/handoff/ticket", json={"member_id": "MEM-00002"}, headers=as_member("MEM-00001")
    ).json()["ticket"]
    assert get_auth_handoff_service().exchange_ticket(ticket)["member_id"] == "MEM-00001"


def test_production_guard_flags_unsafe_settings():
    from app.config import Settings

    problems = Settings(env="production", auth_enabled=False, cors_origins="*").production_problems()
    text = " ".join(problems)
    for needle in ("AUTH_ENABLED", "CORS_ORIGINS", "SOURCES_TOKEN_ENCRYPTION_SECRET", "INGEST_ALLOWED_ROOTS", "DATABASE_URL"):
        assert needle in text

    safe = Settings(
        env="production",
        auth_enabled=True,
        cors_origins="https://dms.example",
        sources_token_encryption_secret="x" * 40,
        ingest_allowed_roots="/srv/ingest",
        database_url="postgresql://app:strong@db/legal_memory",
        malware_scanner="clamd",
        ingest_mode="queue",
        oidc_issuer="https://idp.example",
        oidc_client_id="precentis",
        oidc_redirect_uri="https://dms.example/api/auth/callback",
        allow_api_key_browser_login=False,
        session_cookie_secure=True,
    )
    assert safe.production_problems() == []


def test_production_guard_blocks_startup(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-c", "import app.api.main"],
        cwd=root,
        env={"PATH": "/usr/bin:/bin", "ENV": "production", "AUTH_ENABLED": "false", "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode != 0
    assert "Refusing to start" in proc.stderr


# ── Pins never grant access ───────────────────────────────────────────────────


def test_wall_pins(client, walls: list[Wall]):
    w = walls[0]
    assert client.put(f"/api/matters/{w.matter_id}/pin", headers=as_member(w.outsider)).status_code == 404
    # A pin made while inside the wall disappears if access is later lost.
    assert client.put(f"/api/matters/{w.matter_id}/pin", headers=as_member(w.insider)).status_code == 204
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO member_pins (member_id, matter_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (w.outsider, w.matter_id),
            )
            conn.commit()
        rows = client.get("/api/matters/pinned", headers=as_member(w.outsider)).json()["items"]
        assert w.matter_id not in {r["matter_id"] for r in rows}
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM member_pins WHERE matter_id = %s AND member_id IN (%s, %s)", (w.matter_id, w.insider, w.outsider))
            conn.commit()


def test_pins_require_identity(client, seeded):
    assert client.get("/api/matters/pinned").status_code == 401
