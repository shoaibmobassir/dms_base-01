"""Extractor protocol and dispatch for PDF / DOCX / text."""
from __future__ import annotations

from typing import Protocol

from app.ingest.extractors.dispatch import extract_from_bytes, extract_from_path
from app.ingest.extractors.docx import DocxExtractor
from app.ingest.extractors.pdf import PdfExtractor
from app.ingest.extractors.types import ExtractedDocument, PageSpan


class Extractor(Protocol):
    """Extract text from a file path. Returns (full_text, page_count)."""

    def extract(self, path: str) -> tuple[str, int]:
        ...


__all__ = [
    "DocxExtractor",
    "ExtractedDocument",
    "Extractor",
    "PageSpan",
    "PdfExtractor",
    "extract_from_bytes",
    "extract_from_path",
]
