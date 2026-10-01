"""Assistant tools backed by Ask the Firm, dispatched the way the agent calls them."""
from __future__ import annotations

import pytest

from app.chat.agent import dispatch_tool_call, tool_step_label
from app.chat.tools.schema import ALL_TOOLS, CORE_TOOLS
from app.db.connection import connect
from app.km import answer as km_answer


@pytest.fixture(scope="module")
def matter(seeded):
    with connect() as conn:
        row = conn.execute(
            """
            SELECT m.matter_id, m.matter_code, m.title FROM matters m JOIN permissions p USING (matter_id)
            WHERE NOT p.restricted
              AND EXISTS (SELECT 1 FROM documents d WHERE d.matter_id = m.matter_id)
              AND EXISTS (SELECT 1 FROM matter_members mm WHERE mm.matter_id = m.matter_id)
            ORDER BY m.matter_id LIMIT 1
            """
        ).fetchone()
    if not row:
        pytest.skip("no staffed matter with documents")
    return row


def _call(name: str, args: dict, doc_index: dict, member: str | None = "MEM-00011"):
    with connect() as conn:
        return dispatch_tool_call(name, args, doc_index, {}, conn, "nonce", member_id=member)


def test_firm_tools_are_advertised_first():
    names = [t["function"]["name"] for t in CORE_TOOLS]
    assert names[:4] == ["ask_firm", "resolve_matter", "get_matter_profile", "find_people"]
    assert {"list_workflows", "read_workflow"} <= {t["function"]["name"] for t in ALL_TOOLS}


def test_get_matter_profile_registers_documents(matter):
    idx: dict = {}
    result, events = _call("get_matter_profile", {"matter": matter["matter_code"]}, idx)
    assert result["matter"]["matter_id"] == matter["matter_id"]
    assert result["team"] and result["documents"]
    assert {d["doc_id"] for d in result["documents"]} <= set(idx)
    assert events and events[0]["type"] == "matter_profile"


def test_find_people_for_matter(matter):
    result, _ = _call("find_people", {"matter": matter["matter_code"]}, {})
    with connect() as conn:
        n = conn.execute("SELECT count(*) AS n FROM matter_members WHERE matter_id = %s", (matter["matter_id"],)).fetchone()["n"]
    assert len(result["people"]) == n


def test_resolve_matter_by_title(matter):
    result, _ = _call("resolve_matter", {"query": matter["title"]}, {})
    assert result["status"] == "resolved"
    assert result["matters"][0]["matter_id"] == matter["matter_id"]


def test_ask_firm_returns_citable_passages(matter, monkeypatch):
    monkeypatch.setattr(km_answer, "_llm", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no llm")))
    idx: dict = {}
    result, _ = _call("ask_firm", {"question": "explain this", "scope": matter["matter_code"]}, idx)
    assert result["resolved_scope"] == matter["matter_code"]
    assert result["passages"], "agent needs verbatim passages to cite"
    assert all(p["doc_id"] in idx for p in result["passages"])
    assert "DOC-" not in result["draft_answer"], "raw DMS ids must be mapped to document names"


def test_ask_firm_respects_ethical_wall(walls):
    w = walls[0]
    result, _ = _call("get_matter_profile", {"matter": w.matter_code}, {}, member=w.outsider)
    assert "error" in result


def test_workflow_tools_dispatch():
    listed, _ = _call("list_workflows", {}, {})
    assert "workflows" in listed
    if listed["workflows"]:
        wf_id = listed["workflows"][0]["id"]
        read, _ = _call("read_workflow", {"workflow_id": wf_id}, {})
        assert read["id"] == wf_id and "steps" in read


def test_step_labels_hide_tool_names():
    for name, args in [("ask_firm", {"question": "q"}), ("resolve_matter", {"query": "q"}),
                       ("get_matter_profile", {"matter": "X"}), ("find_people", {"query": "q"})]:
        label = tool_step_label(name, args, {})
        assert name not in label and label != "Working"


def test_ask_firm_reads_a_descriptive_scope(matter, monkeypatch):
    """Models pass descriptions ("<title words>") as scope; they must still resolve."""
    monkeypatch.setattr(km_answer, "_llm", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no llm")))
    words = " ".join(matter["title"].split("—")[0].split()[:3])
    result, _ = _call("ask_firm", {"question": "who is on the team?", "scope": f"our {words} matter"}, {})
    assert result["status"] != "no_evidence"
