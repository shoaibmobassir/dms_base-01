"""List endpoints behind the Matters, Documents, Clients, People and Arguments pages.

The extra columns (lead, next deadline, counts) must only ever count what the
caller is allowed to see: an ethical wall must not leak through a number.
"""
from __future__ import annotations

import os

import pytest

from app.db.connection import connect
from tests.conftest import Wall, as_member


def test_matters_list_carries_lead_deadline_and_document_count(client, seeded):
    items = client.get("/api/matters?limit=200", headers=as_member("MEM-00001")).json()["items"]
    assert items
    for key in ("lead_name", "next_deadline_date", "next_deadline_title", "document_count"):
        assert key in items[0]
    with connect() as conn:
        row = conn.execute(
            """
            SELECT m.matter_id, mb.name FROM matters m
            JOIN matter_members mm ON mm.matter_id = m.matter_id AND lower(mm.role_on_matter) = 'lead'
            JOIN members mb ON mb.member_id = mm.member_id
            ORDER BY m.matter_id LIMIT 1
            """
        ).fetchone()
        due = conn.execute(
            "SELECT matter_id, min(due_date) AS due FROM court_deadlines WHERE status = 'open' GROUP BY 1 LIMIT 1"
        ).fetchone()
    by_id = {m["matter_id"]: m for m in client.get("/api/matters?limit=200").json()["items"]}
    if row and row["matter_id"] in by_id:
        assert by_id[row["matter_id"]]["lead_name"] == row["name"]
    if due and due["matter_id"] in by_id:
        assert by_id[due["matter_id"]]["next_deadline_date"] == str(due["due"])


def test_documents_list_filters_and_hides_deleted(client, seeded):
    facets = client.get("/api/documents/facets").json()["document_types"]
    assert facets and all(f["n"] > 0 for f in facets)
    kind = facets[-1]["value"]
    listed = client.get("/api/documents", params={"doc_type": kind, "limit": 200}).json()
    assert listed["total"] == facets[-1]["n"]
    assert {d["document_type"] for d in listed["items"]} == {kind}
    first = listed["items"][0]
    assert "matter_title" in first and "mime_type" in first
    all_docs = client.get("/api/documents?limit=200").json()["items"]
    assert all(d["status"] != "Deleted" for d in all_docs)


def test_client_and_people_counts_respect_the_wall(client, walls: list[Wall]):
    w = walls[0]

    def total_count(member: str) -> int:
        items = client.get("/api/clients?limit=500", headers=as_member(member)).json()["items"]
        return next(c for c in items if c["client_id"] == w.client_id)["total_matters"]

    with connect() as conn:
        hidden = conn.execute(
            """
            SELECT count(*) AS n FROM matters m JOIN permissions p ON p.matter_id = m.matter_id
            WHERE m.client_id = %(c)s AND p.restricted
              AND %(ins)s = ANY(p.allowed_members) AND NOT (%(ins)s = ANY(p.denied_members))
              AND NOT (%(out)s = ANY(p.allowed_members))
            """,
            {"c": w.client_id, "ins": w.insider, "out": w.outsider},
        ).fetchone()["n"]
    assert hidden >= 1
    assert total_count(w.insider) - total_count(w.outsider) == hidden

    def current(member: str, about: str) -> int:
        items = client.get("/api/people", headers=as_member(member)).json()["items"]
        return next(p for p in items if p["member_id"] == about)["current_matters"]

    # The insider is on the walled matter; an outsider looking at the insider must not count it.
    with connect() as conn:
        on_team = conn.execute(
            "SELECT 1 FROM matter_members WHERE matter_id = %s AND member_id = %s", (w.matter_id, w.insider)
        ).fetchone()
        is_open = conn.execute("SELECT lower(coalesce(status,'open')) = 'open' AS o FROM matters WHERE matter_id = %s",
                               (w.matter_id,)).fetchone()["o"]
    if on_team and is_open:
        assert current(w.insider, w.insider) == current(w.outsider, w.insider) + 1


