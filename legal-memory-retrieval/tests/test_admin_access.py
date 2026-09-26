"""Access model through the HTTP API (plan §5, phase 1 gate).

Every scenario changes a real matter's access, checks what each person can
reach — matter page, document, search, Ask the Firm, calendar, counts — and
restores the original state afterwards. People and matters come from the DB.
"""
from __future__ import annotations

import pytest

from app.db.connection import connect
from tests.conftest import as_member


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    with connect() as conn:
        return list(conn.execute(sql, params).fetchall())


@pytest.fixture(scope="module")
def cast(seeded):
    """An open matter with a document, its lead, a staffed non-lead, and an outsider."""
    rows = _rows(
        """
        SELECT m.matter_id, m.matter_code, m.title,
               (SELECT d.document_id FROM documents d WHERE d.matter_id = m.matter_id ORDER BY d.document_id LIMIT 1) AS document_id,
               (SELECT mm.member_id FROM matter_members mm WHERE mm.matter_id = m.matter_id AND mm.role_on_matter = 'Lead' LIMIT 1) AS lead
        FROM matters m JOIN matter_access a USING (matter_id) JOIN permissions p USING (matter_id)
        WHERE a.mode = 'open' AND cardinality(p.denied_members) = 0
          AND EXISTS (SELECT 1 FROM documents d WHERE d.matter_id = m.matter_id)
        ORDER BY m.matter_id
        """
    )
    admins = {r["member_id"] for r in _rows("SELECT DISTINCT member_id FROM member_roles WHERE role_key IN ('firm_admin', 'risk_compliance')")}
    for r in rows:
        staff = [x["member_id"] for x in _rows(
            "SELECT member_id FROM matter_members WHERE matter_id = %s AND coalesce(role_on_matter, '') <> 'Lead' ORDER BY member_id", (r["matter_id"],))]
        outsiders = [x["member_id"] for x in _rows(
            "SELECT member_id FROM members WHERE member_id NOT IN (SELECT member_id FROM matter_members WHERE matter_id = %s) ORDER BY member_id",
            (r["matter_id"],))]
        staff = [s for s in staff if s not in admins]
        outsiders = [o for o in outsiders if o not in admins]
        if r["lead"] and r["lead"] not in admins and staff and outsiders and r["document_id"]:
            return {**r, "staff": staff[0], "outsider": outsiders[0], "admin": sorted(admins)[0]}
    pytest.skip("no open matter with a non-admin lead, staff and outsider")


@pytest.fixture
def restore(cast):
    """Snapshot the matter's access tables and restore them after the test."""
    mid = cast["matter_id"]
    with connect() as conn:
        access = conn.execute("SELECT mode, hide_existence FROM matter_access WHERE matter_id = %s", (mid,)).fetchone()
        grants = list(conn.execute("SELECT * FROM matter_grants WHERE matter_id = %s", (mid,)).fetchall())
    yield
    with connect() as conn:
        conn.execute("DELETE FROM matter_screens WHERE matter_id = %s", (mid,))
        conn.execute("DELETE FROM matter_grants WHERE matter_id = %s", (mid,))
        for g in grants:
            conn.execute(
                """INSERT INTO matter_grants (grant_id, matter_id, principal_type, principal_id, level, reason, expires_at, granted_by)
                   VALUES (%(grant_id)s, %(matter_id)s, %(principal_type)s, %(principal_id)s, %(level)s, %(reason)s, %(expires_at)s, %(granted_by)s)""",
                g,
            )
        conn.execute("DELETE FROM access_requests WHERE matter_id = %s", (mid,))
        conn.execute("UPDATE matter_access SET mode = %s, hide_existence = %s WHERE matter_id = %s",
                     (access["mode"], access["hide_existence"], mid))
        conn.commit()


