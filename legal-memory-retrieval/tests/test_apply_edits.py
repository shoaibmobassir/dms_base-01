"""The Assistant's edits land in the document at once, and Undo restores it (plan 21, G-A).

Uses the throwaway Word document from test_document_editor (a real open matter, deleted afterwards).
"""
from __future__ import annotations

import io

from docx import Document
from docx.oxml.ns import qn

from app.chat.agent import _apply_now
from app.chat.apply_edits import history_note, undo_latest_in_conversation
from app.chat.models import MessageRole
from app.chat.store import append_message
from app.db.connection import connect
from tests.conftest import as_member
from tests.test_document_editor import PARAS, _file, doc, people  # noqa: F401  (fixtures)

TEXTS = [t for _, t, _ in PARAS]
FEES = next(t for t in TEXTS if "Fees within" in t)
FEES_PID = TEXTS.index(FEES)


def _event(doc_id, edits, **extra):
    return {"type": "edit_proposals", "document_id": doc_id, "filename": "Services Agreement.docx",
            "instruction": "Tighten the payment terms", "edits": edits, **extra}


def _edit(eid, original, proposed, **extra):
    return {"id": eid, "original": original, "proposed": proposed, "status": "pending", "located": True, **extra}


def _text(doc_id) -> list[str]:
    return [p.text for p in Document(io.BytesIO(_file(doc_id))).paragraphs]


def _markup(doc_id) -> bool:
    body = Document(io.BytesIO(_file(doc_id))).element.body
    return bool(list(body.iter(qn("w:ins"))) or list(body.iter(qn("w:del"))))


def test_an_edit_is_written_into_the_document_at_once(doc, people):
    turn: dict[str, str] = {}
    result, events = _apply_now({"proposed": 1, "note": "cards"}, [_event(doc, [_edit("e1", "forty-five (45) days", "sixty (60) days")])],
                                {}, people["editor"], turn)
    ev = events[0]
    assert ev["type"] == "edits_applied" and ev["version_number"] == 2 and ev["changes"][0]["after"] == "sixty (60) days"
    assert ev["changes"][0]["segments"]  # old → new, word by word
    assert result["applied"] is True and "version 2" in result["note"] and "Undo" in result["note"]
    assert "sixty (60) days" in "\n".join(_text(doc)) and not _markup(doc)


def test_changes_in_one_answer_share_the_version_undo_goes_back_to(doc, people):
    turn: dict[str, str] = {}
    first = _model_version(doc, people)
    _, ev1 = _apply_now({}, [_event(doc, [_edit("e1", "forty-five (45) days", "sixty (60) days")])], {}, people["editor"], turn)
    _, ev2 = _apply_now({}, [_event(doc, [_edit("e2", "thirty (30) days", "sixty (60) days")])], {}, people["editor"], turn)
    assert ev1[0]["from_version_id"] == ev2[0]["from_version_id"] == first
    assert ev2[0]["version_number"] == 3


def _model_version(doc, people):
    with connect() as conn:
        return conn.execute("SELECT current_version_id FROM documents WHERE document_id = %s", (doc,)).fetchone()["current_version_id"]


def _first_version(doc):
    with connect() as conn:
        return conn.execute("SELECT version_id FROM document_versions WHERE document_id = %s AND version_number = 1",
                            (doc,)).fetchone()["version_id"]


def _message(client, doc, member, events):
    h = as_member(member)
    session = client.post("/api/chat/sessions", json={}, headers=h).json()
    with connect() as conn:
        msg = append_message(conn, session["id"], MessageRole.assistant, "Changed.", events=events)
    return session["id"], msg.id, h


