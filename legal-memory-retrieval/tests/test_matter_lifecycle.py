"""Closing (resolving) and reopening a matter."""
from __future__ import annotations

import uuid

from app.db.connection import connect
from tests.conftest import as_member

LEAD = "MEM-00001"


def _new_matter(client, title: str) -> str:
    clients = client.get("/api/clients?limit=5", headers=as_member(LEAD)).json()["items"]
    res = client.post("/api/matters", json={"title": title, "client_id": clients[0]["client_id"], "practice_area": "Corporate",
                                             "access_mode": "team"}, headers=as_member(LEAD))
    assert res.status_code == 201, res.text
    return res.json()["matter_id"]


def _cleanup(matter_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM matters WHERE matter_id = %s", (matter_id,))
        conn.commit()


def test_close_needs_an_outcome_and_handles_open_court_dates(client, seeded):
    mid = _new_matter(client, f"Lifecycle {uuid.uuid4()}")
    try:
        h = as_member(LEAD)
        dl = client.post("/api/calendar/deadlines", json={"title": "File reply", "kind": "filing", "matter_id": mid,
                                                           "due_date": "2030-01-15"}, headers=h)
        assert dl.status_code in (200, 201), dl.text
        check = client.get(f"/api/matters/{mid}/close-check", headers=h).json()
        assert check["status"] == "Open" and len(check["deadlines"]) == 1

        # No outcome: refused. An open court date: refused unless marked done in the same step.
        assert client.post(f"/api/matters/{mid}/close", json={"outcome": ""}, headers=h).status_code == 422
        blocked = client.post(f"/api/matters/{mid}/close", json={"outcome": "Settled"}, headers=h)
        assert blocked.status_code == 409 and "court date" in blocked.text

        done = client.post(f"/api/matters/{mid}/close", json={"outcome": "Settled on agreed terms", "resolve_deadlines": True}, headers=h)
        assert done.status_code == 200, done.text
        body = done.json()
        assert body["status"] == "Closed" and body["outcome"] == "Settled on agreed terms" and body["closed_date"]
        assert client.post(f"/api/matters/{mid}/close", json={"outcome": "x"}, headers=h).status_code == 409  # already closed
        with connect() as conn:
            assert conn.execute("SELECT status FROM court_deadlines WHERE matter_id = %s", (mid,)).fetchone()["status"] == "done"
    finally:
        _cleanup(mid)


def test_reopen_needs_a_reason_and_only_works_on_a_closed_matter(client, seeded):
    mid = _new_matter(client, f"Lifecycle {uuid.uuid4()}")
    try:
        h = as_member(LEAD)
        assert client.post(f"/api/matters/{mid}/reopen", json={"reason": "new evidence"}, headers=h).status_code == 409
        assert client.post(f"/api/matters/{mid}/close", json={"outcome": "Withdrawn"}, headers=h).status_code == 200
        assert client.post(f"/api/matters/{mid}/reopen", json={"reason": ""}, headers=h).status_code == 422
        out = client.post(f"/api/matters/{mid}/reopen", json={"reason": "Opposing party appealed"}, headers=h)
        assert out.status_code == 200 and out.json()["status"] == "Open" and not out.json()["closed_date"]
    finally:
        _cleanup(mid)


def test_a_member_without_manage_level_cannot_close(client, seeded):
    mid = _new_matter(client, f"Lifecycle {uuid.uuid4()}")
    try:
        with connect() as conn:
            outsider = conn.execute(
                "SELECT member_id FROM members WHERE member_id NOT IN (SELECT member_id FROM matter_members WHERE matter_id = %s) "
                "AND member_id <> %s LIMIT 1", (mid, LEAD)).fetchone()["member_id"]
        res = client.post(f"/api/matters/{mid}/close", json={"outcome": "Closed"}, headers=as_member(outsider))
        assert res.status_code in (403, 404)
    finally:
        _cleanup(mid)
