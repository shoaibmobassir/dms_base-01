"""A throwaway Word document for browser checks of the History view (plan 21, C3).

    python evals/history_ui_fixture.py create --base http://127.0.0.1:8021     # prints {"document_id": ..., "member": ...}
    python evals/history_ui_fixture.py delete DOC-XXXXXXXXXX

``create`` makes an employment-style agreement in an open matter and saves two edits through the real editor API, like
the report: the fixed compensation INR 1,20,00,000 -> 1,50,00,000 and the start date 1 October -> 7 October. The
document and its rows are removed by ``delete``.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import uuid
from pathlib import Path

import httpx
from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.connection import connect  # noqa: E402
from app.documents import create_version  # noqa: E402
from app.storage.object_store import get_object_store  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PARAS = [
    "Executive Employment Agreement",
    "2. Appointment and Term",
    "The Company appoints the Executive as Chief Technology Officer with effect from 1 October 2026. "
    "The appointment continues until terminated in accordance with Clause 8.",
    "5. Remuneration",
    "The Executive shall receive fixed annual compensation of INR 1,20,00,000 and shall be eligible for grants under "
    "the Company's Employee Stock Option Plan, subject to the plan rules and vesting over four years with a one-year cliff.",
]


def _member_and_matter() -> tuple[str, str, str]:
    with connect() as conn:
        admins = {r["member_id"] for r in conn.execute(
            "SELECT DISTINCT member_id FROM member_roles WHERE role_key IN ('firm_admin', 'risk_compliance')")}
        for m in conn.execute("""SELECT m.matter_id, m.client_id FROM matters m JOIN matter_access a USING (matter_id)
                                 WHERE a.mode = 'open' ORDER BY m.matter_id""").fetchall():
            team = [r["member_id"] for r in conn.execute(
                "SELECT member_id FROM matter_members WHERE matter_id = %s ORDER BY member_id", (m["matter_id"],))]
            editors = [t for t in team if t not in admins]
            if editors:
                return editors[0], m["matter_id"], m["client_id"]
    sys.exit("no open matter with a non-admin team member")


def create(base: str) -> dict:
    member, matter, client = _member_and_matter()
    doc = Document()
    for text in PARAS:
        doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    data = buf.getvalue()
    doc_id = f"DOC-{uuid.uuid4().hex[:10].upper()}"
    uri = get_object_store().put(f"tests/{doc_id}/v1.docx", data, content_type=DOCX)
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (document_id, matter_id, client_id, title, document_type, body, mime_type, source_uri) "
            "VALUES (%s, %s, %s, 'Employment Agreement - History check.docx', 'Agreement', '', %s, %s)",
            (doc_id, matter, client, DOCX, uri))
        conn.commit()
    create_version(document_id=doc_id, body="\n".join(PARAS), author_name="Test", source="upload", version_status="draft",
                   storage_uri=uri, change_summary="First draft")
    h = {"X-Member-Id": member}
    with httpx.Client(base_url=base, headers=h, timeout=60) as c:
        def save(pid: int, text: str, note: str) -> None:
            model = c.get(f"/api/editor/documents/{doc_id}").json()
            r = c.post(f"/api/editor/documents/{doc_id}/save", json={
                "base_version_id": model["base_version_id"], "ops": [{"op": "replace", "pid": pid, "text": text}], "note": note})
            r.raise_for_status()
        save(4, PARAS[4].replace("1,20,00,000", "1,50,00,000"), "Raise fixed compensation to INR 1,50,00,000")
        save(2, PARAS[2].replace("1 October", "7 October"), "Move the start date to 7 October")
    return {"document_id": doc_id, "member": member}


def delete(doc_id: str) -> None:
    from app.documents.editing import wait_for_indexing

    wait_for_indexing()
    with connect() as conn:
        for table in ("document_events", "document_drafts", "document_locks", "chunks", "document_blocks", "version_diffs",
                      "document_revision_authors"):
            conn.execute(f"DELETE FROM {table} WHERE document_id = %s", (doc_id,))
        conn.execute("UPDATE documents SET current_version_id = NULL WHERE document_id = %s", (doc_id,))
        conn.execute("DELETE FROM document_versions WHERE document_id = %s", (doc_id,))
        conn.execute("DELETE FROM documents WHERE document_id = %s", (doc_id,))
        conn.commit()


def copy(source_id: str, member: str) -> dict:
    """A throwaway copy of an existing Word document (its current file, same matter), so a live test never changes the
    real one. Indexed like an upload, through the same extractor."""
    from app.ingest.extractors.dispatch import extract_from_bytes

    with connect() as conn:
        src = conn.execute(
            "SELECT d.matter_id, d.client_id, d.title, v.storage_uri FROM documents d "
            "JOIN document_versions v ON v.version_id = d.current_version_id WHERE d.document_id = %s", (source_id,)).fetchone()
    data = get_object_store().get(src["storage_uri"])
    doc_id = f"DOC-{uuid.uuid4().hex[:10].upper()}"
    title = f"{Path(src['title']).stem} (test copy).docx"
    uri = get_object_store().put(f"tests/{doc_id}/v1.docx", data, content_type=DOCX)
    extracted = extract_from_bytes(title, data)
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (document_id, matter_id, client_id, title, document_type, body, mime_type, source_uri) "
            "VALUES (%s, %s, %s, %s, 'Agreement', '', %s, %s)", (doc_id, src["matter_id"], src["client_id"], title, DOCX, uri))
        conn.commit()
    create_version(document_id=doc_id, body=extracted.text, author_name="Test", source="upload", version_status="draft",
                   storage_uri=uri, change_summary="Copy for a live test", page_spans=extracted.pages)
    with connect() as conn:
        conn.execute("UPDATE document_versions SET mime_type = %s WHERE document_id = %s", (DOCX, doc_id))
        conn.commit()
    from app.embeddings.pending import embed_pending_chunks

    embed_pending_chunks([doc_id])
    return {"document_id": doc_id, "member": member, "title": title}


def chat_edits(doc_id: str, member: str, base: str) -> dict:
    """A conversation whose answer proposes two renumbering edits to the document (the pasted report's case), as the
    Assistant's cards would show them. Returns the session to open at /chat/<session_id>."""
    from app.chat.models import MessageRole
    from app.chat.store import append_message

    with httpx.Client(base_url=base, headers={"X-Member-Id": member}, timeout=60) as c:
        session = c.post("/api/chat/sessions", json={}).json()
    event = {
        "type": "edit_proposals", "document_id": doc_id, "version_id": None, "filename": "Employment Agreement - History check.docx",
        "instruction": "Renumber the sections", "edits": [
            {"id": "n1", "original": "5. Remuneration", "proposed": "3. Remuneration", "reason": "Renumber to sequential order.",
             "page": 1, "located": True, "status": "pending"},
            {"id": "n2", "original": "7. Non-Solicitation", "proposed": "4. Non-Solicitation",
             "reason": "Renumber to sequential order.", "page": 1, "located": True, "status": "pending"}]}
    with connect() as conn:
        append_message(conn, session["id"], MessageRole.user, "fix the numbering on this page")
        append_message(conn, session["id"], MessageRole.assistant, "I renumbered the sections.", events=[event])
        conn.commit()
    return {"session_id": session["id"]}


def delete_session(session_id: str) -> None:
    from app.chat.store import delete_session as remove

    with connect() as conn:
        remove(conn, session_id)
        conn.commit()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["create", "delete", "chat-edits", "delete-session", "copy"])
    ap.add_argument("document_id", nargs="?")
    ap.add_argument("--member", default="")
    ap.add_argument("--base", default="http://127.0.0.1:8021")
    a = ap.parse_args()
    if a.action == "create":
        print(json.dumps(create(a.base)))
    elif a.action == "copy":
        print(json.dumps(copy(a.document_id, a.member)))
    elif a.action == "chat-edits":
        print(json.dumps(chat_edits(a.document_id, a.member, a.base)))
    elif a.action == "delete-session":
        delete_session(a.document_id)
        print("deleted", a.document_id)
    else:
        delete(a.document_id)
        print("deleted", a.document_id)
