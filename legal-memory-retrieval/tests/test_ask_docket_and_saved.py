"""Docket pinning and stored Ask the Firm answers (plan 19)."""
from __future__ import annotations

import uuid

from app.db.connection import connect
from app.km import ask_answers
from app.km.answer import _dedupe_key_finding, gather_evidence
from app.km.docket import parse_docket, pin_docket, title_contains_docket
from app.query.understand import understand
from tests.conftest import as_member


APPEAL_Q = (
    "APPEAL NO. 163 OF 2018 , have we prepared brief note of arguments in this appeal ?"
)


def test_parse_docket_forms():
    assert parse_docket("APPEAL NO. 163 OF 2018").label == "Appeal 163 of 2018"
    assert parse_docket("APL. 163 of 2018").label == "Appeal 163 of 2018"
    assert parse_docket("Civil Appeal 10046 of 2025").label == "Civil Appeal 10046 of 2025"
    assert parse_docket("Petition 310/MP/2026").label == "Petition 310/MP/2026"
    assert parse_docket("who led the Acme deal?") is None


def test_understand_records_docket():
    parsed = understand(APPEAL_Q)
    assert parsed.docket == "Appeal 163 of 2018"
    assert understand("explain this matter").docket is None


def test_title_phrase_match_not_stem_bags():
    docket = parse_docket("Appeal 163 of 2018")
    assert title_contains_docket("GMR Warora Energy v CERC — Appeal 163 of 2018", docket)
    assert title_contains_docket("MSEDCL Note in APL. 163 of 2018.pdf", docket)
    # Security Council resolution 163 must not match an appeal docket.
    assert not title_contains_docket(
        "Security Council resolution 163 (1961) [on the mandate]", docket,
    )


def test_docket_pins_title_matter_not_upload_copies(seeded):
    with connect() as conn:
        titled, copies, docket = pin_docket(conn, APPEAL_Q, None)
    assert docket is not None
    assert docket.label == "Appeal 163 of 2018"
    assert len(titled) == 1
    assert titled[0].matter_code == "REG/DEL/0166/2018"
    assert any(c.matter_code == "CI-OPEN-001" for c in copies)


def test_gather_evidence_scopes_only_to_docket_matter(seeded):
    with connect() as conn:
        g = gather_evidence(conn, APPEAL_Q, None)
    assert g.sc.method == "docket"
    assert g.sc.matter_ids == ["MTR-2018-00166"]
    assert g.base.get("docket") == "Appeal 163 of 2018"
    assert g.sc.matter_ids == [c["matter_id"] for c in g.cards] or g.cards[0]["matter_id"] == "MTR-2018-00166"
    # Upload copies on CI-OPEN-001 must not become evidence passages / cards.
    assert all(c["matter_id"] == "MTR-2018-00166" for c in g.cards)
    assert all(str(h.get("matter_id")) == "MTR-2018-00166" for h in g.passages if h.get("matter_id"))
    copy_codes = {c["matter_code"] for c in (g.base.get("docket_copies") or [])}
    assert "CI-OPEN-001" in copy_codes


def test_no_docket_still_uses_stem_resolver(seeded):
    with connect() as conn:
        g = gather_evidence(conn, "which lawyers have experience in arbitration?", None)
    assert g.sc.method != "docket"
    assert g.base.get("docket") is None


def test_dedupe_key_finding_drops_repeated_first_paragraph():
    key = "Yes, a brief note was prepared for MSEDCL [1]."
    body = (
        "Yes, a brief note was prepared for MSEDCL [1].\n\n"
        "The document is titled Brief note of submissions [2]."
    )
    k, a = _dedupe_key_finding(key, body)
    assert k.startswith("Yes")
    assert "Brief note of submissions" in a
    assert not a.lower().startswith("yes, a brief note")


