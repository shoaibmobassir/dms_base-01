"""Chat workspace: page-marked text, suggested edits, step labels, viewer rendering."""

from __future__ import annotations

import pytest

from app.chat.agent import dispatch_tool_call, tool_step_label
from app.chat.tools.document_tools import (
    DocEntry,
    add_documents_to_index,
    find_in_document,
    page_at,
    paged_text,
)
from app.chat.tools.review_tools import apply_accepted_edits, propose_edits, strip_page_markers
from app.documents.pdf_render import RenderUnavailable, to_pdf

PAGES = [
    (1, "BEFORE THE COMMISSION\nPetition No. 22 of 2026"),
    (2, "The Respondent shall pay the tariff within thirty days."),
    (3, "Late payment attracts a surcharge of 1.25% per month."),
]


def _index(text: str):
    entry = DocEntry(doc_id="doc-0", document_id="DOC-TEST", filename="Petition.pdf", text=text)
    return {"doc-0": entry}, {"doc-0": text}


def test_paged_text_marks_every_page():
    text = paged_text(PAGES)
    assert text.startswith("[Page 1]\nBEFORE THE COMMISSION")
    assert "[Page 2]\nThe Respondent" in text
    assert page_at(text, text.index("surcharge")) == 3
    assert page_at(text, text.index("thirty days")) == 2


def test_strip_page_markers_leaves_body_text():
    stripped = strip_page_markers(paged_text(PAGES))
    assert "[Page" not in stripped
    assert "thirty days" in stripped


def test_attached_documents_come_first_and_are_not_duplicated():
    index = {"doc-0": DocEntry("doc-0", "DOC-A", "a.pdf")}
    merged = add_documents_to_index(index, [("DOC-B", "b.pdf"), ("DOC-A", "a.pdf")])
    assert [e.document_id for e in merged.values()] == ["DOC-B", "DOC-A"]
    assert len({slug for slug in merged}) == 2


def test_find_in_document_reports_page():
    index, store = _index(paged_text(PAGES))
    result = find_in_document("doc-0", "surcharge", index, store)
    assert result["matches"][0]["page"] == 3


def test_propose_edits_locates_passages_and_pages():
    index, store = _index(paged_text(PAGES))
    result = propose_edits(
        "doc-0",
        [
            {"original": "within thirty days", "proposed": "within fifteen days", "reason": "Faster cash flow."},
            {"original": "text that is not there", "proposed": "x", "reason": "y"},
        ],
        index,
        store,
    )
    edits = result["event"]["edits"]
    assert result["event"]["type"] == "edit_proposals"
    assert edits[0]["located"] is True and edits[0]["page"] == 2
    assert edits[0]["status"] == "pending"
    assert edits[1]["located"] is False
    assert result["not_found_in_document"] == [edits[1]["id"]]


def test_propose_edits_rejects_unknown_document():
    assert "error" in propose_edits("doc-9", [{"original": "a", "proposed": "b"}], {}, {})


def test_apply_accepted_edits_only_applies_accepted():
    text = strip_page_markers(paged_text(PAGES))
    revised, applied = apply_accepted_edits(
        text,
        [
            {"status": "accepted", "original": "thirty days", "proposed": "fifteen days"},
            {"status": "rejected", "original": "1.25%", "proposed": "2%"},
            {"status": "accepted", "original": "missing passage", "proposed": "z"},
        ],
    )
    assert applied == 1
    assert "fifteen days" in revised and "1.25%" in revised


def test_dispatch_propose_edits_emits_event():
    index, store = _index(paged_text(PAGES))
    result, events = dispatch_tool_call(
        "propose_edits",
        {"doc_id": "doc-0", "edits": [{"original": "1.25% per month", "proposed": "1% per month", "reason": "Cap."}]},
        index, store, None, "nonce",
    )
    assert result["proposed"] == 1
    assert events[0]["type"] == "edit_proposals"


def test_step_labels_are_plain_english():
    index, _ = _index("x")
    assert tool_step_label("read_document", {"doc_id": "doc-0"}, index) == "Reading Petition.pdf"
    assert "surcharge" in tool_step_label("find_in_document", {"doc_id": "doc-0", "query": "surcharge"}, index)
    for name in ("search_firm_records", "propose_edits", "generate_docx", "ask_inputs", "other"):
        label = tool_step_label(name, {}, index)
        assert label and "_" not in label


def test_render_passes_pdf_through():
    data = b"%PDF-1.4\n%fake\n"
    assert to_pdf(data, "application/pdf", "a.pdf") == data


def test_render_refuses_unknown_types():
    with pytest.raises(RenderUnavailable):
        to_pdf(b"\x00\x01", "application/octet-stream", "archive.zip")


