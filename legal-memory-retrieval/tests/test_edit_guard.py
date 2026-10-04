"""PDF text is machine-read: the Assistant must not "correct" spacing or OCR artifacts, and a PDF is read-only."""
from __future__ import annotations

import pytest

from app.chat.models import MessageRole
from app.chat.store import append_message
from app.chat.tools import review_tools
from app.chat.tools.document_tools import DocEntry
from app.chat.tools.edit_guard import NO_CHANGE, SCANNED_TYPO, SPACING, filter_edits, review_edit
from app.chat.tools.review_tools import propose_edits
from app.db.connection import connect
from app.documents import text_origin
from app.documents.text_origin import BORN_DIGITAL, SCANNED_OCR, page_origin
from tests.conftest import as_member

# A page of a filing where "the" is common and "tbe"/"knowledgeand" are one-off reading errors.
DOC = ("the contents of the affidavit are true to the best of my knowledgeand belief. tbe deponent states that "
       "the lessor and the lessee agree. the lessor shall pay. the lessor may terminate. the lessee shall vacate.")


def _edit(original: str, proposed: str, page: int = 1) -> dict:
    return {"original": original, "proposed": proposed, "page": page}


PDF_SCANNED = {"format": "pdf", "origins": [SCANNED_OCR], "scanned_pages": [1]}
PDF_DIGITAL = {"format": "pdf", "origins": [BORN_DIGITAL], "scanned_pages": []}
DOCX = {"format": "docx", "origins": None, "scanned_pages": []}


# --- the reported case ---------------------------------------------------------------------------------

def test_glued_words_are_not_corrected_in_pdf_text():
    """'knowledgeand' -> 'knowledge and': the printed page is fine; the OCR layer has no space glyph."""
    for info in (PDF_SCANNED, PDF_DIGITAL):
        assert review_edit("knowledgeand belief", "knowledge and belief", source_format="pdf",
                           origin=page_origin(info, 1), doc_text=DOC) == SPACING


def test_a_real_typo_in_a_word_file_is_still_fixed():
    assert review_edit("knowledgeand belief", "knowledge and belief", source_format="docx", origin=None, doc_text=DOC) is None


def test_hyphenation_line_breaks_and_ligatures_are_spacing():
    for a, b in [("indemnifi-\ncation", "indemnification"), ("e­ffective", "effective"), ("ﬁnal", "final"),
                 ("the  parties", "the parties")]:
        assert review_edit(a, b, source_format="pdf", origin=BORN_DIGITAL) == SPACING, (a, b)


def test_no_change_is_dropped_everywhere():
    assert review_edit("same", " same ", source_format="docx", origin=None) == NO_CHANGE


# --- OCR typos on scanned pages ------------------------------------------------------------------------

def test_ocr_typo_on_a_scanned_page_is_dropped_only_when_the_odd_word_is_rare_and_the_fix_common():
    assert review_edit("tbe deponent", "the deponent", source_format="pdf", origin=SCANNED_OCR, doc_text=DOC) == SCANNED_TYPO
    # born-digital page: the text is what the author typed, so a real typo fix is a legitimate recommendation
    assert review_edit("tbe deponent", "the deponent", source_format="pdf", origin=BORN_DIGITAL, doc_text=DOC) is None


def test_look_alike_confusion_is_an_ocr_artifact():
    doc = "the amount is due. the amount is fixed. the amount is final. the arnount is stated here."
    assert review_edit("arnount", "amount", source_format="pdf", origin=SCANNED_OCR, doc_text=doc) == SCANNED_TYPO


def test_substantive_changes_on_scanned_pages_are_kept():
    # a number is never a typo
    assert review_edit("INR 1,20,00,000", "INR 1,50,00,000", source_format="pdf", origin=SCANNED_OCR, doc_text=DOC) is None
    # both words are real and common: a party swap is a legal change
    assert review_edit("the lessee shall pay", "the lessor shall pay", source_format="pdf", origin=SCANNED_OCR, doc_text=DOC) is None
    # insertions and deletions are substantive
    assert review_edit("shall pay", "shall not pay", source_format="pdf", origin=SCANNED_OCR, doc_text=DOC) is None
    assert review_edit("the lessor may terminate", "", source_format="pdf", origin=SCANNED_OCR, doc_text=DOC) is None
    # wording
    assert review_edit("shall pay within thirty days", "shall pay within fifteen days", source_format="pdf",
                       origin=SCANNED_OCR, doc_text=DOC + " thirty thirty fifteen fifteen") is None