def _can_open(client, member: str, cast) -> dict[str, bool]:
    h = as_member(member)
    mid, doc = cast["matter_id"], cast["document_id"]
    title = _rows("SELECT title FROM documents WHERE document_id = %s", (doc,))[0]["title"]
    search = client.post("/api/retrieval", json={"query": f"{cast['title']} {title}", "k": 20}, headers=h).json()
    hits = search.get("hits") or search.get("results") or []
    ask = client.post("/api/answers", json={"query": "explain this", "scope": {"type": "matter", "value": cast["matter_code"]}},
                      headers=h).json()
    tasks = client.get("/api/tasks", params={"matter_id": mid, "status": "all"}, headers=h).json()
    return {
        "matter": client.get(f"/api/matters/{mid}", headers=h).status_code == 200,
        "document": client.get(f"/api/documents/{doc}", headers=h).status_code == 200,
        "search": any(x.get("matter_id") == mid for x in hits),
        "ask": ask.get("reason") != "scope_not_found" and mid in ((ask.get("resolved_scope") or {}).get("matter_ids") or []),
        "calendar_ok": all(t.get("matter_id") == mid for t in tasks.get("items", [])),
    }


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    from app.km import answer as km_answer

    monkeypatch.setattr(km_answer, "_llm", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no llm in tests")))


# ── roles ────────────────────────────────────────────────────────────────────

def test_me_reports_roles_and_permissions(client, cast):
    admin = client.get("/api/access/me", headers=as_member(cast["admin"])).json()
    staff = client.get("/api/access/me", headers=as_member(cast["staff"])).json()
    assert "walls.manage" in admin["permissions"]
    assert "walls.manage" not in staff["permissions"] and "users.manage" not in staff["permissions"]


def test_fee_earner_cannot_change_roles_or_screen(client, cast, restore):
    h = as_member(cast["staff"])
    assert client.put(f"/api/admin/users/{cast['outsider']}/roles", json={"roles": ["firm_admin"]}, headers=h).status_code == 403
    assert client.post(f"/api/access/matters/{cast['matter_id']}/screens",
                       json={"member_id": cast["outsider"], "reason": "test"}, headers=h).status_code == 403
    assert client.get("/api/admin/users", headers=h).status_code == 403


def test_last_admin_cannot_remove_own_admin_role(client, cast):
    admins = _rows("SELECT member_id FROM member_roles WHERE role_key = 'firm_admin'")
    if len(admins) != 1:
        pytest.skip("guard applies only with a single firm admin")
    me = admins[0]["member_id"]
    r = client.put(f"/api/admin/users/{me}/roles", json={"roles": ["fee_earner"]}, headers=as_member(me))
    assert r.status_code == 409


# ── screens ──────────────────────────────────────────────────────────────────

def test_screen_blocks_everything_then_lifts(client, cast, restore):
    before = _can_open(client, cast["outsider"], cast)
    assert before["matter"] and before["document"], "firm-open matter should be visible before the screen"

    r = client.post(f"/api/access/matters/{cast['matter_id']}/screens",
                    json={"member_id": cast["outsider"], "reason": "Acted for the counterparty at a previous firm"},
                    headers=as_member(cast["admin"]))
    assert r.status_code == 201
    during = _can_open(client, cast["outsider"], cast)
    assert not any([during["matter"], during["document"], during["search"], during["ask"]]), during
    status = client.get(f"/api/access/matters/{cast['matter_id']}/status", headers=as_member(cast["outsider"]))
    assert status.status_code == 404, "a screened person must not learn the matter exists"

    assert client.delete(f"/api/access/matters/{cast['matter_id']}/screens/{cast['outsider']}",
                         headers=as_member(cast["admin"])).status_code == 204
    after = _can_open(client, cast["outsider"], cast)
    assert after["matter"] and after["document"]


def test_grant_to_screened_person_is_refused(client, cast, restore):
    admin = as_member(cast["admin"])
    client.post(f"/api/access/matters/{cast['matter_id']}/screens",
                json={"member_id": cast["outsider"], "reason": "conflict"}, headers=admin)
    r = client.post(f"/api/access/matters/{cast['matter_id']}/grants",
                    json={"principal_type": "member", "principal_id": cast["outsider"], "level": "read"}, headers=admin)
    assert r.status_code == 409


# ── modes, grants and teams ──────────────────────────────────────────────────

def test_team_mode_limits_to_staff_and_grants(client, cast, restore):
    lead = as_member(cast["lead"])
    r = client.put(f"/api/access/matters/{cast['matter_id']}", json={"mode": "team"}, headers=lead)
    assert r.status_code == 200, r.text
    assert _can_open(client, cast["staff"], cast)["matter"]
    assert not _can_open(client, cast["outsider"], cast)["matter"]

    # Grant a team the outsider belongs to → access through the team.
    team = client.post("/api/admin/teams", json={"name": f"Test team {cast['matter_id']}"}, headers=as_member(cast["admin"])).json()
    try:
        assert client.put(f"/api/admin/teams/{team['team_id']}/members/{cast['outsider']}", headers=as_member(cast["admin"])).status_code == 204
        g = client.post(f"/api/access/matters/{cast['matter_id']}/grants",
                        json={"principal_type": "team", "principal_id": team["team_id"], "level": "read", "reason": "test"},
                        headers=lead)
        assert g.status_code == 201, g.text
        assert _can_open(client, cast["outsider"], cast)["matter"]
        # Removing the person from the team removes their access.
        client.delete(f"/api/admin/teams/{team['team_id']}/members/{cast['outsider']}", headers=as_member(cast["admin"]))
        assert not _can_open(client, cast["outsider"], cast)["matter"]
        # A team that still holds a grant cannot be deleted.
        assert client.delete(f"/api/admin/teams/{team['team_id']}", headers=as_member(cast["admin"])).status_code == 409
        client.delete(f"/api/access/matters/{cast['matter_id']}/grants/{g.json()['grant_id']}", headers=lead)
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM matter_grants WHERE principal_type = 'team' AND principal_id = %s", (team["team_id"],))
            conn.execute("DELETE FROM teams WHERE team_id = %s", (team["team_id"],))
            conn.commit()


def test_stale_mode_update_is_rejected(client, cast, restore):
    lead = as_member(cast["lead"])
    current = client.get(f"/api/access/matters/{cast['matter_id']}", headers=lead).json()
    ok = client.put(f"/api/access/matters/{cast['matter_id']}", json={"mode": "team", "row_version": current["row_version"]}, headers=lead)
    assert ok.status_code == 200
    stale = client.put(f"/api/access/matters/{cast['matter_id']}", json={"mode": "open", "row_version": current["row_version"]}, headers=lead)
    assert stale.status_code == 409


def test_staff_cannot_manage_access(client, cast, restore):
    r = client.put(f"/api/access/matters/{cast['matter_id']}", json={"mode": "restricted"}, headers=as_member(cast["staff"]))
    assert r.status_code == 403


# ── requests ─────────────────────────────────────────────────────────────────

def test_access_request_flow(client, cast, restore):
    lead, outsider = as_member(cast["lead"]), as_member(cast["outsider"])
    client.put(f"/api/access/matters/{cast['matter_id']}", json={"mode": "team", "hide_existence": False}, headers=lead)
    status = client.get(f"/api/access/matters/{cast['matter_id']}/status", headers=outsider).json()
    assert status["level"] == "none" and status["can_request"]

    req = client.post(f"/api/access/matters/{cast['matter_id']}/requests", json={"reason": "Covering the hearing next week"}, headers=outsider)
    assert req.status_code == 201, req.text
    dup = client.post(f"/api/access/matters/{cast['matter_id']}/requests", json={"reason": "again"}, headers=outsider)
    assert dup.status_code == 409

    queue = client.get("/api/access/requests", params={"scope": "to_decide"}, headers=lead).json()["items"]
    assert any(r["request_id"] == req.json()["request_id"] for r in queue)
    assert client.post(f"/api/access/requests/{req.json()['request_id']}/decision", json={"approve": True},
                       headers=outsider).status_code == 403, "requester cannot approve their own request"
    d = client.post(f"/api/access/requests/{req.json()['request_id']}/decision", json={"approve": True, "note": "ok"}, headers=lead)
    assert d.status_code == 200 and d.json()["status"] == "approved"
    assert _can_open(client, cast["outsider"], cast)["matter"]


def test_hidden_matter_is_indistinguishable_from_missing(client, cast, restore):
    lead, outsider = as_member(cast["lead"]), as_member(cast["outsider"])
    client.put(f"/api/access/matters/{cast['matter_id']}", json={"mode": "restricted", "hide_existence": True}, headers=lead)
    hidden = client.get(f"/api/access/matters/{cast['matter_id']}/status", headers=outsider)
    missing = client.get("/api/access/matters/MTR-0000-99999/status", headers=outsider)
    assert hidden.status_code == missing.status_code == 404
    assert client.post(f"/api/access/matters/{cast['matter_id']}/requests", json={"reason": "please"}, headers=outsider).status_code == 404
    # Restricted is grants-only, but whoever restricts the matter keeps a manage grant.
    assert client.get(f"/api/access/matters/{cast['matter_id']}", headers=lead).status_code == 200
    assert not _can_open(client, cast["staff"], cast)["matter"], "staffing alone does not pass a wall"


def test_access_changes_are_audited(client, cast, restore):
    lead = as_member(cast["lead"])
    client.put(f"/api/access/matters/{cast['matter_id']}", json={"mode": "team"}, headers=lead)
    rows = _rows(
        "SELECT action FROM audit_events WHERE matter_id = %s AND action = 'access.mode' ORDER BY seq DESC LIMIT 1",
        (cast["matter_id"],),
    )
    assert rows and rows[0]["action"] == "access.mode"


def test_dev_header_trust_is_loopback_only():
    """With auth off, a non-local client must not be able to claim a member id."""
    from fastapi.testclient import TestClient

    from app.api.main import app

    remote = TestClient(app, client=("203.0.113.9", 50000))
    assert remote.get("/api/matters", headers=as_member("MEM-00001")).status_code == 401
    local = TestClient(app, client=("127.0.0.1", 50000))
    assert local.get("/api/matters", headers=as_member("MEM-00001")).status_code == 200
