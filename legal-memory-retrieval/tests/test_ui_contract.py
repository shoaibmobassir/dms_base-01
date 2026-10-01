"""Contract tests: every endpoint the SPA calls, against the seeded database.

Field lists mirror frontend/src/api/types.ts. If a test here fails, the UI
breaks the same way — update both sides together.
"""
from __future__ import annotations

import pytest

from conftest import as_member

ME = as_member("MEM-00016")  # on two restricted matters, so every view has data


def get(client, path, headers=ME):
    resp = client.get(path, headers=headers)
    assert resp.status_code == 200, f"{path} → {resp.status_code}: {resp.text[:200]}"
    return resp.json()


def has(row: dict, *fields: str) -> None:
    missing = [f for f in fields if f not in row]
    assert not missing, f"missing {missing} in {sorted(row)}"


@pytest.fixture(scope="module")
def open_matter(client, seeded) -> dict:
    items = get(client, "/api/matters?status=Open&limit=50")["items"]
    assert items, "seed has open matters"
    return items[0]


@pytest.fixture(scope="module")
def document(client, seeded) -> dict:
    """A document visible to ME that has indexed leaf chunks (other fixtures may add bare rows)."""
    from app.db.connection import connect

    with connect() as conn:
        row = conn.execute(
            """
            SELECT d.document_id FROM documents d
            JOIN permissions p ON p.matter_id = d.matter_id
            WHERE (NOT p.restricted OR 'MEM-00016' = ANY(p.allowed_members))
              AND EXISTS (SELECT 1 FROM chunks c WHERE c.document_id = d.document_id AND NOT c.is_parent)
            ORDER BY d.document_id LIMIT 1
            """
        ).fetchone()
    assert row, "seeded corpus has chunked documents"
    return get(client, f"/api/documents/{row['document_id']}")


# ── Shell ─────────────────────────────────────────────────────────────────────


def test_boot_endpoints(client, seeded):
    info = get(client, "/api/system/info", headers={})
    has(info, "auth_enabled", "retrieval_engine", "index_version", "embedding_version", "features")
    firm = get(client, "/api/system/firm", headers={})
    has(firm, "name", "descriptor", "office")
    assert firm["name"] != "Unconfigured firm"
    me = get(client, "/api/people/me")["person"]
    assert me["member_id"] == "MEM-00016"


def test_me_requires_identity(client, seeded):
    assert client.get("/api/people/me").status_code == 401


def test_home_stats(client, seeded):
    body = get(client, "/api/home/stats")
    has(body, "firm", "counts")
    has(body["counts"], "matters", "documents", "arguments", "clients", "open_deadlines", "people")
    assert body["counts"]["open_deadlines"] > 0


def test_search(client, open_matter):
    results = get(client, f"/api/search?q={open_matter['matter_code']}")["results"]
    assert results
    has(results[0], "kind", "id", "code", "title", "subtitle", "meta", "status")


# ── Matters ───────────────────────────────────────────────────────────────────


def test_matters_list_paged_and_filtered(client, seeded):
    body = get(client, "/api/matters?limit=1&offset=0")
    has(body, "total", "items")
    assert len(body["items"]) == 1 and body["total"] >= 2, "fixture needs at least two visible matters"
    has(body["items"][0], "matter_id", "matter_code", "title", "client_id", "client_name", "practice_area",
        "status", "opened_date", "restricted")
    page2 = get(client, "/api/matters?limit=1&offset=1")["items"]
    assert page2 and page2[0]["matter_id"] != body["items"][0]["matter_id"]
    # Paging walks every row exactly once (stable sort).
    everything = [m["matter_id"] for off in range(body["total"]) for m in get(client, f"/api/matters?limit=1&offset={off}")["items"]]
    assert len(everything) == len(set(everything)) == body["total"]
    for status in ("Open", "Closed"):
        rows = get(client, f"/api/matters?status={status}&limit=50")["items"]
        assert all(m["status"] == status for m in rows)


def test_matter_detail_and_tabs(client, open_matter):
    mid = open_matter["matter_id"]
    detail = get(client, f"/api/matters/{mid}")
    has(detail, "matter", "team", "documents")
    has(detail["matter"], "opposing_party", "court", "legal_issues", "facts", "restricted")
    has(detail["team"][0], "member_id", "name", "role", "role_on_matter")

    timeline = get(client, f"/api/matters/{mid}/timeline")["timeline"]
    assert timeline
    has(timeline[0], "date", "event", "doc_id", "doc_type", "author")

    for a in get(client, f"/api/matters/{mid}/arguments")["arguments"]:
        has(a, "argument_id", "issue", "position", "argument", "outcome")
    for r in get(client, f"/api/matters/{mid}/related")["related"]:
        has(r, "matter_id", "matter_code", "title", "status")


def test_matter_deadlines(client, open_matter):
    rows = get(client, f"/api/tasks?status=all&matter_id={open_matter['matter_id']}")["items"]
    assert rows
    has(rows[0], "id", "title", "kind", "due", "status", "court", "matter_id", "matter_code",
        "matter_title", "client_name", "owner_name")
    assert rows == sorted(rows, key=lambda r: r["due"])


def test_deadlines_status_filter(client, seeded):
    open_rows = get(client, "/api/tasks?status=open")["items"]
    done_rows = get(client, "/api/tasks?status=done")["items"]
    assert open_rows and done_rows
    assert {r["status"] for r in open_rows} == {"open"}
    assert {r["status"] for r in done_rows} == {"done"}


