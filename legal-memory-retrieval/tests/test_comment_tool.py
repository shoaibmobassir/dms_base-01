"""The Assistant leaves comments on a document."""
from __future__ import annotations

from app.chat.tools.comment_tools import _locate, comment_on_document_tool
from app.chat.tools.document_tools import DocEntry
from app.db.connection import connect
from app.documents.canonical import get_version_blocks
from tests.conftest import as_member

ME = "MEM-00001"


def test_locate_ignores_case_and_whitespace_and_short_quotes():
    blocks = [{"block_id": "a", "text": "The Supplier   shall deliver\nwithin 30 days."}, {"block_id": "b", "text": "Other"}]
    assert _locate(blocks, "the supplier shall deliver within 30 DAYS")["block_id"] == "a"
    assert _locate(blocks, "nope, not in it at all") is None
    assert _locate(blocks, "The") is None


def _document_with_text(client):
    headers = as_member(ME)
    for d in client.get("/api/documents?limit=80", headers=headers).json()["items"]:
        detail = client.get(f"/api/documents/{d['document_id']}?lean=true", headers=headers).json()
        vid = detail.get("current_version_id")
        if not vid:
            continue
        blocks = [b for b in get_version_blocks(vid) if len(str(b.get("text") or "")) > 40]
        if blocks:
            return d["document_id"], vid, blocks[0]
    return None


def test_comment_is_added_on_the_document_and_unfound_quotes_are_reported(client, seeded):
    found = _document_with_text(client)
    assert found, "needs a document with text blocks"
    document_id, version_id, block = found
    quote = " ".join(str(block["text"]).split())[:60]
    entry = DocEntry("doc-0", document_id, "x.docx", version_id=version_id)
    with connect() as conn:
        result, events = comment_on_document_tool(
            {"doc_id": "doc-0", "comments": [
                {"quote": quote, "comment": "Check this against the order."},
                {"quote": "this sentence is certainly not in the document", "comment": "x"},
            ]},
            {"doc-0": entry}, conn, ME,
        )
    try:
        assert result["added"] == 1 and len(result["not_found"]) == 1
        assert events[0]["type"] == "comments_added" and events[0]["comments"][0]["body"] == "Check this against the order."
        threads = client.get(f"/api/editor/documents/{document_id}/comments", headers=as_member(ME)).json()["threads"]
        assert any(t["body"] == "Check this against the order." for t in threads)
    finally:
        with connect() as conn:
            for c in events[0]["comments"] if events else []:
                conn.execute("DELETE FROM annotations WHERE annotation_id = %s", (c["comment_id"],))
            conn.commit()


def test_nothing_is_added_without_a_known_document_or_comments(client, seeded):
    with connect() as conn:
        assert "error" in comment_on_document_tool({"doc_id": "nope", "comments": [{"quote": "x" * 20, "comment": "y"}]}, {}, conn, ME)[0]
        entry = DocEntry("doc-0", "DOC-X", "x.docx", version_id="V")
        assert "error" in comment_on_document_tool({"doc_id": "doc-0", "comments": []}, {"doc-0": entry}, conn, ME)[0]


def test_a_pdf_cannot_be_edited_by_the_assistant(client, seeded):
    from app.chat.tools.edit_tools import edit_document_tool
    from app.chat.tools.review_tools import propose_edits

    entry = DocEntry("doc-0", "DOC-X", "Rejoinder to reply.PDF", version_id="V")
    with connect() as conn:
        out = propose_edits("doc-0", [{"original": "a b c d e f", "proposed": "x"}], {"doc-0": entry}, {}, conn, ME)
        assert "PDF" in out["error"] and "comment_on_document" in out["error"]
        res, events = edit_document_tool({"doc_id": "doc-0", "instruction": "fix typos"}, {"doc-0": entry}, conn, ME)
        assert "PDF" in res["error"] and events == []


def test_a_version_diff_needs_both_versions_to_belong_to_the_document(client, seeded):
    headers = as_member(ME)
    found = {}
    for d in client.get("/api/documents?limit=80", headers=headers).json()["items"]:
        vs = client.get(f"/api/documents/{d['document_id']}/versions", headers=headers).json().get("versions", [])
        if vs:
            found[d["document_id"]] = vs[0]["version_id"]
        if len(found) == 2:
            break
    (doc_a, ver_a), (_doc_b, ver_b) = list(found.items())
    res = client.get(f"/api/documents/{doc_a}/versions/{ver_a}/diff", params={"compare_with": ver_b}, headers=headers)
    assert res.status_code == 404
