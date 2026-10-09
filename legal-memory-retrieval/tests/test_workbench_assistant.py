"""The Assistant in the workbench (plan 22, W3): conversations bound to a workspace, and the tools that reach a
workspace's own documents and its tabular reviews — always within what the member may read."""
from __future__ import annotations

import uuid

from app.chat.agent import dispatch_tool_call
from app.chat.models import ChatSession
from app.db.connection import connect
from app.api.routers.chat_router import _workspace_scope
from tests.conftest import as_member
from tests.test_tabular import FakeModel, model, reviews  # noqa: F401  (fixtures)
from tests.test_workspaces import _ok, _project, _upload, cast, made  # noqa: F401  (fixtures)


def _cleanup_sessions(ids):
    with connect() as conn:
        conn.execute("DELETE FROM chat_messages WHERE session_id = ANY(%s)", (ids,))
        conn.execute("DELETE FROM chat_sessions WHERE id = ANY(%s)", (ids,))
        conn.commit()


def test_a_conversation_belongs_to_a_workspace_its_member_can_reach(client, cast, made):
    pid = _project(client, cast["outsider"], made)["project_id"]
    made_sessions = []
    try:
        r = client.post("/api/chat/sessions", json={"workspace_kind": "project", "workspace_id": pid},
                        headers=as_member(cast["outsider"]))
        assert r.status_code == 200, r.text
        made_sessions.append(r.json()["id"])
        assert r.json()["workspace_kind"] == "project" and r.json()["workspace_id"] == pid
        assert client.post("/api/chat/sessions", json={"workspace_kind": "project", "workspace_id": pid},
                           headers=as_member(cast["stranger"])).status_code == 404
        lib = _ok(client.post("/api/chat/sessions", json={"workspace_kind": "library", "workspace_id": "me"},
                              headers=as_member(cast["outsider"])))
        made_sessions.append(lib["id"])
        assert lib["workspace_id"] == cast["outsider"]
        listed = _ok(client.get("/api/chat/sessions", params={"workspace_kind": "project", "workspace_id": pid},
                                headers=as_member(cast["outsider"])))
        assert [s["id"] for s in listed] == [made_sessions[0]]
        # leaving the project removes the workspace from the conversation's tools
        session = ChatSession(id=made_sessions[0], member_id=cast["stranger"], workspace_kind="project", workspace_id=pid)
        with connect() as conn:
            assert _workspace_scope(conn, session) is None
            mine = ChatSession(id=made_sessions[0], member_id=cast["outsider"], workspace_kind="project", workspace_id=pid)
            assert _workspace_scope(conn, mine)["label"].startswith("E2E-TMP")
    finally:
        _cleanup_sessions(made_sessions)


def test_search_workspace_finds_project_documents_the_firm_search_cannot(client, cast, made):
    pid = _project(client, cast["outsider"], made)["project_id"]
    word = f"wombat{uuid.uuid4().hex[:6]}"
    doc, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid, body=f"E2E-TMP the {word} warranty lasts two years".encode())
    index: dict = {}
    with connect() as conn:
        result, _ = dispatch_tool_call("search_workspace", {"query": word}, index, {}, conn, "n", member_id=cast["outsider"],
                                       workspace={"kind": "project", "id": pid, "label": "p"})
        assert [r["title"] for r in result["results"]] and result["results"][0]["doc_id"] in index
        assert index[result["results"][0]["doc_id"]].document_id == doc
        # someone outside the project gets nothing (and no slug for the document)
        other: dict = {}
        result, _ = dispatch_tool_call("search_workspace", {"query": word}, other, {}, conn, "n", member_id=cast["stranger"],
                                       workspace={"kind": "project", "id": pid, "label": "p"})
        assert "error" in result and not other
        # without a workspace the tool says so
        result, _ = dispatch_tool_call("search_workspace", {"query": word}, {}, {}, conn, "n", member_id=cast["outsider"])
        assert "error" in result