def test_saved_answer_skips_model_on_second_ask(client, seeded, monkeypatch):
    question = f"Appeal No. 163 of 2018 saved-answer test {uuid.uuid4()}"
    payload = {
        "answer": "Yes — brief note on REG/DEL/0166/2018.",
        "key_finding": "Brief note exists.",
        "status": "answered",
        "provider": "records",
        "abstained": False,
        "citations": [],
        "span_citations": [],
        "panel": {
            "matters": [{
                "matter_id": "MTR-2018-00166",
                "matter_code": "REG/DEL/0166/2018",
                "title": "GMR Warora Energy v CERC — Appeal 163 of 2018",
            }],
            "documents": [],
            "people": [],
        },
        "matter_cards": [{"matter_id": "MTR-2018-00166", "matter_code": "REG/DEL/0166/2018",
                          "title": "GMR Warora Energy v CERC — Appeal 163 of 2018"}],
        "sources": [],
        "people": [],
        "resolved_scope": {
            "kind": "matter", "method": "docket", "label": "REG/DEL/0166/2018",
            "matter_ids": ["MTR-2018-00166"],
        },
        "hits": [],
    }
    with connect() as conn:
        saved_id = ask_answers.save(conn, "MEM-00001", question, None, payload)

    calls = {"n": 0}

    def _boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("model must not run for a saved answer")

    monkeypatch.setattr("app.km.answer.ask_the_firm", _boom)
    monkeypatch.setattr("app.km.answer.ask_the_firm_stream", _boom)

    headers = as_member("MEM-00001")
    res = client.post("/api/answers", json={"query": question}, headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("saved") is True
    assert "REG/DEL/0166/2018" in body["answer"]
    assert calls["n"] == 0

    by_id = client.get(f"/api/answers/saved/{saved_id}", headers=headers)
    assert by_id.status_code == 200
    assert by_id.json()["key_finding"] == "Brief note exists."
    assert by_id.json()["saved_id"] == saved_id

    # Stream path also short-circuits.
    stream = client.post("/api/answers/stream", json={"query": question}, headers=headers)
    assert stream.status_code == 200
    assert "\"saved\": true" in stream.text or "Brief note exists" in stream.text
    assert calls["n"] == 0

    saved = client.get(f"/api/answers/saved?q={question}", headers=headers)
    assert saved.status_code == 200
    assert saved.json()["key_finding"] == "Brief note exists."


def test_saved_answer_refresh_reruns(client, seeded, monkeypatch):
    question = f"Appeal No. 163 of 2018 refresh test {uuid.uuid4()}"
    with connect() as conn:
        ask_answers.save(conn, "MEM-00001", question, None, {
            "answer": "stale", "key_finding": "stale", "status": "answered",
            "provider": "records", "abstained": False, "citations": [],
            "panel": {"matters": [{"matter_id": "MTR-2018-00166", "matter_code": "REG/DEL/0166/2018",
                                   "title": "x"}], "documents": [], "people": []},
            "matter_cards": [], "sources": [], "people": [],
            "resolved_scope": {"matter_ids": ["MTR-2018-00166"]},
            "hits": [],
        })

    def fake_ask(conn, q, member_id, scope=None, **_k):
        return {
            "query": q, "answer": "fresh", "key_finding": "fresh", "citations": [],
            "abstained": False, "provider": "records", "status": "fallback",
            "hits": [], "people": [], "matter_cards": [],
            "resolved_scope": {"matter_ids": ["MTR-2018-00166"], "method": "docket"},
            "panel": {"matters": [{"matter_id": "MTR-2018-00166", "matter_code": "REG/DEL/0166/2018",
                                   "title": "x", "document_count": 0}], "documents": [], "people": []},
            "latency_ms": {},
        }

    monkeypatch.setattr("app.api.routers.answers.ask_the_firm", fake_ask)
    res = client.post(
        "/api/answers",
        json={"query": question, "refresh": True},
        headers=as_member("MEM-00001"),
    )
    assert res.status_code == 200, res.text
    assert res.json()["answer"] == "fresh"
    assert res.json().get("saved") is not True


def test_saved_answer_dropped_when_acl_lost(client, walls, seeded):
    w = walls[0]
    question = f"ACL saved ask {uuid.uuid4()}"
    with connect() as conn:
        ask_answers.save(conn, w.outsider, question, None, {
            "answer": "secret", "key_finding": "secret", "status": "answered",
            "provider": "records", "abstained": False, "citations": [],
            "panel": {"matters": [{"matter_id": w.matter_id, "matter_code": w.matter_code,
                                   "title": w.title}], "documents": [], "people": []},
            "matter_cards": [{"matter_id": w.matter_id}],
            "sources": [{"matter_id": w.matter_id, "document_id": w.document_id}],
            "people": [],
            "resolved_scope": {"matter_ids": [w.matter_id]},
            "hits": [],
        })
    res = client.get(f"/api/answers/saved?q={question}", headers=as_member(w.outsider))
    assert res.status_code == 404