def test_without_document_text_a_typo_level_change_is_never_dropped_on_a_guess():
    assert review_edit("tbe deponent", "the deponent", source_format="pdf", origin=SCANNED_OCR, doc_text=None) is None


def test_filter_edits_splits_kept_and_rejected():
    edits = [_edit("knowledgeand belief", "knowledge and belief"), _edit("tbe deponent", "the deponent"),
             _edit("INR 1,20,00,000", "INR 1,50,00,000")]
    kept, rejected = filter_edits(edits, PDF_SCANNED, DOC)
    assert [e["original"] for e in kept] == ["INR 1,20,00,000"]
    assert len(rejected) == 2 and all(r["why"] for r in rejected)


# --- page provenance -----------------------------------------------------------------------------------

def test_a_page_sized_image_makes_a_scan_and_a_logo_does_not():
    letter = (612.0, 792.0)
    assert text_origin._is_scan([(1700, 2200)], *letter) is True      # 200 dpi scan
    assert text_origin._is_scan([(300, 100)], *letter) is False       # logo
    assert text_origin._is_scan([(1700, 300)], *letter) is False      # full-width banner, not full page
    assert text_origin._is_scan([], *letter) is False
    assert text_origin._is_scan([(1700, 2200)], 0, 0) is False


def test_page_origin_is_conservative_when_unknown():
    assert page_origin({"format": "docx"}, 1) is None
    assert page_origin(PDF_SCANNED, 1) == SCANNED_OCR
    assert page_origin({"format": "pdf", "origins": None, "scanned_pages": []}, 3) == SCANNED_OCR   # file unreadable
    assert page_origin({"format": "pdf", "origins": [BORN_DIGITAL, SCANNED_OCR], "scanned_pages": [2]}, 2) == SCANNED_OCR
    assert page_origin({"format": "pdf", "origins": [BORN_DIGITAL], "scanned_pages": []}, 1) == BORN_DIGITAL


# --- propose_edits end to end --------------------------------------------------------------------------

def _run(monkeypatch, info, edits, text=DOC):
    monkeypatch.setattr(review_tools, "source_info", lambda conn, document_id: info)
    entry = DocEntry(doc_id="doc-0", document_id="DOC-X", filename="Rejoinder.pdf", text=text)
    return propose_edits("doc-0", edits, {"doc-0": entry}, {"doc-0": text})


def test_propose_edits_drops_artifacts_and_marks_a_pdf_read_only(monkeypatch):
    res = _run(monkeypatch, PDF_SCANNED, [
        {"original": "knowledgeand belief", "proposed": "knowledge and belief", "reason": "spacing"},
        {"original": "the lessor shall pay", "proposed": "the lessor shall pay within thirty days", "reason": "certainty"},
    ])
    assert res["proposed"] == 1 and len(res["dropped_as_reading_artifacts"]) == 1
    assert res["event"]["read_only"] is True and res["event"]["source_format"] == "pdf"
    assert "read-only" in res["note"]


def test_propose_edits_with_only_artifacts_says_there_is_nothing_to_report(monkeypatch):
    res = _run(monkeypatch, PDF_SCANNED, [{"original": "knowledgeand belief", "proposed": "knowledge and belief"}])
    assert res["proposed"] == 0 and "event" not in res
    assert "Do not report them" in res["note"]


def test_propose_edits_on_a_word_file_is_unchanged(monkeypatch):
    res = _run(monkeypatch, DOCX, [{"original": "knowledgeand belief", "proposed": "knowledge and belief"}])
    assert res["proposed"] == 1 and res["event"]["read_only"] is False


# --- export is refused for a PDF -----------------------------------------------------------------------

def test_export_refuses_a_pdf(client, seeded):
    with connect() as conn:
        row = conn.execute("SELECT document_id FROM documents WHERE mime_type = 'application/pdf' LIMIT 1").fetchone()
    if not row:
        pytest.skip("no PDF document in the database")
    doc_id = row["document_id"]
    event = {"type": "edit_proposals", "document_id": doc_id, "version_id": None, "filename": "x.pdf",
             "edits": [{"id": "e1", "original": "a", "proposed": "b", "status": "accepted"}]}
    headers = as_member("MEM-00001")
    session = client.post("/api/chat/sessions", json={}, headers=headers).json()
    try:
        with connect() as conn:
            msg = append_message(conn, session["id"], MessageRole.assistant, "Edits.", events=[event])
        r = client.post(f"/api/chat/sessions/{session['id']}/messages/{msg.id}/edits/export?document_id={doc_id}", headers=headers)
        assert r.status_code == 409 and "read-only" in r.json()["detail"]
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM chat_messages WHERE session_id = %s", (session["id"],))
            conn.execute("DELETE FROM chat_sessions WHERE id = %s", (session["id"],))


