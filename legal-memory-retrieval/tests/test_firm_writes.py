"""Write layer (plan 17, P2) through the HTTP API and the real database: matters, staffing,
timeline, arguments, related matters, conflict checks and client intake, people, the
live-update feed and Home "my work". Everything a test creates is removed afterwards.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app import access
from app.db.connection import connect
from tests.conftest import as_member

CLIENT = "CLI-00901"  # Acme Technologies (active)
_MATTER_TABLES = ("matter_links", "matter_events", "arguments", "matter_members", "matter_grants", "matter_screens",
                  "access_requests", "member_pins", "court_deadlines", "matter_profiles", "matter_access", "permissions")


def _rows(sql, params=()):
    with connect() as conn:
        return list(conn.execute(sql, params).fetchall())


@pytest.fixture(scope="module")
def cast(seeded):
    with connect() as conn:
        def holders(role):
            return [r["member_id"] for r in conn.execute("SELECT member_id FROM member_roles WHERE role_key = %s ORDER BY member_id", (role,))]
        partners = [m for m in holders("partner") if not access.has_permission(conn, m, "walls.manage")]
        earners = [m for m in holders("fee_earner") if not access.has_permission(conn, m, "matters.create")]
        risk = [m for m in holders("risk_compliance")]
        admins = [m for m in holders("firm_admin")]
    if len(partners) < 2 or len(earners) < 3 or not risk or not admins:
        pytest.skip("needs two partners, three fee earners, a risk officer and an admin")
    return {"partner": partners[0], "partner2": partners[1], "associate": earners[0], "outsider": earners[1],
            "other": earners[2], "risk": risk[0], "admin": admins[0]}


@pytest.fixture
def cleanup():
    made = {"matters": [], "clients": [], "checks": [], "members": []}
    yield made
    with connect() as conn:
        for mid in made["matters"]:
            for t in _MATTER_TABLES:
                col = "matter_id" if t != "matter_links" else "matter_id"
                conn.execute(f"DELETE FROM {t} WHERE {col} = %s", (mid,))
            conn.execute("DELETE FROM matter_links WHERE related_matter_id = %s", (mid,))
            conn.execute("DELETE FROM matters WHERE matter_id = %s", (mid,))
        for cid in made["clients"]:
            conn.execute("DELETE FROM clients WHERE client_id = %s", (cid,))
        for chk in made["checks"]:
            conn.execute("DELETE FROM conflict_checks WHERE check_id = %s", (chk,))
        for mem in made["members"]:
            conn.execute("DELETE FROM member_roles WHERE member_id = %s", (mem,))
            conn.execute("DELETE FROM members WHERE member_id = %s", (mem,))
        conn.commit()


def _new_matter(client, cast, cleanup, **extra):
    body = {"title": f"Test matter {uuid.uuid4().hex[:6]}", "client_id": CLIENT, "practice_area": "Corporate",
            "office": "Bengaluru", "team": [{"member_id": cast["associate"], "role": "Associate"}], **extra}
    r = client.post("/api/matters", json=body, headers=as_member(cast["partner"]))
    assert r.status_code == 201, r.text
    cleanup["matters"].append(r.json()["matter_id"])
    return r.json()


def _can_open(client, member, matter_id) -> bool:
    return client.get(f"/api/matters/{matter_id}", headers=as_member(member)).status_code == 200


# ── matters ──────────────────────────────────────────────────────────────────

def test_open_a_matter(client, cast, cleanup):
    assert client.post("/api/matters", headers=as_member(cast["associate"]), json={
        "title": "x", "client_id": CLIENT, "practice_area": "Corporate"}).status_code == 403
    m = _new_matter(client, cast, cleanup)
    assert m["access_mode"] == "team" and m["status"] == "Open" and m["matter_code"].startswith("CORP/BEN/")
    detail = client.get(f"/api/matters/{m['matter_id']}", headers=as_member(cast["partner"])).json()
    lead = [t for t in detail["team"] if t["role_on_matter"] == "Lead"]
    assert [t["member_id"] for t in lead] == [cast["partner"]] and detail["my_level"] == "manage"
    # Team mode: the team sees it, the rest of the firm does not.
    assert _can_open(client, cast["associate"], m["matter_id"])
    assert not _can_open(client, cast["outsider"], m["matter_id"])
    # Codes are unique.
    dup = client.post("/api/matters", headers=as_member(cast["partner"]), json={
        "title": "dup", "client_id": CLIENT, "practice_area": "Corporate", "matter_code": m["matter_code"]})
    assert dup.status_code == 409
    assert _rows("SELECT count(*) AS n FROM audit_events WHERE action = 'matter.create' AND object_id = %s", (m["matter_id"],))[0]["n"] == 1


def test_restricted_matter_keeps_its_team_inside_the_wall(client, cast, cleanup):
    m = _new_matter(client, cast, cleanup, access_mode="restricted")
    assert _can_open(client, cast["partner"], m["matter_id"]) and _can_open(client, cast["associate"], m["matter_id"])
    assert not _can_open(client, cast["outsider"], m["matter_id"])


def test_edit_and_close_a_matter(client, cast, cleanup):
    m = _new_matter(client, cast, cleanup)
    url = f"/api/matters/{m['matter_id']}"
    # Only managers edit; stale edits are refused.
    assert client.patch(url, json={"changes": {"title": "x"}}, headers=as_member(cast["associate"])).status_code == 403
    assert client.patch(url, json={"changes": {"title": "New title"}, "row_version": m["row_version"] + 3},
                        headers=as_member(cast["partner"])).status_code == 409
    r = client.patch(url, json={"changes": {"title": "New title", "facts": ["Signed 1 March"]}, "row_version": m["row_version"]},
                     headers=as_member(cast["partner"]))
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "New title" and r.json()["row_version"] == m["row_version"] + 1
    r = client.patch(url, json={"changes": {"status": "Closed", "outcome": "Settled"}}, headers=as_member(cast["partner"]))
    assert r.json()["status"] == "Closed" and r.json()["closed_date"] == date.today().isoformat()
    assert client.patch(url, json={"changes": {"matter_id": "hack"}}, headers=as_member(cast["partner"])).status_code == 422


# ── staffing ─────────────────────────────────────────────────────────────────

def test_staffing_dates_control_team_access(client, cast, cleanup):
    m = _new_matter(client, cast, cleanup)
    url = f"/api/matters/{m['matter_id']}/team/{cast['outsider']}"
    assert client.put(url, json={"role": "Junior"}, headers=as_member(cast["associate"])).status_code == 403
    assert client.put(url, json={"role": "Junior"}, headers=as_member(cast["partner"])).status_code == 200
    assert _can_open(client, cast["outsider"], m["matter_id"])
    # "Yesterday" by the database's clock, which is the one access rules use.
    ended = _rows("SELECT (current_date - 1)::text AS d")[0]["d"]
    r = client.put(url, json={"role": "Junior", "started_at": "2026-01-01", "ended_at": ended}, headers=as_member(cast["partner"]))
    assert r.status_code == 200
    assert not _can_open(client, cast["outsider"], m["matter_id"])
    assert any(t["member_id"] == cast["outsider"] and not t["active"] for t in r.json()["team"])
    # The matter always has a lead.
    lead_url = f"/api/matters/{m['matter_id']}/team/{cast['partner']}"
    assert client.put(lead_url, json={"role": "Associate"}, headers=as_member(cast["partner"])).status_code == 409
    assert client.delete(lead_url, headers=as_member(cast["partner"])).status_code == 409
    assert client.put(url, json={"role": "Nonsense"}, headers=as_member(cast["partner"])).status_code == 422
    assert client.delete(url, headers=as_member(cast["partner"])).status_code == 200


# ── timeline and arguments ───────────────────────────────────────────────────

def test_timeline_entries(client, cast, cleanup):
    m = _new_matter(client, cast, cleanup)
    base = f"/api/matters/{m['matter_id']}"
    assert client.post(f"{base}/events", json={"occurred_on": "2026-03-01", "title": "x"},
                       headers=as_member(cast["outsider"])).status_code == 404
    r = client.post(f"{base}/events", json={"occurred_on": "2026-03-01", "title": "Term sheet signed", "kind": "milestone"},
                    headers=as_member(cast["associate"]))
    assert r.status_code == 201, r.text
    ev = r.json()
    tl = client.get(f"{base}/timeline", headers=as_member(cast["associate"])).json()["timeline"]
    assert any(t.get("event_id") == ev["event_id"] and t["doc_type"] == "Milestone" for t in tl)
    patch = f"{base}/events/{ev['event_id']}"
    assert client.patch(patch, json={"title": "y", "row_version": 9}, headers=as_member(cast["associate"])).status_code == 409
    assert client.patch(patch, json={"title": "Term sheet signed by both", "row_version": 1},
                        headers=as_member(cast["associate"])).json()["title"] == "Term sheet signed by both"
    assert client.post(f"{base}/events", json={"occurred_on": "2026-03-01", "title": "t", "kind": "party"},
                       headers=as_member(cast["associate"])).status_code == 422
    assert client.delete(patch, headers=as_member(cast["associate"])).status_code == 204
    assert not any(t.get("event_id") == ev["event_id"] for t in client.get(f"{base}/timeline", headers=as_member(cast["associate"])).json()["timeline"])


def test_arguments(client, cast, cleanup):
    m = _new_matter(client, cast, cleanup)
    base = f"/api/matters/{m['matter_id']}/arguments"
    r = client.post(base, json={"issue": "Limitation", "position": "our client", "argument": "Time runs from discovery."},
                    headers=as_member(cast["associate"]))
    assert r.status_code == 201, r.text
    arg = r.json()
    assert arg["author_member_id"] == cast["associate"]
    listed = client.get(base, headers=as_member(cast["associate"])).json()
    items = listed.get("arguments") or listed.get("items") or []
    assert any(a["argument_id"] == arg["argument_id"] for a in items)
    assert client.post(base, json={"issue": "x", "argument": "y", "supporting_documents": ["DOC-00001"]},
                       headers=as_member(cast["associate"])).status_code == 422
    assert client.patch(f"{base}/{arg['argument_id']}", json={"outcome": "Accepted", "row_version": 1},
                        headers=as_member(cast["associate"])).json()["outcome"] == "Accepted"
    assert client.delete(f"{base}/{arg['argument_id']}", headers=as_member(cast["associate"])).status_code == 204


# ── related matters ──────────────────────────────────────────────────────────

def test_linking_needs_edit_on_both_and_respects_walls(client, cast, cleanup):
    a = _new_matter(client, cast, cleanup)
    b = _new_matter(client, cast, cleanup, access_mode="restricted")
    body = {"related_matter_id": b["matter_id"], "relation": "parallel_proceeding", "note": "Same facts"}
    # The associate can edit A but is not inside B's wall... they are on B's team, so give B a stranger-only check below.
    r = client.post(f"/api/matters/{a['matter_id']}/related", json=body, headers=as_member(cast["partner"]))
    assert r.status_code == 201, r.text
    rel_a = client.get(f"/api/matters/{a['matter_id']}/related", headers=as_member(cast["partner"])).json()["related"]
    assert rel_a[0]["matter_id"] == b["matter_id"] and rel_a[0]["manual"] and rel_a[0]["relation"] == "parallel_proceeding"
    rel_b = client.get(f"/api/matters/{b['matter_id']}/related", headers=as_member(cast["partner"])).json()["related"]
    assert any(x["matter_id"] == a["matter_id"] for x in rel_b)
    # Someone on A's team but outside B's wall never sees B through the link.
    client.put(f"/api/matters/{a['matter_id']}/team/{cast['other']}", json={"role": "Junior"}, headers=as_member(cast["partner"]))
    rel = client.get(f"/api/matters/{a['matter_id']}/related", headers=as_member(cast["other"])).json()["related"]
    assert b["matter_id"] not in {x["matter_id"] for x in rel}
    # ...and cannot create links into it.
    c = _new_matter(client, cast, cleanup)
    client.put(f"/api/matters/{c['matter_id']}/team/{cast['other']}", json={"role": "Junior"}, headers=as_member(cast["partner"]))
    assert client.post(f"/api/matters/{c['matter_id']}/related", json={"related_matter_id": b["matter_id"]},
                       headers=as_member(cast["other"])).status_code in (403, 404)
    assert client.delete(f"/api/matters/{a['matter_id']}/related/{b['matter_id']}", headers=as_member(cast["partner"])).status_code == 204


# ── conflicts and client intake ──────────────────────────────────────────────

def _check(client, member, names, cleanup):
    r = client.post("/api/conflicts/check", json={"names": names}, headers=as_member(member))
    if r.status_code == 201:
        cleanup["checks"].append(r.json()["check_id"])
    return r


def test_only_intake_roles_run_checks(client, cast, cleanup):
    assert _check(client, cast["associate"], ["Anyone Ltd"], cleanup).status_code == 403


def test_hits_on_walled_matters_are_redacted_for_the_requester(client, cast, cleanup):
    walled = _rows("""SELECT m.matter_id, m.opposing_party FROM matters m JOIN permissions p USING (matter_id)
                      WHERE p.restricted AND m.opposing_party ILIKE 'Vector Green%%'""")
    if not walled or access.can_see_matter(connect().__enter__(), cast["partner"], walled[0]["matter_id"]):
        pytest.skip("needs a walled matter the partner cannot see")
    r = _check(client, cast["partner"], ["Vector Green Sunshine"], cleanup)
    assert r.status_code == 201, r.text
    mine = r.json()
    adverse = [h for h in mine["results"] if h["kind"] == "adverse_party"]
    assert adverse and all(h.get("redacted") for h in adverse)
    assert walled[0]["matter_id"] not in str(mine)
    assert mine["status"] == "awaiting_risk"
    full = client.get(f"/api/conflicts/{mine['check_id']}", headers=as_member(cast["risk"])).json()
    assert any(h.get("matter_id") == walled[0]["matter_id"] for h in full["results"])
    # Another requester cannot read someone else's check.
    assert client.get(f"/api/conflicts/{mine['check_id']}", headers=as_member(cast["partner2"])).status_code == 404


def test_client_intake_follows_the_conflict_decision(client, cast, cleanup):
    name = f"Zephyr Quillon {uuid.uuid4().hex[:4]} Holdings Ltd"
    clean = _check(client, cast["partner"], [name], cleanup).json()
    assert clean["status"] == "clear"  # nobody by that name anywhere
    # A name the check did not cover is refused.
    assert client.post("/api/clients", json={"name": "Somebody Else Ltd", "check_id": clean["check_id"]},
                       headers=as_member(cast["partner"])).status_code == 422
    r = client.post("/api/clients", json={"name": name, "check_id": clean["check_id"], "industry": "Energy"},
                    headers=as_member(cast["partner"]))
    assert r.status_code == 201, r.text
    cleanup["clients"].append(r.json()["client_id"])
    assert r.json()["status"] == "active"
    assert client.post("/api/clients", json={"name": name, "check_id": clean["check_id"]},
                       headers=as_member(cast["partner"])).status_code == 409

    # A check with hits: the client waits as prospective until Risk decides.
    hit = _check(client, cast["partner"], ["Acme Technologies", f"Acme Technologies {uuid.uuid4().hex[:4]}"], cleanup).json()
    assert hit["status"] == "awaiting_risk"
    new_name = hit["names"][1]
    r = client.post("/api/clients", json={"name": new_name, "check_id": hit["check_id"]}, headers=as_member(cast["partner"]))
    cleanup["clients"].append(r.json()["client_id"])
    assert r.json()["status"] == "prospective"
    # Matters cannot be opened for a prospective client.
    assert client.post("/api/matters", json={"title": "t", "client_id": r.json()["client_id"], "practice_area": "Corporate"},
                       headers=as_member(cast["partner"])).status_code == 422
    todo = client.get("/api/conflicts?scope=to_decide", headers=as_member(cast["risk"])).json()["items"]
    assert hit["check_id"] in {c["check_id"] for c in todo}
    assert client.post(f"/api/conflicts/{hit['check_id']}/decision", json={"decision": "clear"},
                       headers=as_member(cast["partner"])).status_code == 403
    assert client.post(f"/api/conflicts/{hit['check_id']}/decision", json={"decision": "waived"},
                       headers=as_member(cast["risk"])).status_code == 422  # a waiver needs reasons
    d = client.post(f"/api/conflicts/{hit['check_id']}/decision", json={"decision": "waived", "notes": "Group company; consent on file"},
                    headers=as_member(cast["risk"]))
    assert d.status_code == 200 and d.json()["decision"] == "waived"
    assert _rows("SELECT status FROM clients WHERE client_id = %s", (r.json()["client_id"],))[0]["status"] == "active"


# ── people ───────────────────────────────────────────────────────────────────

def test_people_edit_their_expertise_and_admins_onboard(client, cast, cleanup):
    before = _rows("SELECT practice_areas FROM members WHERE member_id = %s", (cast["associate"],))[0]["practice_areas"]
    try:
        r = client.patch("/api/people/me", json={"practice_areas": ["Corporate", "Energy"]}, headers=as_member(cast["associate"]))
        assert r.status_code == 200 and r.json()["practice_areas"] == ["Corporate", "Energy"]
        assert client.patch("/api/people/me", json={"office": "Paris"}, headers=as_member(cast["associate"])).status_code == 422
        assert client.patch(f"/api/people/{cast['outsider']}", json={"office": "Paris"},
                            headers=as_member(cast["associate"])).status_code == 403
    finally:
        with connect() as conn:
            conn.execute("UPDATE members SET practice_areas = %s WHERE member_id = %s", (before, cast["associate"]))
            conn.commit()
    r = client.post("/api/people", json={"name": "Test Newcomer", "role": "Associate", "office": "Geneva",
                                         "email": f"new.{uuid.uuid4().hex[:6]}@example.com", "roles": ["fee_earner"]},
                    headers=as_member(cast["admin"]))
    assert r.status_code == 201, r.text
    cleanup["members"].append(r.json()["member_id"])
    assert r.json()["roles"] == ["fee_earner"]
    assert client.post("/api/people", json={"name": "x"}, headers=as_member(cast["associate"])).status_code == 403


# ── live updates and my work ─────────────────────────────────────────────────

def test_event_feed_is_filtered_per_member(client, cast, cleanup):
    start = client.get("/api/events", headers=as_member(cast["associate"])).json()["latest"]
    m = _new_matter(client, cast, cleanup)  # team mode: the outsider cannot see it
    client.post(f"/api/matters/{m['matter_id']}/events", json={"occurred_on": "2026-03-01", "title": "Hearing listed"},
                headers=as_member(cast["associate"]))
    seen = client.get(f"/api/events?since={start}", headers=as_member(cast["associate"])).json()
    assert {"matter.created", "matter.timeline"} <= {e["topic"] for e in seen["items"] if e["matter_id"] == m["matter_id"]}
    assert seen["latest"] > start
    hidden = client.get(f"/api/events?since={start}", headers=as_member(cast["outsider"])).json()
    assert not any(e["matter_id"] == m["matter_id"] for e in hidden["items"])
    assert hidden["latest"] >= seen["latest"]  # the cursor still moves past what they cannot see


def test_event_stream_speaks_sse(client, cast, cleanup, monkeypatch):
    from app.api.routers import firm

    monkeypatch.setattr(firm, "STREAM_SECONDS", 2.5)
    monkeypatch.setattr(firm, "POLL_SECONDS", 0.2)
    start = client.get("/api/events", headers=as_member(cast["partner"])).json()["latest"]
    m = _new_matter(client, cast, cleanup)
    with client.stream("GET", f"/api/events/stream?since={start}", headers=as_member(cast["partner"])) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert "event: ready" in body and "event: matter.created" in body and m["matter_id"] in body


def test_my_work(client, cast, cleanup):
    m = _new_matter(client, cast, cleanup)
    work = client.get("/api/home/my-work", headers=as_member(cast["associate"])).json()
    assert m["matter_id"] in {x["matter_id"] for x in work["matters"]}
    assert set(work) == {"matters", "due", "editing", "comments", "decisions"}
    risk = client.get("/api/home/my-work", headers=as_member(cast["risk"])).json()
    assert "conflict_checks" in risk["decisions"]


def test_a_creator_reads_their_new_matter_even_when_the_app_clock_is_a_day_ahead(client, cast, cleanup, monkeypatch):
    """The start date comes from the database's clock: with the app server's local date a day ahead of the database's
    (a different time zone), the creator's own assignment must not start 'tomorrow' and lock them out."""
    import app.firm.matters as matters_mod

    class Tomorrow(date):
        @classmethod
        def today(cls):
            return date.today() + timedelta(days=1)

    monkeypatch.setattr(matters_mod, "date", Tomorrow)
    r = client.post("/api/matters", headers=as_member(cast["partner"]), json={
        "title": f"E2E-TMP clock {uuid.uuid4().hex[:6]}", "client_id": CLIENT, "practice_area": "Corporate", "access_mode": "team"})
    assert r.status_code == 201 or r.status_code == 200, r.text
    mid = r.json()["matter_id"]
    cleanup["matters"].append(mid)
    assert client.get(f"/api/matters/{mid}", headers=as_member(cast["partner"])).status_code == 200
    started = _rows("SELECT started_at, current_date AS today FROM matter_members WHERE matter_id = %s", (mid,))[0]
    assert started["started_at"] <= started["today"]