def test_render_without_converter_is_unavailable(monkeypatch, tmp_path):
    import app.documents.pdf_render as render

    monkeypatch.setattr(render, "converter_path", lambda: None)
    monkeypatch.setattr(render, "_cache_dir", lambda: tmp_path)
    with pytest.raises(RenderUnavailable):
        to_pdf(b"PK\x03\x04docx-bytes", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "a.docx")


def test_citation_page_follows_verified_quote():
    from app.chat.agent import correct_quote_pages
    from app.chat.verify_citations import verify_document_citation

    text = paged_text(PAGES)
    citation = {"ref": 1, "doc_id": "doc-0", "page": 1, "quote": "surcharge of 1.25% per month",
                "quotes": [{"page": 1, "quote": "surcharge of 1.25% per month"}]}
    fixed = correct_quote_pages(verify_document_citation(citation, text), text)
    assert fixed["verified"] is True
    assert fixed["page"] == 3 and fixed["quotes"][0]["page"] == 3


def test_generated_docx_has_text_for_viewer(monkeypatch, tmp_path):
    """A generated Word file can be read in the viewer's text view by its owner."""
    from fastapi.testclient import TestClient

    from app.api.main import app
    from app.chat.tools.generation_tools import generate_docx
    from app.config import settings

    monkeypatch.setattr(settings, "object_store_root", str(tmp_path))

    made = generate_docx("Viewer probe", [{"heading": "Terms", "content": "Payment within fifteen days."}], owner_member_id="MEM-00001")
    client = TestClient(app)
    ok = client.get(f"/api/documents/{made['document_id']}/text", headers={"X-Member-Id": "MEM-00001"})
    assert ok.status_code == 200
    assert "fifteen days" in ok.json()["text"]
    assert ok.json()["pages"][0]["page"] == 1
    other = client.get(f"/api/documents/{made['document_id']}/text", headers={"X-Member-Id": "MEM-00002"})
    assert other.status_code == 404


def test_internal_doc_labels_become_names():
    from app.chat.agent import name_documents

    index, _ = _index("x")
    out = name_documents("The note (doc-0) and doc-0 say so; doc-7 is unknown.", index)
    assert out == "The note (Petition.pdf) and Petition.pdf say so; doc-7 is unknown."


def test_tesseract_tsv_becomes_relative_word_boxes():
    from app.documents.page_words import parse_tesseract_tsv

    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "4\t1\t1\t1\t1\t0\t100\t200\t400\t40\t-1\t\n"
        "5\t1\t1\t1\t1\t1\t100\t200\t150\t40\t95\tLate\n"
        "5\t1\t1\t1\t1\t2\t260\t200\t240\t40\t96\tpayment\n"
        "5\t1\t1\t1\t1\t3\t510\t200\t10\t40\t10\t \n"
    )
    words = parse_tesseract_tsv(tsv, 1000, 2000)
    assert [w["text"] for w in words] == ["Late", "payment"]
    assert words[0] == {"text": "Late", "line": "1.1.1", "x0": 0.1, "y0": 0.1, "x1": 0.25, "y1": 0.12}


def test_tolerant_quote_location_keeps_word_boundaries():
    """Characters that expand under NFKD (₹, ligatures) must not shift the excerpt."""
    from app.chat.verify_citations import locate_quote

    source = "Paid ₹44.73 crore; the ﬁnal sum is subject to adjustment based on the “final” adjudication."
    loc = locate_quote(source, "subject to adjustment based on the final adjudication")
    assert loc is not None
    assert loc.excerpt.startswith("subject") and loc.excerpt.endswith("adjudication")


def test_prompt_names_attached_documents_first():
    from app.chat.agent import build_llm_messages

    index = add_documents_to_index(
        {"doc-0": DocEntry("doc-0", "DOC-SEARCH", "Brief note (older copy)")},
        [("DOC-ATTACHED", "BRIEF NOTE.pdf")],
    )
    system = build_llm_messages([], "Review this note", index, "n")[0]["content"]
    attached_at = system.index("DOCUMENTS THE USER ATTACHED")
    assert "BRIEF NOTE.pdf" in system[attached_at:system.index("OTHER DOCUMENTS FOUND BY SEARCH")]
    assert "Brief note (older copy)" in system[system.index("OTHER DOCUMENTS FOUND BY SEARCH"):]


def test_attaching_a_document_already_found_marks_it():
    index = {"doc-0": DocEntry("doc-0", "DOC-A", "a.pdf")}
    merged = add_documents_to_index(index, [("DOC-A", "a.pdf")])
    assert merged["doc-0"].attached is True


def test_clarifying_options_use_document_names():
    index, store = _index("x")
    _result, events = dispatch_tool_call(
        "ask_inputs",
        {"items": [{"id": "f", "kind": "choice", "question": "Use doc-0?", "options": [{"value": "The petition (doc-0)"}]}]},
        index, store, None, "n",
    )
    item = events[0]["items"][0]
    assert item["question"] == "Use Petition.pdf?"
    assert item["options"][0]["value"] == "The petition (Petition.pdf)"