# --- scanned pages are marked in the text the model reads ---------------------------------------------

def test_scanned_pages_are_marked_inside_the_text():
    from app.chat.tools.document_tools import annotate_scanned

    text = "[Page 1]\nBorn digital.\n\n[Page 2]\nknowledgeand belief"
    shown = annotate_scanned(text, [2])
    assert "[Page 1]\nBorn digital." in shown                       # untouched
    assert "[Page 2 - SCANNED PAGE" in shown and "do not report them as errors" in shown
    assert "knowledgeand belief" in shown                            # the text itself is never altered
    assert annotate_scanned(text, None) == text and annotate_scanned(text, []) == text


def test_read_document_marks_scanned_pages_but_stores_plain_text(monkeypatch):
    from app.chat.tools import document_tools

    monkeypatch.setattr("app.documents.text_origin.source_info", lambda conn, did: {
        "format": "pdf", "origins": [BORN_DIGITAL, SCANNED_OCR], "scanned_pages": [2]})
    text = "[Page 1]\nIntro.\n\n[Page 2]\nknowledgeand belief"
    entry = DocEntry(doc_id="doc-0", document_id="DOC-X", filename="x.pdf", text=text)
    store = {"doc-0": text}
    out = document_tools.read_document("doc-0", {"doc-0": entry}, store, conn=None, nonce=None)
    assert "SCANNED PAGE" in out["text"] and out["source"]["scanned_pages"] == [2]
    assert store["doc-0"] == text and "SCANNED" not in store["doc-0"]


# --- claims in the answer's prose -----------------------------------------------------------------------

STORED = ("[Page 1]\nThe Tribunal is the ELECTRCITY forum. Tbe affidavit follows.\n\n"
          "[Page 2 - SCANNED PAGE: machine-read text]\nto the best of my knowledgeand belief. Nothing false has been states thcrein.")


def test_words_found_only_on_scanned_pages_are_identified():
    from app.chat.tools.edit_guard import scan_only_words

    words = scan_only_words(STORED, [2])
    assert {"knowledgeand", "thcrein", "states"} <= words
    assert "tribunal" not in words and "electrcity" not in words     # born-digital page words never count


def test_a_line_calling_an_ocr_artifact_an_error_is_removed_and_others_stay():
    from app.chat.tools.edit_guard import scan_only_words, scrub_scan_claims

    answer = ("**3.\n- **Issue**: \"knowledgeand\" missing space\n- Why: professional\n"
              "**4.\n- Issue: \"thcrein\" appears to be an OCR error\n"
              "**5.\n- Issue: the tribunal name is spelled \"ELECTRCITY\" on page 1\n"
              "The verification states that the facts are true.")
    cleaned, removed = scrub_scan_claims(answer, scan_only_words(STORED, [2]))
    assert len(removed) == 2
    assert "knowledgeand" not in cleaned and "thcrein" not in cleaned
    assert "ELECTRCITY" in cleaned                                    # a real defect on a born-digital page stays
    assert "The verification states that the facts are true." in cleaned
    assert "**3." not in cleaned and "**4." not in cleaned and "**5." in cleaned   # dangling headings go with their line


def test_scrub_does_nothing_without_scanned_pages():
    from app.chat.tools.edit_guard import scan_only_words, scrub_scan_claims

    text = 'The word "knowledgeand" is missing a space.'
    assert scan_only_words(STORED, []) == set()
    assert scrub_scan_claims(text, set()) == (text, [])


def test_an_item_whose_original_and_fix_differ_only_as_a_scan_reads_is_removed():
    from app.chat.tools.edit_guard import scan_only_words, scrub_scan_claims

    stored = ("[Page 1]\nthe affidavit states that the deponent is true. the deponent is sworn. the deponent signs.\n\n"
              "[Page 2]\nto the best of my knowledgeand belief. the deponent is sworn.")
    answer = ("**4. Verification wording**\n- Original: \"to the best of my knowledgeand belief\"\n"
              "- Suggested: \"to the best of my knowledge and belief\"\n"
              "**5. Deadline**\n- Original: \"within thirty days\"\n- Suggested: \"within fifteen days\"")
    cleaned, removed = scrub_scan_claims(answer, scan_only_words(stored, [2]), stored)
    assert len(removed) == 1 and "knowledgeand" not in cleaned
    assert "within thirty days" in cleaned and "within fifteen days" in cleaned    # a real recommendation stays
