"""Unified document extraction: PDF / DOCX / text → ExtractedDocument."""
from __future__ import annotations

from pathlib import Path

from app.ingest.extractors.docx import DocxExtractor
from app.ingest.extractors.pdf import PdfExtractor
from app.ingest.extractors.types import ExtractedDocument, join_pages

PDF_EXT = {".pdf"}
DOCX_EXT = {".docx"}
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".html", ".xml"}


def extract_from_bytes(filename: str, data: bytes) -> ExtractedDocument:
    ext = Path(filename).suffix.lower()
    if ext in PDF_EXT:
        return PdfExtractor().extract_bytes(data)
    if ext in DOCX_EXT:
        return DocxExtractor().extract_bytes(data)
    if ext in TEXT_EXT or ext == "":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1", errors="replace")
        # Pseudo-pages for plain text
        page_texts: list[str] = []
        chunk = 3000
        for i in range(0, max(1, len(text)), chunk):
            page_texts.append(text[i : i + chunk])
        doc = join_pages(page_texts if text else [""])
        doc.mime_type = "text/plain"
        doc.source_format = "text"
        return doc
    # Unsupported binary placeholder (still one page)
    placeholder = f"[Binary artifact stored: {filename}; text extraction not available]"
    doc = join_pages([placeholder])
    doc.mime_type = "application/octet-stream"
    doc.source_format = "binary"
    return doc


def extract_from_path(path: str) -> ExtractedDocument:
    p = Path(path)
    return extract_from_bytes(p.name, p.read_bytes())
