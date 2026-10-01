"""PDF text extractor using pypdf (BSD licensed) — page-aware.

Scanned pages have no text layer. When Poppler and Tesseract are installed,
those pages are read with OCR. Digital pages keep the embedded text.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfReader

from app.ingest.extractors.types import ExtractedDocument, join_pages

log = logging.getLogger(__name__)

# A page with fewer letters than this is treated as a scan.
_MIN_LETTERS = 40


def _letter_count(text: str) -> int:
    return sum(ch.isalnum() for ch in text)


def _ocr_page(pdf_path: str, page_number: int, workdir: Path) -> str:
    """Render one PDF page and read it with Tesseract. Empty string if that fails."""
    prefix = workdir / f"page-{page_number}"
    render = subprocess.run(
        ["pdftoppm", "-f", str(page_number), "-l", str(page_number), "-png", "-r", "200", pdf_path, str(prefix)],
        check=False,
        capture_output=True,
        timeout=90,
    )
    if render.returncode != 0:
        log.warning("page render failed for %s page %s", pdf_path, page_number)
        return ""
    images = sorted(workdir.glob(f"page-{page_number}*.png"))
    if not images:
        return ""
    ocr = subprocess.run(
        ["tesseract", str(images[0]), "stdout", "-l", "eng"],
        check=False,
        capture_output=True,
        timeout=120,
        text=True,
    )
    if ocr.returncode != 0:
        log.warning("ocr failed for %s page %s", pdf_path, page_number)
        return ""
    return (ocr.stdout or "").strip()


def _fill_scanned_pages(path: str, page_texts: list[str]) -> list[str]:
    sparse = [i for i, text in enumerate(page_texts, start=1) if _letter_count(text) < _MIN_LETTERS]
    if not sparse:
        return page_texts
    if shutil.which("pdftoppm") is None or shutil.which("tesseract") is None:
        log.info("scanned pdf pages left without text; pdftoppm or tesseract is not installed")
        return page_texts
    filled = list(page_texts)
    with tempfile.TemporaryDirectory(prefix="pdf-ocr-") as tmp:
        workdir = Path(tmp)
        for number in sparse:
            text = _ocr_page(path, number, workdir)
            if _letter_count(text) >= _MIN_LETTERS:
                filled[number - 1] = text
    return filled


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
        page_texts = _fill_scanned_pages(path, page_texts)
        doc = join_pages(page_texts)
        doc.mime_type = "application/pdf"
        doc.source_format = "pdf"
        return doc

    def extract_bytes(self, data: bytes) -> ExtractedDocument:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(data)
            tmp.flush()
            return self.extract_structured(tmp.name)
