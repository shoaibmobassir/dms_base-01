"""Follow-up questions in Ask the Firm."""
from __future__ import annotations

import uuid

from app.db.connection import connect
from app.km import ask_answers
from app.km.follow_up import inherited_scope, standalone_question
from tests.conftest import as_member

MEMBER = "MEM-00001"


def _payload(answer: str = "Earlier answer.") -> dict:
    return {
        "answer": answer, "key_finding": "", "status": "answered", "provider": "records",
        "abstained": False, "citations": [], "span_citations": [],
        "panel": {"matters": [], "documents": [], "people": []},
        "matter_cards": [], "sources": [], "people": [],
        "resolved_scope": None, "hits": [],
    }


def test_standalone_question_carries_the_earlier_question():
    q = standalone_question("What did we argue on maintainability?", "And on the appeal?")
    assert q.startswith("What did we argue on maintainability?")
    assert q.endswith("Follow-up: And on the appeal?")


def test_standalone_question_without_history_is_just_the_question():
    assert standalone_question("", "  Who led it? ") == "Who led it?"


def test_standalone_question_bounds_the_earlier_text():
    out = standalone_question("start " + "x" * 5000 + " end", "next")
    assert len(out) < 500
    assert out.startswith("start") and "end Follow-up: next" in out  # the topic and the latest turn both survive


def test_scope_is_inherited_unless_the_member_sets_one():
    prev = {"scope": "MTR-1", "scope_type": "matter"}
    assert inherited_scope(prev, None) == {"type": "matter", "value": "MTR-1"}
    mine = {"type": "client", "value": "Acme"}
    assert inherited_scope(prev, mine) == mine
    assert inherited_scope({}, None) is None


def test_follow_up_to_an_unknown_answer_is_404(client, seeded):
    res = client.post(
        "/api/answers",
        json={"query": "and then?", "follow_up_of": str(uuid.uuid4())},
        headers=as_member(MEMBER),
    )
    assert res.status_code == 404


def test_follow_up_retrieves_with_context_and_is_stored_apart(client, seeded, monkeypatch):
    first_q = f"What did we argue on maintainability? {uuid.uuid4()}"
    follow_q = f"And on the appeal? {uuid.uuid4()}"
    with connect() as conn:
        first_id = ask_answers.save(conn, MEMBER, first_q, {"type": "matter", "value": "MTR-2018-00166"}, _payload())

    seen: dict = {}

    def _fake(conn, question, member_id, scope=None, **_k):
        seen["question"], seen["scope"] = question, scope
        return {**_payload("Follow-up answer."), "query": question, "latency_ms": {}}

    monkeypatch.setattr("app.api.routers.answers.ask_the_firm", _fake)
    res = client.post("/api/answers", json={"query": follow_q, "follow_up_of": first_id}, headers=as_member(MEMBER))
    assert res.status_code == 200, res.text
    body = res.json()
    assert first_q in seen["question"] and follow_q in seen["question"]
    assert seen["scope"] == {"type": "matter", "value": "MTR-2018-00166"}
    # The member's own wording is shown, and the answer says what it follows.
    assert body["query"] == follow_q
    assert body["follow_up_of"] == first_id
    assert body["follow_up_query"] == first_q

    reopened = client.get(f"/api/answers/saved/{body['saved_id']}", headers=as_member(MEMBER))
    assert reopened.status_code == 200
    assert reopened.json()["follow_up_of"] == first_id

    # The same words asked on their own must not be served the context-dependent answer.
    def _standalone(conn, question, member_id, scope=None, **_k):
        seen["standalone"] = question
        return {**_payload("Standalone answer."), "query": question, "latency_ms": {}}

    monkeypatch.setattr("app.api.routers.answers.ask_the_firm", _standalone)
    again = client.post(
        "/api/answers",
        json={"query": follow_q, "scope": {"type": "matter", "value": "MTR-2018-00166"}},
        headers=as_member(MEMBER),
    )
    assert again.status_code == 200
    assert again.json().get("saved") is not True
    assert seen["standalone"] == follow_q


def test_a_follow_up_never_overwrites_a_standalone_answer_with_the_same_words(client, seeded, monkeypatch):
    words = f"What about costs? {uuid.uuid4()}"
    with connect() as conn:
        standalone_id = ask_answers.save(conn, MEMBER, words, None, _payload("Standalone answer."))
        other_id = ask_answers.save(conn, MEMBER, f"Earlier question {uuid.uuid4()}", None, _payload())

    monkeypatch.setattr(
        "app.api.routers.answers.ask_the_firm",
        lambda conn, question, member_id, scope=None, **_k: {**_payload("Follow-up answer."), "query": question, "latency_ms": {}},
    )
    res = client.post("/api/answers", json={"query": words, "follow_up_of": other_id}, headers=as_member(MEMBER))
    assert res.status_code == 200, res.text
    assert res.json()["saved_id"] != standalone_id

    # The stand-alone row is intact, and also what the cache lookup returns for those words.
    got = client.get(f"/api/answers/saved/{standalone_id}", headers=as_member(MEMBER)).json()
    assert got["answer"] == "Standalone answer." and not got.get("follow_up_of")
    cached = client.get("/api/answers/saved", params={"q": words}, headers=as_member(MEMBER))
    assert cached.status_code == 200 and cached.json()["answer"] == "Standalone answer."


def test_a_follow_up_to_a_follow_up_keeps_the_thread_topic(client, seeded, monkeypatch):
    first_q = f"What did we argue on maintainability? {uuid.uuid4()}"
    with connect() as conn:
        first_id = ask_answers.save(conn, MEMBER, first_q, None, _payload())
    seen: list[str] = []

    def _fake(conn, question, member_id, scope=None, **_k):
        seen.append(question)
        return {**_payload("ok"), "query": question, "latency_ms": {}}

    monkeypatch.setattr("app.api.routers.answers.ask_the_firm", _fake)
    second = client.post("/api/answers", json={"query": "And on the appeal?", "follow_up_of": first_id}, headers=as_member(MEMBER)).json()
    client.post("/api/answers", json={"query": "What were the costs?", "follow_up_of": second["saved_id"]}, headers=as_member(MEMBER))
    assert "maintainability" in seen[-1] and "What were the costs?" in seen[-1]
