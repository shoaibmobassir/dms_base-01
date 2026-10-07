"""Playbooks (plan 22, W5) through the HTTP API: shipped, firm and personal; sharing; publishing; the Assistant reads
them fenced as user-selected instructions; a column set starts a tabular review."""
from __future__ import annotations

import pytest

from app import access, playbooks
from app.chat.agent import dispatch_tool_call
from app.db.connection import connect
from tests.conftest import as_member
from tests.test_tabular import FakeModel, model, reviews  # noqa: F401  (fixtures)
from tests.test_workspaces import _ok, _project, _upload, cast, made  # noqa: F401  (fixtures)


@pytest.fixture
def publisher(seeded):
    with connect() as conn:
        for r in conn.execute("SELECT DISTINCT member_id FROM member_roles WHERE role_key IN ('knowledge_manager', 'partner') "
                              "ORDER BY member_id"):
            if access.has_permission(conn, r["member_id"], "km.publish") and not access.has_permission(conn, r["member_id"], "walls.manage"):
                return r["member_id"]
    pytest.skip("no member with km.publish")


@pytest.fixture
def plain(seeded):
    """Two members who cannot publish to the firm (no km.publish) and hold no walls.manage."""
    with connect() as conn:
        found = [r["member_id"] for r in conn.execute("SELECT member_id FROM members WHERE active ORDER BY member_id")
                 if not access.has_permission(conn, r["member_id"], "km.publish")
                 and not access.has_permission(conn, r["member_id"], "walls.manage")]
    if len(found) < 2:
        pytest.skip("needs two members without km.publish")
    return {"a": found[0], "b": found[1]}


@pytest.fixture
def mine():
    ids: list[str] = []
    yield ids
    with connect() as conn:
        conn.execute("DELETE FROM playbooks WHERE playbook_id = ANY(%s)", (ids,))
        conn.commit()


def test_the_shipped_catalog_syncs_once_and_is_read_only(client, cast, mine):
    with connect() as conn:
        playbooks.sync_shipped(conn, force=True)
        assert playbooks.sync_shipped(conn, force=True) == 0  # same content: nothing to do
    items = _ok(client.get("/api/playbooks", headers=as_member(cast["outsider"])))["items"]
    shipped = {p["playbook_id"]: p for p in items if p["source"] == "shipped"}
    assert "PBK-CONTRACT-TRIAGE" in shipped and "PBK-CONTRACT-KEY-TERMS-COLUMNS" in shipped
    assert shipped["PBK-CONTRACT-KEY-TERMS-COLUMNS"]["kind"] == "columns" and shipped["PBK-CONTRACT-KEY-TERMS-COLUMNS"]["column_count"] == 10
    r = client.patch("/api/playbooks/PBK-CONTRACT-TRIAGE", json={"title": "x"}, headers=as_member(cast["outsider"]))
    assert r.status_code == 403
    copy = _ok(client.post("/api/playbooks/PBK-CONTRACT-TRIAGE/duplicate", headers=as_member(cast["outsider"])), 201)
    mine.append(copy["playbook_id"])
    assert copy["source"] == "personal" and copy["origin_playbook_id"] == "PBK-CONTRACT-TRIAGE" and copy["my_level"] == "manage"
    edited = _ok(client.patch(f"/api/playbooks/{copy['playbook_id']}", json={"title": "My triage", "row_version": copy["row_version"]},
                              headers=as_member(cast["outsider"])))
    assert edited["title"] == "My triage" and edited["version"] == 2


