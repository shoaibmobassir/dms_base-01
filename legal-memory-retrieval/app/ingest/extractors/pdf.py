"""PDF text extractor using pypdf (BSD licensed)."""
from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


class PdfExtractor:
    """Extract text from a PDF file. Returns (full_text, page_count)."""

    def extract(self, path: str) -> tuple[str, int]:
        reader = PdfReader(path)
        pages = []
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(text)
        full_text = "\n\n".join(pages)
        return full_text, len(reader.pages)
