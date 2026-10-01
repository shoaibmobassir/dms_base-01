"""The KM panel on Ask the Firm answers: matters, documents and people, ACL-safe.

Expected values come from Postgres, not from one corpus snapshot.
"""
from __future__ import annotations

import pytest

from app.db.connection import connect
from app.km import answer as km_answer
from app.km.answer import ask_the_firm
from app.km.panel import build_panel, mark_cited
from tests.conftest import as_member


def _one(sql: str, params: tuple = ()):
    with connect() as conn:
        return conn.execute(sql, params).fetchone()


@pytest.fixture(scope="module")
def led_matter(seeded):
    row = _one(
        """
        SELECT m.matter_id, m.matter_code, mb.member_id AS lead_id, mb.name AS lead_name
        FROM matters m JOIN permissions p USING (matter_id)
        JOIN matter_members mm ON mm.matter_id = m.matter_id AND mm.role_on_matter = 'Lead'
        JOIN members mb ON mb.member_id = mm.member_id
        WHERE NOT p.restricted AND EXISTS (SELECT 1 FROM documents d WHERE d.matter_id = m.matter_id)
        ORDER BY m.matter_id LIMIT 1
        """
    )
    if not row:
        pytest.skip("no unrestricted matter with a lead")
    return row


@pytest.fixture
def no_llm(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("llm disabled in test")

    monkeypatch.setattr(km_answer, "_llm", _boom)


def test_scoped_answer_lists_the_matter_first_and_its_lead_first(led_matter, no_llm):
    with connect() as conn:
        out = ask_the_firm(conn, "explain this", "MEM-00011", {"type": "matter", "value": led_matter["matter_code"]})
    panel = out["panel"]
    assert panel["matters"][0]["matter_id"] == led_matter["matter_id"]
    assert panel["matters"][0]["relation"] == "asked"
    lead = panel["people"][0]
    assert lead["member_id"] == led_matter["lead_id"]
    assert f"Lead on {led_matter['matter_code']}" in lead["why"]
    assert panel["documents"], "a matter overview must still list the matter's documents"


def test_restricted_matter_never_enters_the_panel(walls):
    w = walls[0]
    passage = {"document_id": w.document_id, "matter_id": w.matter_id, "matter_code": w.matter_code,
               "title": "restricted", "text": "restricted text", "score": 1.0}
    with connect() as conn:
        panel = build_panel(
            conn, member_id=w.outsider, scope_ids=[w.matter_id], cards=[], passages=[passage],
            candidates=[{"matter_id": w.matter_id, "score": 0.9}], experts=[], people_first=False,
        )
    assert w.matter_id not in {m["matter_id"] for m in panel["matters"]}
    assert w.document_id.upper() not in {d["document_id"] for d in panel["documents"]}
    assert all(m["matter_id"] != w.matter_id for p in panel["people"] for m in p["on_matters"])


def test_cited_documents_are_flagged_and_listed_first():
    panel = {"documents": [{"document_id": "DOC-A", "why": "relevant passage"},
                           {"document_id": "DOC-B", "why": "relevant passage"}]}
    mark_cited(panel, {"DOC-B"})
    assert [d["document_id"] for d in panel["documents"]] == ["DOC-B", "DOC-A"]
    assert panel["documents"][0]["cited"] and panel["documents"][0]["why"] == "cited in the answer"


def test_api_returns_panel_and_matched_matters_from_it(client, led_matter, no_llm):
    body = {"query": "explain this", "scope": {"type": "matter", "value": led_matter["matter_code"]}}
    out = client.post("/api/answers", json=body, headers=as_member("MEM-00011")).json()
    assert set(out["panel"]) == {"matters", "documents", "people"}
    assert out["matchedMatters"][0]["matter_id"] == led_matter["matter_id"]
    assert "similarity" not in out["matchedMatters"][0]
    assert out["latency_ms"]["panel_ms"] < 500
