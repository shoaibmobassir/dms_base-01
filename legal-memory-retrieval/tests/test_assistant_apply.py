"""Accepting the Assistant's edits changes the document (a clean new version), and dragged-in pages reach the prompt.

Each test uses the throwaway Word document from test_document_editor (a real open matter, deleted afterwards).
"""
from __future__ import annotations

import io

import pytest
from docx import Document
from docx.oxml.ns import qn

from app.chat.models import FileAttachment, MessageRole, PageReference
from app.chat.page_reference import reference_note, resolve_references
from app.chat.store import append_message
from app.db.connection import connect
from app.documents import editing
from tests.conftest import as_member
from tests.test_document_editor import PARAS, _file, _model, doc, people  # noqa: F401  (fixtures)

FEES = next(t for _, t, _ in PARAS if "Fees within" in t)
NOTICE = next(t for _, t, _ in PARAS if "thirty (30)" in t)
FEES_PID = [t for _, t, _ in PARAS].index(FEES)


def _edit(eid, original, proposed, **extra):
    return {"id": eid, "original": original, "proposed": proposed, "status": "pending", "located": True, **extra}


def _message(client, doc_id, member, edits, **group):
    headers = as_member(member)
    session = client.post("/api/chat/sessions", json={}, headers=headers).json()
    event = {"type": "edit_proposals", "document_id": doc_id, "version_id": None, "filename": "Services Agreement.docx",
             "instruction": "Fix the payment terms", "edits": edits, **group}
    with connect() as conn:
        msg = append_message(conn, session["id"], MessageRole.assistant, "Edits proposed.", events=[event])
    return f"/api/chat/sessions/{session['id']}/messages/{msg.id}/edits", headers


def _has_markup(data: bytes) -> bool:
    body = Document(io.BytesIO(data)).element.body
    return bool(list(body.iter(qn("w:ins"))) or list(body.iter(qn("w:del"))))


def _text(data: bytes) -> str:
    return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)


def test_accepting_one_edit_writes_it_into_the_document_without_markup(client, doc, people):
    url, h = _message(client, doc, people["editor"], [_edit("e1", "forty-five (45) days", "sixty (60) days")])
    r = client.patch(f"{url}/e1", json={"status": "accepted"}, headers=h)
    assert r.status_code == 200, r.text
    edit = r.json()
    assert edit["status"] == "accepted" and edit["applied_version_number"] == 2 and edit["applied_from_version_id"]
    data = _file(doc)
    assert "sixty (60) days" in _text(data) and "forty-five" not in _text(data)
    assert not _has_markup(data)  # no struck-through old text, no tracked changes
    items = client.get(f"/api/editor/documents/{doc}/commits", headers=h).json()["items"]
    assert items[0]["message"].startswith("Assistant: Fix the payment terms") and items[0]["is_clean"]


