"""A Word file carries tracked changes only when it has revision elements, whatever its words say (2026-10-04).

"9. Change of Control" in the CTO agreement matched a bare b"Change " test, so the file always counted as tracked: every
save kept its markup (the crossed-out text the lawyer kept seeing) and it could never become a clean version.
"""
from __future__ import annotations

import io

from docx import Document

from app.documents.docx_review import has_revisions
from app.drafting.docx_tracked import apply_tracked_changes


def _docx(*paras: str) -> bytes:
    d = Document()
    for p in paras:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_words_that_look_like_markup_names_are_not_revisions():
    assert not has_revisions(_docx("9. Change of Control", "Material Adverse Change ", "Insert the delivery address."))


def test_real_insertions_and_deletions_are_revisions():
    tracked, _ = apply_tracked_changes(_docx("Fees are INR 1,20,00,000."),
                                       [{"op": "replace", "pid": 0, "text": "Fees are INR 1,50,00,000."}], author="A")
    assert has_revisions(tracked)


def test_a_formatting_change_is_a_revision():
    data = _docx("Plain text")
    import zipfile

    src = zipfile.ZipFile(io.BytesIO(data))
    xml = src.read("word/document.xml").replace(
        b"<w:r>", b'<w:r><w:rPr><w:b/><w:rPrChange w:id="1" w:author="A"><w:rPr/></w:rPrChange></w:rPr>', 1)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for item in src.infolist():
            z.writestr(item, xml if item.filename == "word/document.xml" else src.read(item.filename))
    assert has_revisions(out.getvalue())


def test_unreadable_data_is_not_a_revision():
    assert not has_revisions(b"not a zip")



def test_a_tracked_file_is_extracted_as_it_now_reads():
    """Old and new text are never stored together, and the new text is never lost (plan 21, G-D)."""
    from app.ingest.extractors.dispatch import extract_from_bytes

    tracked, _ = apply_tracked_changes(_docx("Fees are INR 1,20,00,000 per year.", "Notice is thirty days."),
                                       [{"op": "replace", "pid": 0, "text": "Fees are INR 1,50,00,000 per year."}], author="A")
    assert has_revisions(tracked)
    text = extract_from_bytes("Agreement.docx", tracked).text
    assert "INR 1,50,00,000" in text and "1,20,00,000" not in text and "Notice is thirty days." in text