def test_arguments_are_grouped_by_kind(client, seeded):
    body = client.get("/api/knowledge/arguments?limit=100").json()
    kinds = body["kinds"]
    assert body["total"] == sum(kinds.values())
    for kind, n in kinds.items():
        sub = client.get("/api/knowledge/arguments", params={"kind": kind, "limit": 100}).json()
        assert sub["total"] == n
        assert {a["kind"] for a in sub["items"]} == {kind}
    first = body["items"][0]
    for key in ("court", "lead_name", "opened_date", "supporting_documents"):
        assert key in first
    # Disputes come first in the unfiltered list.
    if kinds.get("disputes"):
        assert first["kind"] == "disputes"


def test_document_text_falls_back_to_the_stored_body(client, seeded):
    with connect() as conn:
        row = conn.execute(
            """
            SELECT d.document_id, d.body FROM documents d
            WHERE coalesce(d.body, '') <> '' AND d.status IS DISTINCT FROM 'Deleted'
              AND NOT EXISTS (SELECT 1 FROM chunks c WHERE c.document_id = d.document_id)
              AND NOT EXISTS (SELECT 1 FROM document_blocks b WHERE b.document_id = d.document_id)
            LIMIT 1
            """
        ).fetchone()
    if not row:
        pytest.skip("every document with a body is chunked")
    text = client.get(f"/api/documents/{row['document_id']}/text").json()
    assert text["text"] == row["body"]
    assert text["pages"] == [{"page": 1, "text": row["body"]}]


def test_session_listing_has_matter_code_and_first_question(client, walls: list[Wall]):
    w = walls[0]
    me = as_member(w.insider)
    s = client.post("/api/chat/sessions", json={"matter_id": w.matter_id}, headers=me).json()
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO chat_messages (id, session_id, role, content) VALUES (%s, %s, 'user', %s)",
                (f"msg-{os.urandom(4).hex()}", s["id"], "Who leads this matter?"),
            )
            conn.commit()
        row = next(x for x in client.get("/api/chat/sessions", headers=me).json() if x["id"] == s["id"])
        assert row["matter_code"] == w.matter_code
        assert row["first_question"] == "Who leads this matter?"
    finally:
        client.delete(f"/api/chat/sessions/{s['id']}", headers=me)


def test_purge_removes_an_upload_batch_and_its_documents(seeded, tmp_path, monkeypatch):
    from app.config import settings
    from app.ingest.purge import purge_upload_batches
    from app.ingest.upload_batch import create_upload_batch, process_upload_batch
    from app.storage.object_store import reset_object_store_for_tests

    reset_object_store_for_tests()
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_root", str(tmp_path / "obj"))
    with connect() as conn:
        matter_id = conn.execute("SELECT matter_id FROM matters LIMIT 1").fetchone()["matter_id"]
    uniq = os.urandom(3).hex()
    batch = create_upload_batch(matter_id=matter_id, files=[(f"Purge/doc_{uniq}.txt", f"Purge me {uniq}.".encode())])
    try:
        assert process_upload_batch(batch["batch_id"])["indexed"] == 1
        with connect() as conn:
            doc = conn.execute("SELECT document_id FROM documents WHERE title = %s", (f"doc_{uniq}.txt",)).fetchone()
        assert doc
    finally:
        removed = purge_upload_batches([batch["batch_id"]])
    assert removed == 1
    with connect() as conn:
        assert conn.execute("SELECT 1 FROM documents WHERE document_id = %s", (doc["document_id"],)).fetchone() is None
        assert conn.execute("SELECT 1 FROM chunks WHERE document_id = %s", (doc["document_id"],)).fetchone() is None
        assert conn.execute("SELECT 1 FROM upload_batches WHERE batch_id = %s", (batch["batch_id"],)).fetchone() is None
