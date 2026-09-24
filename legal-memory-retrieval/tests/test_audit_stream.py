"""Audit stream (production plan 08, step B): what is recorded, who can read it,
and that it is append-only and tamper-evident. Runs against the seeded database."""
from __future__ import annotations

import io
import json

import psycopg
import pytest

from app.audit import events as audit
from app.db.connection import connect
from conftest import Wall, as_member

ADMIN = as_member("MEM-00011")  # seed_demo makes the Knowledge Manager an administrator


def _last(action: str, **where) -> dict | None:
    clauses = ["action = %(action)s"] + [f"{k} = %({k})s" for k in where]
    with connect() as conn:
        return conn.execute(
            f"SELECT * FROM audit_events WHERE {' AND '.join(clauses)} ORDER BY seq DESC LIMIT 1",
            {"action": action, **where},
        ).fetchone()


def _seq() -> int:
    with connect() as conn:
        return conn.execute("SELECT COALESCE(max(seq), 0) AS s FROM audit_events").fetchone()["s"]


def test_document_view_and_denial_recorded(client, walls: list[Wall]):
    w = walls[0]
    before = _seq()
    client.get(f"/api/documents/{w.document_id}", headers=as_member(w.insider))
    client.get(f"/api/documents/{w.document_id}", headers=as_member(w.outsider))
    ok = _last("document.view", member_id=w.insider, object_id=w.document_id)
    denied = _last("document.view", member_id=w.outsider, object_id=w.document_id)
    assert ok["seq"] > before and ok["outcome"] == "success" and ok["matter_id"] == w.matter_id
    assert denied["seq"] > before and denied["outcome"] == "denied" and denied["matter_id"] is None  # no leak of the matter


def test_download_recorded(client, seeded):
    before = _seq()
    doc = "DOC-E9058749C1"  # Acme SPA (seed_acme.py) has an original file
    resp = client.get(f"/api/documents/{doc}/download", headers=as_member("MEM-00001"))
    if resp.status_code != 200:
        pytest.skip("Acme matter not seeded (scripts/seed_acme.py)")
    row = _last("document.download", object_id=doc)
    assert row["seq"] > before and row["detail"]["version_id"]


def test_retrieval_recorded_with_query(client, seeded):
    before = _seq()
    client.post("/api/retrieval", json={"query": "audit probe cure period", "k": 3}, headers=as_member("MEM-00016"))
    row = _last("retrieval", member_id="MEM-00016")
    assert row["seq"] > before and row["detail"]["query"] == "audit probe cure period"


def test_upload_recorded(client, walls: list[Wall]):
    w = walls[0]
    before = _seq()
    resp = client.post(
        "/api/uploads/batches", data={"matter_id": w.matter_id},
        files=[("files", ("audit-probe.txt", io.BytesIO(b"audit probe"), "text/plain"))],
        headers=as_member(w.insider),
    )
    assert resp.status_code == 200
    row = _last("upload.create", member_id=w.insider)
    assert row["seq"] > before and row["matter_id"] == w.matter_id
    _delete_batch(resp.json()["batch_id"])


def _delete_batch(batch_id: str) -> None:
    from app.storage.object_store import get_object_store

    with connect() as conn, conn.transaction():
        for f in conn.execute("SELECT storage_uri FROM upload_batch_files WHERE batch_id = %s", (batch_id,)).fetchall():
            get_object_store().delete(f["storage_uri"])
        job = conn.execute("SELECT ingest_job_id FROM upload_batches WHERE batch_id = %s", (batch_id,)).fetchone()
        conn.execute("DELETE FROM upload_batch_files WHERE batch_id = %s", (batch_id,))
        conn.execute("DELETE FROM upload_batches WHERE batch_id = %s", (batch_id,))
        conn.execute("DELETE FROM ingest_items WHERE job_id = %s", (job["ingest_job_id"],))
        conn.execute("DELETE FROM ingest_jobs WHERE job_id = %s", (job["ingest_job_id"],))


def test_rejected_api_key_recorded(client, monkeypatch, seeded):
    from app.config import settings

    monkeypatch.setattr(settings, "auth_enabled", True)
    before = _seq()
    assert client.get("/api/matters", headers={"X-Api-Key": "not-a-key"}).status_code == 401
    row = _last("auth.request", outcome="denied")
    assert row["seq"] > before and row["detail"]["reason"] == "invalid api key"


def test_export_is_admin_only(client, seeded):
    assert client.get("/api/audit/events", headers=as_member("MEM-00001")).status_code == 403
    assert client.get("/api/audit/events/verify", headers=as_member("MEM-00001")).status_code == 403
    assert _last("audit.read", member_id="MEM-00001")["outcome"] == "denied"


def test_export_filters_and_jsonl(client, walls: list[Wall]):
    w = walls[0]
    client.get(f"/api/documents/{w.document_id}", headers=as_member(w.outsider))
    page = client.get(f"/api/audit/events?action=document.&outcome=denied&member={w.outsider}", headers=ADMIN).json()
    assert page["events"] and all(e["outcome"] == "denied" and e["action"].startswith("document.") for e in page["events"])
    resp = client.get("/api/audit/events?format=jsonl&limit=5", headers=ADMIN)
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in resp.text.splitlines()]
    assert len(lines) == 5 and {"seq", "hash", "prev_hash", "action"} <= set(lines[0])
    assert _last("audit.export", member_id="MEM-00011")


def test_chain_verifies(client, seeded):
    body = client.get("/api/audit/events/verify", headers=ADMIN).json()
    assert body["intact"] is True and body["events"] > 0


def test_append_only():
    with connect() as conn:
        for sql in ("UPDATE audit_events SET action = 'x'", "DELETE FROM audit_events", "TRUNCATE audit_events"):
            with pytest.raises(psycopg.errors.RaiseException):
                conn.execute(sql)
            conn.rollback()


def test_tampering_is_detected():
    """Even with triggers disabled (owner-level access), an edit breaks the chain.
    Done inside a transaction that is rolled back, so the real stream is untouched."""
    audit.record("test.tamper_probe", member_id="MEM-00001", detail={"n": 1})
    with connect() as conn:
        conn.execute("ALTER TABLE audit_events DISABLE TRIGGER trg_audit_no_update")
        seq = conn.execute("SELECT max(seq) AS s FROM audit_events WHERE action = 'test.tamper_probe'").fetchone()["s"]
        conn.execute("UPDATE audit_events SET member_id = 'MEM-00002' WHERE seq = %s", (seq,))
        result = audit.verify_chain(conn)
        conn.rollback()
    assert result["intact"] is False and result["first_broken_seq"] == seq
    assert audit.verify_chain()["intact"] is True


def test_matter_activity_feed(client, walls: list[Wall]):
    w = walls[0]
    assert client.get(f"/api/matters/{w.matter_id}/activity", headers=as_member(w.outsider)).status_code == 404
    items = client.get(f"/api/matters/{w.matter_id}/activity", headers=as_member(w.insider)).json()["items"]
    assert all(i["action"] in ("upload.create", "upload.process", "chat.prompt", "document.download", "export.bundle", "document.version") for i in items)
