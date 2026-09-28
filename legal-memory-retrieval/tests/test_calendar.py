"""Calendar (plan 17, P3) through the HTTP API: scopes and visibility, events, court deadlines
with second-lawyer confirmation, and private ICS feeds."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.db.connection import connect
from tests.conftest import as_member
from tests.test_firm_writes import _new_matter, cast, cleanup  # noqa: F401 — fixtures

TAG = "CALTEST"
SOON = (date.today() + timedelta(days=10)).isoformat()
RANGE = {"from": date.today().isoformat(), "to": (date.today() + timedelta(days=60)).isoformat()}


@pytest.fixture(autouse=True)
def _clean_personal_events(cast):
    """Test events, and the partner's feed only if this test created it (never a real subscription)."""
    with connect() as conn:
        had_feed = conn.execute("SELECT 1 FROM calendar_feeds WHERE member_id = %s", (cast["partner"],)).fetchone() is not None
    yield
    with connect() as conn:
        conn.execute("DELETE FROM calendar_events WHERE title LIKE %s", (TAG + "%",))
        if not had_feed:
            conn.execute("DELETE FROM calendar_feeds WHERE member_id = %s", (cast["partner"],))
        conn.commit()


def _items(client, member, scope="mine", **params):
    r = client.get("/api/calendar", params={**RANGE, "scope": scope, **params}, headers=as_member(member))
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _event(client, member, **body):
    data = {"title": f"{TAG} {uuid.uuid4().hex[:4]}", "starts_at": f"{SOON}T09:00:00Z", **body}
    r = client.post("/api/calendar/events", json=data, headers=as_member(member))
    assert r.status_code == 201, r.text
    return r.json()


def test_personal_events_are_seen_by_owner_and_attendees_only(client, cast):
    ev = _event(client, cast["partner"], attendees=[cast["associate"]], kind="meeting")
    assert ev["end"] > ev["start"]  # an hour by default
    assert ev["id"] in {i["id"] for i in _items(client, cast["partner"])}
    assert ev["id"] in {i["id"] for i in _items(client, cast["associate"])}  # attendee: in their "mine"
    assert ev["id"] not in {i["id"] for i in _items(client, cast["outsider"], "firm")}
    # Only the organiser changes it; others who can see it get 403, others 404.
    assert client.patch(f"/api/calendar/events/{ev['id']}", json={"title": "x"}, headers=as_member(cast["associate"])).status_code == 403
    assert client.patch(f"/api/calendar/events/{ev['id']}", json={"title": "x"}, headers=as_member(cast["outsider"])).status_code == 404
    r = client.patch(f"/api/calendar/events/{ev['id']}", json={"title": f"{TAG} moved", "starts_at": f"{SOON}T14:00:00Z",
                                                               "row_version": ev["row_version"]}, headers=as_member(cast["partner"]))
    assert r.status_code == 200 and r.json()["start"].startswith(f"{SOON}T14:00")
    assert client.delete(f"/api/calendar/events/{ev['id']}", headers=as_member(cast["partner"])).status_code == 204


def test_matter_events_follow_the_matter_acl_and_scopes(client, cast, cleanup):
    m = _new_matter(client, cast, cleanup)  # team mode: partner (lead) + associate
    ev = _event(client, cast["partner"], matter_id=m["matter_id"], kind="internal")
    assert ev["id"] not in {i["id"] for i in _items(client, cast["outsider"], "firm")}
    # The associate did not organise or attend it: not "mine", but it is "my team" and "matter".
    assert ev["id"] not in {i["id"] for i in _items(client, cast["associate"], "mine")}
    assert ev["id"] in {i["id"] for i in _items(client, cast["associate"], "team")}
    assert ev["id"] in {i["id"] for i in _items(client, cast["associate"], "matter", matter_id=m["matter_id"])}
    assert client.get("/api/calendar", params={**RANGE, "scope": "matter", "matter_id": m["matter_id"]},
                      headers=as_member(cast["outsider"])).status_code == 404
    # Attendees must be able to see the matter.
    r = client.post("/api/calendar/events", json={"title": f"{TAG} x", "starts_at": f"{SOON}T09:00:00Z", "matter_id": m["matter_id"],
                                                  "attendees": [cast["outsider"]]}, headers=as_member(cast["partner"]))
    assert r.status_code == 422
    # The associate can edit the matter, so can edit its event.
    assert client.patch(f"/api/calendar/events/{ev['id']}", json={"location": "Room 4"}, headers=as_member(cast["associate"])).status_code == 200