def test_undo_restores_the_text_from_before_the_answer(client, doc, people):
    turn: dict[str, str] = {}
    _, e1 = _apply_now({}, [_event(doc, [_edit("e1", "forty-five (45) days", "sixty (60) days")])], {}, people["editor"], turn)
    _, e2 = _apply_now({}, [_event(doc, [_edit("e2", "thirty (30) days", "ninety (90) days")])], {}, people["editor"], turn)
    sid, mid, h = _message(client, doc, people["editor"], e1 + e2)
    r = client.post(f"/api/chat/sessions/{sid}/messages/{mid}/edits/undo", json={"document_id": doc}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["restored_version_number"] == 1 and r.json()["version_number"] == 4
    restored = _text(doc)
    assert FEES in restored and "thirty (30) days' written notice" in "\n".join(restored)
    assert "sixty" not in "\n".join(restored) and "ninety" not in "\n".join(restored)
    stored = client.get(f"/api/chat/sessions/{sid}", headers=h).json()["messages"][-1]["events"]
    assert all(e.get("undone_version_number") == 4 for e in stored if e["type"] == "edits_applied")
    again = client.post(f"/api/chat/sessions/{sid}/messages/{mid}/edits/undo", json={"document_id": doc}, headers=h)
    assert again.status_code == 404


def test_undo_is_refused_when_the_document_changed_since(client, doc, people):
    _, e1 = _apply_now({}, [_event(doc, [_edit("e1", "forty-five (45) days", "sixty (60) days")])], {}, people["editor"], {})
    _apply_now({}, [_event(doc, [_edit("e2", "thirty (30) days", "ninety (90) days")])], {}, people["editor"], {})  # a later answer
    sid, mid, h = _message(client, doc, people["editor"], e1)
    r = client.post(f"/api/chat/sessions/{sid}/messages/{mid}/edits/undo", json={"document_id": doc}, headers=h)
    assert r.status_code == 409 and "History" in r.json()["detail"]


def test_the_undo_tool_undoes_the_latest_answer_and_says_when_there_is_nothing(client, doc, people):
    _, e1 = _apply_now({}, [_event(doc, [_edit("e1", "forty-five (45) days", "sixty (60) days")])], {}, people["editor"], {})
    sid, _mid, _h = _message(client, doc, people["editor"], e1)
    out = undo_latest_in_conversation(sid, doc, people["editor"])
    assert out["undone"] is True and out["restored_version_number"] == 1
    assert FEES in _text(doc)
    nothing = undo_latest_in_conversation(sid, doc, people["editor"])
    assert nothing["undone"] is False and "do not claim" in nothing["reason"]


def test_a_paragraph_already_in_the_document_is_not_added_twice(doc, people):
    new = "Interest on late payment accrues daily."
    edits = [_edit("i1", "", new, op="insert_after", pid=FEES_PID, anchor=FEES),
             _edit("i2", "", new, op="insert_after", pid=FEES_PID, anchor=FEES)]
    result, events = _apply_now({}, [_event(doc, edits)], {}, people["editor"], {})
    assert _text(doc).count(new) == 1
    assert events[0]["failed"][0]["reason"] == "that paragraph is already in the document"
    again, _ = _apply_now({}, [_event(doc, [_edit("i3", "", new, op="insert_after", pid=FEES_PID, anchor=FEES)])], {},
                          people["editor"], {})
    assert again.get("applied") is not True and _text(doc).count(new) == 1


def test_an_insert_follows_its_anchor_after_earlier_changes_moved_it(doc, people):
    edits = [_edit("d1", TEXTS[1], "", op="delete", pid=1),  # removes a paragraph above, shifting everything up
             _edit("i1", "", "A new closing sentence.", op="insert_after", pid=FEES_PID, anchor=FEES)]
    _apply_now({}, [_event(doc, edits[:1])], {}, people["editor"], {})
    _apply_now({}, [_event(doc, edits[1:])], {}, people["editor"], {})
    text = _text(doc)
    assert text[text.index(FEES) + 1] == "A new closing sentence."


def test_a_reader_without_edit_rights_gets_suggestions_not_changes(doc, people):
    result, events = _apply_now({}, [_event(doc, [_edit("e1", "forty-five (45) days", "sixty (60) days")])], {},
                                people["outsider"], {})
    assert events[0]["type"] == "edit_proposals" and "could NOT be written" in result["note"]
    assert "forty-five (45) days" in "\n".join(_text(doc))
    assert _model_version(doc, people) == _first_version(doc)


def test_a_read_only_group_is_left_as_recommendations(doc, people):
    result, events = _apply_now({}, [_event(doc, [_edit("e1", "forty-five (45) days", "x")], read_only=True)], {},
                                people["editor"], {})
    assert events[0]["type"] == "edit_proposals" and "applied" not in result


def test_earlier_answers_are_summarised_for_the_model():
    note = history_note([
        {"type": "edits_applied", "document_id": "D", "filename": "CTO.docx", "version_number": 5, "changes": [{}, {}]},
        {"type": "edits_applied", "document_id": "D", "filename": "CTO.docx", "version_number": 6, "changes": [{}],
         "undone_version_id": "V7", "undone_version_number": 7},
        {"type": "edit_proposals", "filename": "Old.docx", "edits": [{"status": "accepted"}, {"status": "pending"}]},
        {"type": "comments_added", "filename": "A.pdf", "comments": [{}, {}, {}]},
    ])
    assert "[Changed CTO.docx → v5: 2 change(s), in the document]" in note
    assert "undone as v7" in note and "1 accepted, 1 pending, not applied" in note and "Added 3 comment(s)" in note
