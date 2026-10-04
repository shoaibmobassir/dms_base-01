"""A conversation exported to Word."""
from __future__ import annotations

import io

from docx import Document

from app.chat.export import conversation_to_docx
from tests.conftest import as_member

ME = "MEM-00001"


def _text(data: bytes) -> str:
    return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)


def test_docx_has_turns_bold_lists_and_sources():
    data = conversation_to_docx("Termination review", [
        {"role": "user", "content": "What does clause 9 say?", "created_at": "2026-10-03T09:30:00+00:00"},
        {"role": "assistant", "content": "**Clause 9** allows termination.\n- on 30 days notice\n1. in writing [1]",
         "citations": [{"ref": 1, "title": "Share Purchase Agreement", "page": 14}]},
        {"role": "system", "content": "hidden"},
    ])
    text = _text(data)
    assert "Termination review" in text and "You (03 Oct 2026, 09:30)" in text and "Assistant" in text
    assert "Clause 9 allows termination." in text and "on 30 days notice" in text
    assert "[1] Share Purchase Agreement, p. 14" in text
    assert "hidden" not in text


def test_export_endpoint_returns_a_word_file_for_the_owner_only(client, seeded):
    created = client.post("/api/chat/sessions", json={}, headers=as_member(ME))
    assert created.status_code == 200, created.text
    sid = created.json()["id"]
    try:
        res = client.get(f"/api/chat/sessions/{sid}/export.docx", headers=as_member(ME))
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("application/vnd.openxmlformats")
        assert res.content[:2] == b"PK"
        other = client.get(f"/api/chat/sessions/{sid}/export.docx", headers=as_member("MEM-00002"))
        assert other.status_code in (403, 404)
    finally:
        client.delete(f"/api/chat/sessions/{sid}", headers=as_member(ME))
