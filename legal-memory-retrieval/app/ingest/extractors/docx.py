"""DOCX text extractor using python-docx (MIT licensed) — paragraph → pseudo-pages."""
from __future__ import annotations

import io
import tempfile
from pathlib import Path

from app.ingest.extractors.types import ExtractedDocument, join_pages

# Approximate page break every N characters for DOCX (no fixed pages in OOXML flow)
_CHARS_PER_PAGE = 3000


def style_namer(document):
    """``paragraph -> style name`` for one document, resolving each style once.

    python-docx's ``paragraph.style`` scans the whole styles part for the default style
    on every unstyled paragraph — seconds on a long agreement.
    """
    from docx.enum.style import WD_STYLE_TYPE

    names = {s.style_id: s.name or "" for s in document.styles}
    default = document.styles.default(WD_STYLE_TYPE.PARAGRAPH)
    default_name = (default.name or "") if default is not None else ""

    def name(p) -> str:
        style_id = p._p.style
        return names.get(style_id, default_name) if style_id else default_name

    return name


def heading_texts(document) -> list[str]:
    """The text of every paragraph styled as a heading (Title, Heading 1-9), in order."""
    style_of = style_namer(document)
    out = []
    for p in document.paragraphs:
        text = (p.text or "").strip()
        style = style_of(p).lower()
        if text and (style.startswith("heading") or style == "title"):
            out.append(text)
    return out


def docx_heading_texts(data: bytes) -> list[str]:
    """``heading_texts`` of a stored Word file; [] when it cannot be read."""
    try:
        from docx import Document

        return heading_texts(Document(io.BytesIO(data)))
    except Exception:  # noqa: BLE001 — headings are a refinement; text parsing still works without them
        return []


class DocxExtractor:
    """Extract structured text from DOCX, preserving paragraphs and headings."""

    def extract(self, path: str) -> tuple[str, int]:
        doc = self.extract_structured(path)
        return doc.text, doc.page_count

    def extract_structured(self, path: str) -> ExtractedDocument:
        from docx import Document

        document = Document(path)
        paragraphs = [(p.text or "").strip() for p in document.paragraphs]
        paragraphs = [t for t in paragraphs if t]
        # The text is the document's own words. Headings are passed to the block parser separately: writing a label
        # into the text ("SECTION 5. Remuneration") made the reader, search and the Assistant quote words that are
        # not in the file, so edits to them could not be placed.
        headings = heading_texts(document)

        # Tables as pipe-separated blocks
        for table in document.tables:
            rows = []
            for row in table.rows:
                cells = [" ".join(c.text.split()) for c in row.cells]
                rows.append(" | ".join(cells))
            if rows:
                paragraphs.append("\n".join(rows))

        body = "\n\n".join(paragraphs)
        # Slice into pseudo-pages for Page → Block hierarchy
        page_texts: list[str] = []
        if not body:
            page_texts = [""]
        else:
            start = 0
            while start < len(body):
                end = min(len(body), start + _CHARS_PER_PAGE)
                if end < len(body):
                    cut = body.rfind("\n\n", start, end)
                    if cut > start + _CHARS_PER_PAGE // 2:
                        end = cut
                page_texts.append(body[start:end].strip())
                start = end
            page_texts = [p for p in page_texts if p] or [body]

        extracted = join_pages(page_texts)
        extracted.mime_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        extracted.source_format = "docx"
        extracted.headings = headings
        return extracted

    def extract_bytes(self, data: bytes) -> ExtractedDocument:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=True) as tmp:
            tmp.write(data)
            tmp.flush()
            return self.extract_structured(tmp.name)
