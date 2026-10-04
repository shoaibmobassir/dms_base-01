"""Pinned conversations, matter-scoped conversations and Ask the Firm question history."""
from __future__ import annotations

import uuid

from app.api.routers.chat_router import _search
from app.chat.models import ChatSession
from app.db.connection import connect
from tests.conftest import Wall, as_member


def _new_session(client, member: str, **body) -> dict:
    resp = client.post("/api/chat/sessions", json=body, headers=as_member(member))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_pinning_keeps_activity_order_and_is_listed(client, seeded):
    me = as_member("MEM-00001")
    s = _new_session(client, "MEM-00001")
    try:
        assert s["pinned"] is False
        pinned = client.patch(f"/api/chat/sessions/{s['id']}", json={"pinned": True}, headers=me).json()
        assert pinned["pinned"] is True
        assert pinned["updated_at"] == s["updated_at"]  # pinning is not an edit
        listed = {x["id"]: x for x in client.get("/api/chat/sessions", headers=me).json()}
        assert listed[s["id"]]["pinned"] is True
        assert client.patch(f"/api/chat/sessions/{s['id']}", json={"pinned": False}, headers=me).json()["pinned"] is False
    finally:
        client.delete(f"/api/chat/sessions/{s['id']}", headers=me)


def test_conversation_matter_respects_the_wall(client, walls: list[Wall]):
    w = walls[0]
    assert client.post("/api/chat/sessions", json={"matter_id": w.matter_id}, headers=as_member(w.outsider)).status_code == 404

    s = _new_session(client, w.outsider)
    try:
        resp = client.patch(f"/api/chat/sessions/{s['id']}", json={"matter_id": w.matter_id}, headers=as_member(w.outsider))
        assert resp.status_code == 404
    finally:
        client.delete(f"/api/chat/sessions/{s['id']}", headers=as_member(w.outsider))

    s = _new_session(client, w.insider)
    ins = as_member(w.insider)
    try:
        scoped = client.patch(f"/api/chat/sessions/{s['id']}", json={"matter_id": w.matter_id}, headers=ins).json()
        assert scoped["matter_id"] == w.matter_id
        cleared = client.patch(f"/api/chat/sessions/{s['id']}", json={"matter_id": ""}, headers=ins).json()
        assert cleared["matter_id"] is None
    finally:
        client.delete(f"/api/chat/sessions/{s['id']}", headers=ins)


def test_scoped_conversation_searches_only_its_matter(walls: list[Wall]):
    w = walls[0]
    session = ChatSession(id="t", matter_id=w.matter_id, member_id=w.insider)
    with connect() as conn:
        hits = _search(conn, session, w.title)
    assert hits, "expected passages from the matter's own documents"
    assert {h["matter_id"] for h in hits} == {w.matter_id}


def test_ask_history_is_personal_deduplicated_and_deletable(client, seeded):
    from app.km import ask_answers

    question = f"History test {uuid.uuid4()}"
    with connect() as conn:
        ask_answers.save(conn, "MEM-00001", question, None, {
            "answer": "a", "key_finding": "a", "status": "answered", "provider": "records",
            "abstained": False, "citations": [], "panel": {"matters": [], "documents": [], "people": []},
            "matter_cards": [], "sources": [], "people": [], "hits": [],
        })
        ask_answers.save(conn, "MEM-00001", question, None, {
            "answer": "a2", "key_finding": "a2", "status": "answered", "provider": "records",
            "abstained": False, "citations": [], "panel": {"matters": [], "documents": [], "people": []},
            "matter_cards": [], "sources": [], "people": [], "hits": [],
        })  # same question: one row
        ask_answers.save(conn, "MEM-00001", question, {"type": "matter", "value": "CORP/X"}, {
            "answer": "b", "key_finding": "b", "status": "answered", "provider": "records",
            "abstained": False, "citations": [], "panel": {"matters": [], "documents": [], "people": []},
            "matter_cards": [], "sources": [], "people": [], "hits": [],
        })

    mine = client.get("/api/answers/history", headers=as_member("MEM-00001")).json()["items"]
    rows = [r for r in mine if r["query"] == question]
    assert len(rows) == 2
    assert {r["scope"] for r in rows} == {None, "CORP/X"}
    theirs = client.get("/api/answers/history", headers=as_member("MEM-00002")).json()["items"]
    assert all(r["query"] != question for r in theirs)

    # Another member cannot delete my question.
    assert client.delete(f"/api/answers/history/{rows[0]['id']}", headers=as_member("MEM-00002")).status_code == 404
    for r in rows:
        assert client.delete(f"/api/answers/history/{r['id']}", headers=as_member("MEM-00001")).status_code == 204
    left = client.get("/api/answers/history", headers=as_member("MEM-00001")).json()["items"]
    assert all(r["query"] != question for r in left)


def test_agent_search_tool_stays_inside_the_conversation_matter(walls: list[Wall]):
    from app.chat.agent import build_llm_messages, dispatch_tool_call

    w = walls[0]
    matter = {"matter_id": w.matter_id, "matter_code": w.matter_code, "title": w.title}
    with connect() as conn:
        result, _ = dispatch_tool_call(
            "search_firm_records", {"query": w.title}, {}, {}, conn, "nonce", member_id=w.insider, matter=matter,
        )
    assert result["results"], "expected results from the matter"
    assert {r["matter_id"] for r in result["results"]} == {w.matter_id}

    system = build_llm_messages([], "hello", {}, "nonce", matter=matter)[0]["content"]
    assert f"LIMITED TO ONE MATTER: {w.matter_code}" in system