def test_court_dates_need_a_second_lawyer(client, cast, cleanup):
    m = _new_matter(client, cast, cleanup)
    r = client.post("/api/calendar/deadlines", json={"matter_id": m["matter_id"], "title": "Written submissions", "kind": "filing",
                                                     "due_date": SOON}, headers=as_member(cast["partner"]))
    assert r.status_code == 201, r.text
    dl = r.json()
    assert dl["confirmed"] is False and dl["owner_id"] == cast["partner"]
    url = f"/api/calendar/deadlines/{dl['id']}/confirm"
    assert client.post(url, headers=as_member(cast["partner"])).status_code == 403   # entered and owns it
    assert client.post(url, headers=as_member(cast["outsider"])).status_code == 404  # cannot see the matter
    r = client.post(url, headers=as_member(cast["associate"]))
    assert r.status_code == 200 and r.json()["confirmed"] is True and r.json()["confirmed_by"]
    assert client.post(url, headers=as_member(cast["associate"])).status_code == 409
    # Moving the date makes it a new court date: it needs confirming again.
    r = client.patch(f"/api/calendar/deadlines/{dl['id']}", json={"due_date": (date.today() + timedelta(days=12)).isoformat()},
                     headers=as_member(cast["partner"]))
    assert r.json()["confirmed"] is False
    # Compliance dates are internal: no confirmation step.
    r = client.post("/api/calendar/deadlines", json={"matter_id": m["matter_id"], "title": "Board filing", "kind": "compliance",
                                                     "due_date": SOON}, headers=as_member(cast["partner"]))
    assert r.json()["confirmed"] is None
    assert client.post(f"/api/calendar/deadlines/{r.json()['id']}/confirm", headers=as_member(cast["associate"])).status_code == 422
    # Done.
    assert client.patch(f"/api/calendar/deadlines/{dl['id']}", json={"status": "done"}, headers=as_member(cast["partner"])).json()["status"] == "done"


def test_range_and_scope_are_validated(client, cast):
    h = as_member(cast["partner"])
    assert client.get("/api/calendar", params={"from": "2026-01-01", "to": "2028-01-01"}, headers=h).status_code == 422
    assert client.get("/api/calendar", params={"from": "2026-02-01", "to": "2026-01-01"}, headers=h).status_code == 422
    assert client.get("/api/calendar", params={**RANGE, "scope": "matter"}, headers=h).status_code == 422


def test_ics_feed(client, cast, cleanup):
    m = _new_matter(client, cast, cleanup, access_mode="restricted")
    client.post("/api/calendar/deadlines", json={"matter_id": m["matter_id"], "title": "Secret hearing", "kind": "hearing",
                                                 "due_date": SOON}, headers=as_member(cast["partner"]))
    _event(client, cast["partner"], detail="Line one\nLine two; with, punctuation " + "x" * 120)
    feed = client.post("/api/calendar/feed", json={}, headers=as_member(cast["partner"])).json()
    assert feed["url"].endswith(".ics") and len(feed["token"]) > 30
    r = client.get(f"/api/calendar-feed/{feed['token']}.ics")  # no headers: calendar apps cannot send them
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    body = r.text
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.rstrip().endswith("END:VCALENDAR")
    assert "Secret hearing" not in body and "[UNCONFIRMED] Restricted matter" in body
    assert "Line one\\nLine two\\; with\\, punctuation" in body.replace("\r\n ", "")
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))
    # Opting in shows restricted titles; rotating kills the old URL; revoking kills the feed.
    new = client.post("/api/calendar/feed", json={"show_restricted": True}, headers=as_member(cast["partner"])).json()
    assert client.get(f"/api/calendar-feed/{feed['token']}.ics").status_code == 404
    assert "Secret hearing" in client.get(f"/api/calendar-feed/{new['token']}.ics").text
    assert client.delete("/api/calendar/feed", headers=as_member(cast["partner"])).status_code == 204
    assert client.get(f"/api/calendar-feed/{new['token']}.ics").status_code == 404
    assert client.get("/api/calendar-feed/not-a-token.ics").status_code == 404