# ── Documents ─────────────────────────────────────────────────────────────────


def test_documents_list_and_search(client, document):
    body = get(client, "/api/documents?limit=5")
    has(body, "total", "items")
    has(body["items"][0], "document_id", "matter_id", "matter_code", "title", "document_type",
        "author_name", "doc_date", "status", "version")
    hits = get(client, f"/api/documents?q={document['document_id']}")["items"]
    assert document["document_id"] in {d["document_id"] for d in hits}


def test_document_detail_text_versions(client, document):
    did = document["document_id"]
    d = get(client, f"/api/documents/{did}")
    has(d, "title", "document_type", "body", "chunks", "highlight_chunk_id", "matter_info")
    assert d["chunks"] and {"chunk_id", "chunk_index", "text"} <= set(d["chunks"][0])
    chunk = d["chunks"][0]["chunk_id"]
    assert get(client, f"/api/documents/{did}?chunk_id={chunk}")["highlight_chunk_id"] == chunk
    text = get(client, f"/api/documents/{did}/text")
    assert text["text"] and text["chunk_count"] > 0
    assert isinstance(get(client, f"/api/documents/{did}/versions")["versions"], list)


# ── Clients, people, knowledge, teams ─────────────────────────────────────────


def test_clients(client, seeded):
    from app.db.connection import connect

    body = get(client, "/api/clients?limit=5")
    has(body, "total", "items")
    has(body["items"][0], "client_id", "name", "industry", "headquarters")
    with connect() as conn:
        # A client whose notes come from a matter ME can see (seed_demo writes these).
        cid = conn.execute(
            """
            SELECT n.client_id FROM client_notes n JOIN permissions p ON p.matter_id = n.source_matter_id
            WHERE NOT p.restricted OR 'MEM-00016' = ANY(p.allowed_members)
            ORDER BY n.client_id LIMIT 1
            """
        ).fetchone()["client_id"]
    c = get(client, f"/api/clients/{cid}")
    has(c, "client_id", "name", "matters", "notes", "locations", "aliases")
    assert c["notes"], "seeded client notes"
    has(c["notes"][0], "note_id", "kind", "text", "source_matter_id", "source_matter_code", "author_name")
    assert "client_memory" not in c, "hard-coded client memory is gone"


def test_people(client, seeded):
    rows = get(client, "/api/people")["items"]
    has(rows[0], "member_id", "name", "role", "practice_areas", "specializations", "office", "joined_year")
    p = get(client, f"/api/people/{rows[0]['member_id']}")
    has(p, "person", "matters")
    assert client.get("/api/people/MEM-99999", headers=ME).status_code == 404


def test_knowledge_arguments(client, seeded):
    body = get(client, "/api/knowledge/arguments?limit=5")
    has(body, "total", "items")
    has(body["items"][0], "argument_id", "matter_id", "issue", "argument", "matter_code", "matter_title")
    assert body["total"] >= len(body["items"])


def test_fabricated_knowledge_endpoints_removed(client, seeded):
    assert client.get("/api/knowledge/precedents", headers=ME).status_code == 404
    assert client.get("/api/knowledge/clauses", headers=ME).status_code == 404


def test_teams(client, seeded):
    rows = get(client, "/api/teams")["items"]
    assert rows
    has(rows[0], "name", "lawyers", "active_matters")


# ── Chat (no LLM call) ────────────────────────────────────────────────────────


def test_chat_models_and_suggestions(client, seeded):
    models = get(client, "/api/chat/models")
    has(models, "models", "configured")
    for m in models["models"]:
        has(m, "id", "label", "provider", "default")
    assert isinstance(get(client, "/api/chat/suggestions")["suggestions"], list)


def test_chat_session_lifecycle(client, seeded):
    s = client.post("/api/chat/sessions", json={"model": "not-a-real-model"}, headers=ME).json()
    try:
        assert s["title"] is None, "untitled until the first question auto-titles it"
        served = {m["id"] for m in get(client, "/api/chat/models")["models"]}
        assert s["model"] in served or (not served and s["model"] is None)
        assert s["id"] in {x["id"] for x in get(client, "/api/chat/sessions")}
        renamed = client.patch(f"/api/chat/sessions/{s['id']}", json={"title": "Renamed"}, headers=ME).json()
        assert renamed["title"] == "Renamed"
        detail = get(client, f"/api/chat/sessions/{s['id']}")
        has(detail, "session", "messages")
    finally:
        assert client.delete(f"/api/chat/sessions/{s['id']}", headers=ME).status_code == 204
    assert client.get(f"/api/chat/sessions/{s['id']}", headers=ME).status_code == 404


# ── Sidebar: pinned matters ───────────────────────────────────────────────────


def test_pin_lifecycle(client, open_matter):
    mid = open_matter["matter_id"]
    assert client.put(f"/api/matters/{mid}/pin", headers=ME).status_code == 204
    assert client.put(f"/api/matters/{mid}/pin", headers=ME).status_code == 204  # idempotent
    rows = get(client, "/api/matters/pinned")["items"]
    assert mid in {r["matter_id"] for r in rows}
    has(rows[0], "matter_id", "matter_code", "title", "client_name", "status", "restricted")
    assert client.delete(f"/api/matters/{mid}/pin", headers=ME).status_code == 204
    assert mid not in {r["matter_id"] for r in get(client, "/api/matters/pinned")["items"]}