def test_read_review_cells_is_redacted_like_the_page(client, cast, made, model, reviews):
    wall = cast["wall"]
    pid = _project(client, cast["insider"], made)["project_id"]
    _ok(client.put(f"/api/projects/{pid}/members", json={"principal_id": cast["outsider"], "role": "viewer"},
                   headers=as_member(cast["insider"])))
    _ok(client.post(f"/api/workspaces/documents/{wall.document_id}/links", json={"kind": "project", "id": pid},
                    headers=as_member(cast["insider"])), 201)
    own, _, _ = _upload(client, cast["insider"], made, kind="project", cid=pid)
    r = client.post("/api/tabular/reviews", json={"title": "T", "kind": "project", "id": pid, "document_ids": [wall.document_id, own],
                                                  "columns": [{"preset": "parties"}]}, headers=as_member(cast["insider"]))
    rid = _ok(r, 201)["review_id"]
    reviews.append(rid)
    with connect() as conn:
        insider, _ = dispatch_tool_call("read_review_cells", {"review_id": rid}, {}, {}, conn, "n", member_id=cast["insider"])
        outsider, _ = dispatch_tool_call("read_review_cells", {"review_id": rid}, {}, {}, conn, "n", member_id=cast["outsider"])
        stranger, _ = dispatch_tool_call("read_review_cells", {"review_id": rid}, {}, {}, conn, "n", member_id=cast["stranger"])
    assert len(insider["cells"]) == 2
    assert [c["document_id"] for c in outsider["cells"]] == [own]
    assert "error" in stranger


def test_find_precedents_reads_only_firm_material_the_member_may_read_and_leaves_out_the_source(client, cast, made):
    from app.chat.tools.precedents import find_precedents
    from app.embeddings.pending import embed_pending_chunks

    # a firm document the partner can read, with a vector
    with connect() as conn:
        row = conn.execute(
            """SELECT c.document_id, c.text FROM chunks c JOIN documents d USING (document_id)
               WHERE d.home_kind = 'matter' AND d.archived_at IS NULL AND c.embedding IS NOT NULL
                 AND NOT coalesce(c.is_parent, false) AND length(c.text) > 200
                 AND (c.version_id IS NULL OR c.version_id = d.current_version_id)
                 AND EXISTS (SELECT 1 FROM documents x JOIN permissions p ON p.matter_id = x.matter_id
                             WHERE x.document_id = d.document_id)
               ORDER BY c.chunk_id LIMIT 1""").fetchone()
        assert row, "needs an embedded matter document"
        partner = "MEM-00001"
        found = find_precedents(conn, partner, row["text"])
        assert found and found[0]["similarity"] > 0.5
        top = found[0]["document_id"]
        assert top not in {h["document_id"] for h in find_precedents(conn, partner, row["text"], top)}
        assert all(h["home_kind"] in ("matter", "firm") for h in found)

    # a project document with a distinctive clause is never offered as a firm precedent, even to its owner
    pid = _project(client, cast["outsider"], made)["project_id"]
    clause = (f"E2E-TMP The Licensee shall indemnify the Licensor against all claims arising from the use of the "
              f"Platypus{uuid.uuid4().hex[:6]} software in breach of this licence.")
    doc, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid, body=clause.encode())
    embed_pending_chunks([doc])
    with connect() as conn:
        assert doc not in {h["document_id"] for h in find_precedents(conn, cast["outsider"], clause, limit=10)}
        result, _ = dispatch_tool_call("find_precedents", {"text": clause}, {}, {}, conn, "n", member_id=cast["outsider"])
        assert "passages" in result and all(p["kind"] in ("firm template", "matter document") for p in result["passages"])
        short, _ = dispatch_tool_call("find_precedents", {"text": "too short"}, {}, {}, conn, "n", member_id=cast["outsider"])
        assert "error" in short
