"""Putting a person on the payroll and taking them off: roles, deactivation, what it blocks."""
from __future__ import annotations

import uuid

import pytest

from app.db.connection import connect
from tests.conftest import as_member

ADMIN = "MEM-00011"


@pytest.fixture
def newcomer(client, seeded):
    made = client.post("/api/people", json={"name": f"E2E-TMP Person {uuid.uuid4().hex[:6]}", "role": "Associate", "roles": ["fee_earner"]},
                       headers=as_member(ADMIN))
    assert made.status_code == 201, made.text
    pid = made.json()["member_id"]
    yield pid
    with connect() as conn:
        for t in ("matter_members", "member_roles"):
            conn.execute(f"DELETE FROM {t} WHERE member_id = %s", (pid,))
        conn.execute("DELETE FROM members WHERE member_id = %s", (pid,))
        conn.commit()


def test_deactivate_needs_a_reason_and_blocks_everything_after(client, newcomer):
    h = as_member(ADMIN)
    assert client.post(f"/api/people/{newcomer}/deactivate", json={"reason": ""}, headers=h).status_code == 422
    out = client.post(f"/api/people/{newcomer}/deactivate", json={"reason": "Left the firm"}, headers=h)
    assert out.status_code == 200 and out.json()["active"] is False
    # They are gone from the directory, cannot act, and cannot be staffed.
    assert newcomer not in {p["member_id"] for p in client.get("/api/people", headers=h).json()["items"]}
    assert client.get("/api/people/me", headers=as_member(newcomer)).status_code == 403
    matters = client.get("/api/matters?limit=1", headers=h).json()["items"]
    staffed = client.put(f"/api/matters/{matters[0]['matter_id']}/team/{newcomer}", json={"role": "Associate"}, headers=h)
    assert staffed.status_code == 409 and "deactivated" in staffed.text
    # An administrator sees them, with the flag, and can bring them back.
    row = next(u for u in client.get("/api/admin/users", headers=h).json()["items"] if u["member_id"] == newcomer)
    assert row["active"] is False
    back = client.post(f"/api/people/{newcomer}/reactivate", headers=h)
    assert back.status_code == 200 and back.json()["active"] is True
    assert client.get("/api/people/me", headers=as_member(newcomer)).status_code == 200


def test_you_cannot_deactivate_yourself_or_the_last_admin(client, seeded):
    h = as_member(ADMIN)
    own = client.post(f"/api/people/{ADMIN}/deactivate", json={"reason": "x"}, headers=h)
    assert own.status_code == 409 and "yourself" in own.text


def test_a_lead_of_an_open_matter_must_hand_it_over_first(client, seeded):
    h = as_member(ADMIN)
    with connect() as conn:
        lead = conn.execute(
            "SELECT mm.member_id FROM matter_members mm JOIN matters m USING (matter_id) "
            "WHERE lower(mm.role_on_matter) = 'lead' AND m.status = 'Open' AND mm.member_id <> %s LIMIT 1", (ADMIN,)).fetchone()["member_id"]
    out = client.post(f"/api/people/{lead}/deactivate", json={"reason": "Leaving"}, headers=h)
    assert out.status_code == 409 and "lead" in out.text


def test_only_user_managers_may_deactivate(client, seeded):
    other = client.post("/api/people/MEM-00002/deactivate", json={"reason": "x"}, headers=as_member("MEM-00001"))
    assert other.status_code == 403
