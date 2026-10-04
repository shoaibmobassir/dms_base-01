"""Editing a client, its notes, and putting it on hold or making it inactive."""
from __future__ import annotations

import uuid

import pytest

from app.db.connection import connect
from tests.conftest import as_member

PARTNER = "MEM-00001"


@pytest.fixture
def new_client(client, seeded):
    name = f"E2E-TMP Client {uuid.uuid4().hex[:8]}"
    h = as_member(PARTNER)
    check = client.post("/api/conflicts/check", json={"names": [name], "purpose": "test"}, headers=h)
    assert check.status_code == 201, check.text
    made = client.post("/api/clients", json={"name": name, "check_id": check.json()["check_id"], "industry": "Energy"}, headers=h)
    assert made.status_code == 201, made.text
    cid = made.json()["client_id"]
    yield cid, name
    with connect() as conn:
        conn.execute("DELETE FROM matters WHERE client_id = %s", (cid,))
        conn.execute("DELETE FROM clients WHERE client_id = %s", (cid,))
        conn.execute("DELETE FROM conflict_checks WHERE check_id = %s", (check.json()["check_id"],))
        conn.commit()


def test_edit_details_hold_and_inactive(client, new_client):
    cid, name = new_client
    h = as_member(PARTNER)
    out = client.patch(f"/api/clients/{cid}", json={"industry": "Renewable energy", "headquarters": "Mumbai"}, headers=h)
    assert out.status_code == 200 and out.json()["industry"] == "Renewable energy"
    assert client.patch(f"/api/clients/{cid}", json={"status": "on_hold"}, headers=h).json()["status"] == "on_hold"
    assert client.patch(f"/api/clients/{cid}", json={"status": "inactive"}, headers=h).json()["status"] == "inactive"
    assert client.patch(f"/api/clients/{cid}", json={"status": "prospective"}, headers=h).status_code == 422


def test_an_inactive_client_cannot_have_open_matters(client, new_client):
    cid, _ = new_client
    h = as_member(PARTNER)
    m = client.post("/api/matters", json={"title": f"E2E-TMP m {uuid.uuid4().hex[:6]}", "client_id": cid, "practice_area": "Corporate"}, headers=h)
    assert m.status_code == 201, m.text
    blocked = client.patch(f"/api/clients/{cid}", json={"status": "inactive"}, headers=h)
    assert blocked.status_code == 409 and "still open" in blocked.text
    client.post(f"/api/matters/{m.json()['matter_id']}/close", json={"outcome": "Done"}, headers=h)
    assert client.patch(f"/api/clients/{cid}", json={"status": "inactive"}, headers=h).status_code == 200


def test_a_name_cannot_be_taken_by_another_client(client, new_client):
    cid, _ = new_client
    other = client.get("/api/clients?limit=3", headers=as_member(PARTNER)).json()["items"][0]["name"]
    assert client.patch(f"/api/clients/{cid}", json={"name": other}, headers=as_member(PARTNER)).status_code == 409


def test_notes_are_added_by_partners_and_removed_by_their_author(client, new_client):
    cid, _ = new_client
    h = as_member(PARTNER)
    note = client.post(f"/api/clients/{cid}/notes", json={"kind": "prefers", "text": "Wants a call before any filing."}, headers=h)
    assert note.status_code == 201, note.text
    assert client.post(f"/api/clients/{cid}/notes", json={"kind": "bogus", "text": "x"}, headers=h).status_code == 422
    shown = client.get(f"/api/clients/{cid}", headers=h).json()
    assert any(n["text"] == "Wants a call before any filing." for n in shown["notes"])
    assert client.delete(f"/api/clients/{cid}/notes/{note.json()['note_id']}", headers=h).status_code == 204


def test_someone_without_standing_cannot_edit_or_note(client, new_client):
    cid, _ = new_client
    with connect() as conn:
        junior = conn.execute(
            "SELECT m.member_id FROM members m WHERE NOT EXISTS (SELECT 1 FROM member_roles r JOIN role_permissions p USING (role_key) "
            "WHERE r.member_id = m.member_id AND p.permission = 'clients.create') AND m.member_id <> %s LIMIT 1", (PARTNER,)).fetchone()["member_id"]
    h = as_member(junior)
    assert client.patch(f"/api/clients/{cid}", json={"industry": "x"}, headers=h).status_code == 403
    assert client.post(f"/api/clients/{cid}/notes", json={"kind": "avoid", "text": "x"}, headers=h).status_code == 403