def test_accept_all_is_one_version_and_places_edits_by_paragraph_or_by_passage(client, doc, people):
    edits = [
        _edit("e1", FEES, FEES.replace("forty-five (45)", "sixty (60)"), op="replace", pid=FEES_PID),
        _edit("e2", "thirty (30) days", "sixty (60) days"),
    ]
    url, h = _message(client, doc, people["editor"], edits)
    r = client.patch(url, json={"status": "accepted", "document_id": doc}, headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["updated"] == 2 and out["failed"] == {} and out["version_number"] == 2
    text = _text(_file(doc))
    assert FEES.replace("forty-five (45)", "sixty (60)") in text and "sixty (60) days' written notice" in text
    assert _model(client, doc, people["editor"])["version_number"] == 2


def test_cards_quoting_the_old_section_label_still_apply_without_writing_it(client, doc, people):
    """Cards made from text indexed with the old "SECTION " heading label (the reported CTO agreement case)."""
    edits = [_edit("e1", "SECTION Article 2 — Fees", "SECTION Article 3 — Fees"),
             _edit("e2", "SECTION Article 1 — Term", "Article 1 — Duration")]
    url, h = _message(client, doc, people["editor"], edits)
    r = client.patch(url, json={"status": "accepted", "document_id": doc}, headers=h)
    assert r.status_code == 200 and r.json()["failed"] == {}, r.text
    text = _text(_file(doc))
    assert "Article 3 — Fees" in text and "Article 1 — Duration" in text and "SECTION" not in text


def test_an_edit_whose_passage_is_gone_stays_pending_and_changes_nothing(client, doc, people):
    url, h = _message(client, doc, people["editor"], [_edit("e1", "a clause that is not in this document", "x")])
    r = client.patch(f"{url}/e1", json={"status": "accepted"}, headers=h)
    assert r.status_code == 409 and "not found" in r.json()["detail"]
    assert _model(client, doc, people["editor"])["version_number"] == 1
    assert not _has_markup(_file(doc))


def test_an_edit_already_in_the_document_cannot_be_rejected_from_the_card(client, doc, people):
    url, h = _message(client, doc, people["editor"], [_edit("e1", "forty-five (45) days", "sixty (60) days")])
    assert client.patch(f"{url}/e1", json={"status": "accepted"}, headers=h).status_code == 200
    r = client.patch(f"{url}/e1", json={"status": "rejected"}, headers=h)
    assert r.status_code == 409 and "History" in r.json()["detail"]


def test_accepting_twice_does_not_write_a_second_version(client, doc, people):
    url, h = _message(client, doc, people["editor"], [_edit("e1", "forty-five (45) days", "sixty (60) days")])
    client.patch(f"{url}/e1", json={"status": "accepted"}, headers=h)
    again = client.patch(f"{url}/e1", json={"status": "accepted"}, headers=h)
    assert again.status_code == 200 and again.json()["applied_version_number"] == 2
    assert _model(client, doc, people["editor"])["version_number"] == 2


def test_export_after_accepting_is_a_redline_and_writes_no_second_version(client, doc, people, monkeypatch):
    stored: dict = {}

    def fake_store(data, title, ext, mime, member):
        stored["data"] = data
        return {"document_id": "GEN-1", "filename": f"{title}.docx"}

    monkeypatch.setattr("app.chat.tools.generation_tools.store_generated_bytes", fake_store)
    url, h = _message(client, doc, people["editor"], [_edit("e1", "forty-five (45) days", "sixty (60) days")])
    client.patch(f"{url}/e1", json={"status": "accepted"}, headers=h)
    r = client.post(f"{url}/export", params={"document_id": doc}, headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["redline"] and out["applied"] == 1 and not out["tracked_in_original"]
    assert _has_markup(stored["data"])  # the redline shows the change as tracked changes...
    assert _model(client, doc, people["editor"])["version_number"] == 2  # ...the document itself is untouched
    assert not _has_markup(_file(doc))


def test_recommendations_on_a_read_only_group_are_only_recorded(client, doc, people):
    url, h = _message(client, doc, people["editor"], [_edit("e1", "forty-five (45) days", "sixty (60) days")], read_only=True)
    r = client.patch(f"{url}/e1", json={"status": "accepted"}, headers=h)
    assert r.status_code == 200 and "applied_version_id" not in r.json()
    assert _model(client, doc, people["editor"])["version_number"] == 1


def test_a_viewer_without_edit_rights_cannot_apply(client, doc, people):
    url, h = _message(client, doc, people["outsider"], [_edit("e1", "forty-five (45) days", "x")])
    r = client.patch(f"{url}/e1", json={"status": "accepted"}, headers=h)
    assert r.status_code in (403, 404)
    assert _model(client, doc, people["editor"])["version_number"] == 1


# ── pages dragged into the Assistant ─────────────────────────────────────────

def _ref(doc_id, unit="part", number=1, **kw):
    return FileAttachment(filename="Services Agreement.docx", document_id=doc_id,
                          reference=PageReference(unit=unit, number=number, **kw))


def test_a_dragged_part_reaches_the_prompt_with_its_text(doc, people):
    editing.wait_for_indexing()
    with connect() as conn:
        refs = resolve_references(conn, [_ref(doc)], people["editor"])
    assert len(refs) == 1 and refs[0]["unit"] == "part" and refs[0]["number"] == 1
    note = reference_note(refs)
    assert "Part 1 of Services Agreement.docx" in note and f"document {doc}" in note
    assert "Services Agreement" in refs[0]["text"]


def test_a_reference_to_a_document_the_member_cannot_read_is_dropped(seeded):
    with connect() as conn:
        admins = {r["member_id"] for r in conn.execute(
            "SELECT DISTINCT member_id FROM member_roles WHERE role_key IN ('firm_admin', 'risk_compliance')")}
        row = conn.execute("""SELECT d.document_id, d.matter_id FROM documents d JOIN matter_access a USING (matter_id)
                              WHERE a.mode = 'restricted' ORDER BY d.document_id LIMIT 1""").fetchone()
        if row is None:
            pytest.skip("no restricted matter")
        team = [r["member_id"] for r in conn.execute("SELECT member_id FROM matter_members WHERE matter_id = %s", (row["matter_id"],))]
        stranger = next((r["member_id"] for r in conn.execute("SELECT member_id FROM members ORDER BY member_id")
                         if r["member_id"] not in team and r["member_id"] not in admins), None)
        if stranger is None:
            pytest.skip("no member outside the restricted matter")
        assert resolve_references(conn, [_ref(row["document_id"])], stranger) == []


def test_no_references_means_no_note():
    assert reference_note([]) == ""
    with connect() as conn:
        assert resolve_references(conn, [FileAttachment(filename="a.docx", document_id="DOC-X")], None) == []


def test_the_current_headings_of_documents_in_play_reach_the_prompt(doc, people):
    from app.chat.page_reference import outline_note
    from app.documents import reindex_current_version

    editing.wait_for_indexing()
    with connect() as conn:  # the fixture stores its text one line per paragraph; extraction separates them by a blank line
        conn.execute("UPDATE document_versions SET body = %s WHERE document_id = %s",
                     ("\n\n".join(t for _, t, _ in PARAS), doc))
        conn.commit()
    reindex_current_version(doc)
    with connect() as conn:
        note = outline_note(conn, [doc, doc], people["editor"])
    assert "CURRENT HEADINGS" in note and "Services Agreement.docx" in note
    assert "Article 1 — Term" in note and "Article 2 — Fees" in note
    assert note.count("Services Agreement.docx") == 1  # each document once