def test_personal_playbooks_are_private_until_shared(client, plain, mine):
    body = {"kind": "instructions", "title": "E2E-TMP my way", "body_md": "1. Read the document.\n2. List the risks."}
    pb = _ok(client.post("/api/playbooks", json=body, headers=as_member(plain["a"])), 201)
    mine.append(pb["playbook_id"])
    assert client.get(f"/api/playbooks/{pb['playbook_id']}", headers=as_member(plain["b"])).status_code == 404
    assert pb["playbook_id"] not in [p["playbook_id"] for p in _ok(client.get("/api/playbooks", headers=as_member(plain["b"])))["items"]]
    _ok(client.put(f"/api/playbooks/{pb['playbook_id']}/shares", json={"principal_id": plain["b"], "level": "view"},
                   headers=as_member(plain["a"])))
    seen = _ok(client.get(f"/api/playbooks/{pb['playbook_id']}", headers=as_member(plain["b"])))
    assert seen["my_level"] == "read" and seen["body_md"].startswith("1. Read")
    assert client.patch(f"/api/playbooks/{pb['playbook_id']}", json={"title": "x"}, headers=as_member(plain["b"])).status_code == 403
    # an outsider cannot publish to the firm
    assert client.post(f"/api/playbooks/{pb['playbook_id']}/publish", headers=as_member(plain["a"])).status_code == 403
    bad = client.post("/api/playbooks", json={"kind": "columns", "title": "x", "columns": []}, headers=as_member(plain["a"]))
    assert bad.status_code == 422


def test_publishing_makes_a_playbook_the_firms(client, plain, publisher, mine):
    pb = _ok(client.post("/api/playbooks", json={"kind": "instructions", "title": "E2E-TMP firm way", "body_md": "Do it well."},
                         headers=as_member(publisher)), 201)
    mine.append(pb["playbook_id"])
    out = _ok(client.post(f"/api/playbooks/{pb['playbook_id']}/publish", headers=as_member(publisher)))
    assert out["source"] == "firm"
    other = _ok(client.get(f"/api/playbooks/{pb['playbook_id']}", headers=as_member(plain["b"])))
    assert other["my_level"] == "read"


def test_the_assistant_reads_a_playbook_fenced_and_its_reference_documents_by_access(client, cast, made, mine):
    pid = _project(client, cast["outsider"], made)["project_id"]
    doc, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid)
    pb = _ok(client.post("/api/playbooks", json={"kind": "instructions", "title": "E2E-TMP with refs",
                                                 "body_md": "Follow the template.", "document_ids": [doc, cast["wall"].document_id]},
                         headers=as_member(cast["outsider"])), 201)
    mine.append(pb["playbook_id"])
    assert [f["document_id"] for f in pb["files"]] == [doc]  # the walled document was never attached
    with connect() as conn:
        listed, _ = dispatch_tool_call("list_workflows", {}, {}, {}, conn, "N1", member_id=cast["outsider"])
        assert pb["playbook_id"] in [w["id"] for w in listed["workflows"]]
        read, _ = dispatch_tool_call("read_workflow", {"workflow_id": pb["playbook_id"]}, {}, {}, conn, "N1",
                                     member_id=cast["outsider"])
        assert read["instructions"].startswith('<workflow-instructions nonce="N1">')
        assert read["reference_documents"][0]["document_id"] == doc
        other, _ = dispatch_tool_call("read_workflow", {"workflow_id": pb["playbook_id"]}, {}, {}, conn, "N1",
                                      member_id=cast["stranger"])
        assert "error" in other


def test_a_column_set_starts_a_review_and_a_review_saves_its_questions(client, cast, made, model, reviews, mine):
    pid = _project(client, cast["outsider"], made)["project_id"]
    doc, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid)
    r = client.post("/api/tabular/reviews", json={"title": "From playbook", "kind": "project", "id": pid,
                                                  "playbook_id": "PBK-LEASE-REVIEW-COLUMNS", "document_ids": [doc]},
                    headers=as_member(cast["outsider"]))
    view = _ok(r, 201)
    reviews.append(view["review_id"])
    assert [c["label"] for c in view["columns"]][:2] == ["Landlord and tenant", "Premises"] and len(view["columns"]) == 8
    saved = _ok(client.post(f"/api/tabular/reviews/{view['review_id']}/save-as-playbook", json={"title": "E2E-TMP lease qs"},
                            headers=as_member(cast["outsider"])), 201)
    mine.append(saved["playbook_id"])
    assert saved["kind"] == "columns" and len(saved["columns"]) == 8
