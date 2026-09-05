"""PDF text extractor using pypdf (BSD licensed) — page-aware."""
from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from app.ingest.extractors.types import ExtractedDocument, join_pages


class PdfExtractor:
    """Extract text from a PDF file with real page boundaries."""

    def extract(self, path: str) -> tuple[str, int]:
        """Legacy API: (full_text, page_count)."""
        doc = self.extract_structured(path)
        return doc.text, doc.page_count

    def extract_structured(self, path: str) -> ExtractedDocument:
        reader = PdfReader(path)
        page_texts: list[str] = []
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            page_texts.append(text)
        if not page_texts:
            page_texts = [""]
        doc = join_pages(page_texts)
        doc.mime_type = "application/pdf"
        doc.source_format = "pdf"
        return doc

    def extract_bytes(self, data: bytes) -> ExtractedDocument:
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(data)
            tmp.flush()
            return self.extract_structured(tmp.name)
