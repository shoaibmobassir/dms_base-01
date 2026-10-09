"""edit_document end to end: tool → edit cards → bulk accept → tracked changes in the ORIGINAL .docx.

The planning model is replaced by fixed operations; version creation and storage are captured,
not written, so the shared seeded database is left unchanged.
"""
from __future__ import annotations

import io

import pytest
from docx import Document

from app.chat.models import MessageRole
from app.chat.store import append_message
from app.chat.tools.document_tools import DocEntry
from app.chat.tools.edit_tools import edit_document_tool
from app.db.connection import connect
from app.drafting.docx_tracked import view
from app.editing import engine
from app.editing.document import load_editable
from tests.conftest import as_member

SPA = "DOC-E9058749C1"


@pytest.fixture
def spa(seeded):
    with connect() as conn:
        doc = load_editable(conn, SPA, None)
    if doc is None or doc.source != "docx":
        pytest.skip("Acme SPA .docx not ingested (scripts/seed_acme.py)")
    return doc


def test_tool_proposes_paragraph_edits_from_the_original_docx(spa, monkeypatch):
    target = next(i for i, t in enumerate(spa.paragraphs) if "Long Stop Date" in t)
    monkeypatch.setattr(engine, "plan_edits", lambda paras, instr, llm=None: engine.EditPlan(
        ops=[{"op": "replace", "pid": target, "text": paras[target].replace("Long Stop Date", "Longstop Date")}]))
    import app.editing.engine as eng_mod
    monkeypatch.setattr(eng_mod, "plan_edits", engine.plan_edits)
    with connect() as conn:
        result, events = edit_document_tool({"doc_id": "doc-0", "instruction": "Rename Long Stop Date"},
                                            {"doc-0": DocEntry("doc-0", SPA, "Share Purchase Agreement.docx")}, conn, None)
    assert result["proposed"] == 1 and events[0]["anchoring"] == "paragraph" and events[0]["source"] == "docx"
    e = events[0]["edits"][0]
    assert e["pid"] == target and "Longstop Date" in e["proposed"] and e["status"] == "pending"


def test_legacy_accepted_edits_export_writes_tracked_changes_into_the_original(client, spa, monkeypatch):
    target = next(i for i, t in enumerate(spa.paragraphs) if "Long Stop Date" in t)
    event = {
        "type": "edit_proposals", "document_id": SPA, "version_id": spa.version_id, "filename": "SPA.docx",
        "anchoring": "paragraph", "source": "docx", "instruction": "Rename Long Stop Date",
        "edits": [
            {"id": "e1", "op": "replace", "pid": target, "original": spa.paragraphs[target],
             "proposed": spa.paragraphs[target].replace("Long Stop Date", "Longstop Date"), "status": "accepted"},
            {"id": "e2", "op": "insert_after", "pid": target, "original": "", "proposed": "A new sentence.",
             "status": "accepted"},
        ],
    }
    headers = as_member("MEM-00007")
    session = client.post("/api/chat/sessions", json={}, headers=headers).json()
    with connect() as conn:
        msg = append_message(conn, session["id"], MessageRole.assistant, "Edits proposed.", events=[event])
    captured: dict = {}

    def fake_version(document_id, body, **kw):
        captured.update(document_id=document_id, body=body, **kw)
        return {"version_id": "VER-TEST", "version_label": "v9.0"}

    from app.storage import object_store

    real_store = object_store.get_object_store()

    class FakeStore:  # reads the real originals; writes are captured
        def get(self, uri):
            return real_store.get(uri)

        def put(self, key, data, content_type=None):
            captured["clean_docx"] = data
            return f"memory://{key}"

    monkeypatch.setattr("app.documents.create_version", fake_version)
    monkeypatch.setattr(object_store, "get_object_store", lambda: FakeStore())
    stored: dict = {}

    def fake_store(data, title, ext, mime, member):
        stored["data"] = data
        return {"document_id": "GEN-1", "filename": f"{title}.docx"}

    monkeypatch.setattr("app.chat.tools.generation_tools.store_generated_bytes", fake_store)

    url = f"/api/chat/sessions/{session['id']}/messages/{msg.id}/edits"
    # Messages accepted before accepting wrote into the document (no applied version) still export as before.
    r = client.post(f"{url}/export?document_id={SPA}", headers=headers)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["tracked_in_original"] and out["applied"] == 2 and out["version_id"] == "VER-TEST"
    accepted = view(stored["data"], accept=True)
    rejected = view(stored["data"], accept=False)
    assert "Longstop Date" in accepted[target] and accepted[target + 1] == "A new sentence."
    assert rejected == [p for p in spa.paragraphs]
    clean = [p.text for p in Document(io.BytesIO(captured["clean_docx"])).paragraphs]
    assert clean == accepted and captured["storage_uri"].startswith("memory://")
    assert "Longstop Date" in captured["body"]


def test_export_refuses_edits_proposed_on_an_older_version(client, spa):
    event = {"type": "edit_proposals", "document_id": SPA, "version_id": "VER-OLD", "filename": "SPA.docx",
             "anchoring": "paragraph", "source": "docx",
             "edits": [{"id": "e1", "op": "replace", "pid": 0, "original": "x", "proposed": "y", "status": "accepted"}]}
    headers = as_member("MEM-00007")
    session = client.post("/api/chat/sessions", json={}, headers=headers).json()
    with connect() as conn:
        msg = append_message(conn, session["id"], MessageRole.assistant, "Edits.", events=[event])
    r = client.post(f"/api/chat/sessions/{session['id']}/messages/{msg.id}/edits/export?document_id={SPA}", headers=headers)
    if spa.version_id:
        assert r.status_code == 409
