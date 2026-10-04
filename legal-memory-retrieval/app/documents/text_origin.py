"""Where the text of a document comes from, so the Assistant knows how far to trust it.

A PDF page is one of:

- ``born_digital``: the text was typed in a program and exported (Word, a browser). The characters and the
  spaces between them are what the author wrote.
- ``scanned_ocr``: the page is a picture of paper, and any text on it was read by an OCR engine. The OCR layer
  often has no space glyph where the print has a gap ("knowledgeand"), wrong letters ("rn" for "m", "1" for "I"),
  and missing punctuation. Those are artifacts of reading, not defects in the document.

A page is taken to be scanned when it carries an image that spans most of the page at scan resolution. Small
images (a logo, a signature) do not count. This is read from the PDF itself, so no re-ingest or stored flag is
needed; results are cached by file hash like the other render caches.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app.config import settings

log = logging.getLogger(__name__)

BORN_DIGITAL = "born_digital"
SCANNED_OCR = "scanned_ocr"

# An image is a scan of the page when it is at least this many dots per inch across the page width and
# covers most of the page height at that density.
MIN_SCAN_DPI = 100
MIN_COVER = 0.8
_PDF_MIMES = {"application/pdf"}
_DOCX_MIMES = {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def _cache_path(pdf: bytes) -> Path:
    folder = Path(settings.object_store_root) / "render_cache"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{hashlib.sha256(pdf).hexdigest()}-origins.json"


def _images(resources: Any, depth: int = 0) -> list[tuple[int, int]]:
    """(width, height) in pixels of every image painted by a page, looking one level into form XObjects."""
    found: list[tuple[int, int]] = []
    try:
        xobjects = (resources or {}).get("/XObject")
        xobjects = xobjects.get_object() if xobjects is not None else {}
        for ref in xobjects.values():
            obj = ref.get_object()
            subtype = obj.get("/Subtype")
            if subtype == "/Image":
                found.append((int(obj.get("/Width", 0)), int(obj.get("/Height", 0))))
            elif subtype == "/Form" and depth < 1:
                found.extend(_images(obj.get("/Resources"), depth + 1))
    except Exception:  # a malformed resource tree must not stop the read
        log.debug("could not read page images", exc_info=True)
    return found


def _is_scan(images: list[tuple[int, int]], page_w_pt: float, page_h_pt: float) -> bool:
    if page_w_pt <= 0 or page_h_pt <= 0:
        return False
    need_w = MIN_COVER * page_w_pt * MIN_SCAN_DPI / 72
    need_h = MIN_COVER * page_h_pt * MIN_SCAN_DPI / 72
    return any(w >= need_w and h >= need_h for w, h in images)


def page_origins(pdf: bytes) -> list[str]:
    """``born_digital`` or ``scanned_ocr`` for each page, in order."""
    cache = _cache_path(pdf)
    try:
        return list(json.loads(cache.read_text()))
    except (OSError, ValueError):
        pass
    origins: list[str] = []
    for page in PdfReader(io.BytesIO(pdf)).pages:
        box = page.mediabox
        scanned = _is_scan(_images(page.get("/Resources")), float(box.width), float(box.height))
        origins.append(SCANNED_OCR if scanned else BORN_DIGITAL)
    try:
        cache.write_text(json.dumps(origins))
    except OSError:
        log.debug("could not cache page origins", exc_info=True)
    return origins


def _format_of(mime: str | None, uri: str | None) -> str:
    name = (uri or "").lower()
    if (mime or "") in _PDF_MIMES or name.endswith(".pdf"):
        return "pdf"
    if (mime or "") in _DOCX_MIMES or name.endswith(".docx"):
        return "docx"
    return "text"


def source_info(conn: Any, document_id: str) -> dict[str, Any]:
    """What kind of file a document is and, for a PDF, which pages are scans.

    ``{"format": "pdf"|"docx"|"text", "scanned_pages": [14, 15], "origins": [...] | None}``. Never raises: when
    the file cannot be read the format is still reported and ``origins`` is ``None`` (callers then treat a PDF
    as possibly scanned).
    """
    info: dict[str, Any] = {"format": "text", "scanned_pages": [], "origins": None}
    if conn is None or not document_id:
        return info
    try:
        doc = conn.execute(
            "SELECT source_uri, mime_type, current_version_id FROM documents WHERE document_id = %s", (document_id,)
        ).fetchone()
        if not doc:
            return info
        uri, mime = doc["source_uri"], doc["mime_type"]
        if doc["current_version_id"]:
            ver = conn.execute(
                "SELECT storage_uri, mime_type FROM document_versions WHERE version_id = %s AND document_id = %s",
                (doc["current_version_id"], document_id),
            ).fetchone()
            if ver and ver["storage_uri"]:
                uri, mime = ver["storage_uri"], ver["mime_type"] or mime
        info["format"] = _format_of(mime, uri)
        if info["format"] == "pdf" and uri:
            from app.storage.object_store import get_object_store

            origins = page_origins(get_object_store().get(uri))
            info["origins"] = origins
            info["scanned_pages"] = [i for i, o in enumerate(origins, start=1) if o == SCANNED_OCR]
    except Exception as exc:  # the file may be missing from this machine's store; the format is still known
        log.warning("could not read page origins for %s: %s", document_id, exc)
    return info


def page_origin(info: dict[str, Any], page: int | None) -> str | None:
    """Origin of one page; ``scanned_ocr`` when unknown for a PDF with any scanned page, else ``None``."""
    if info.get("format") != "pdf":
        return None
    origins = info.get("origins")
    if origins and page and 1 <= page <= len(origins):
        return origins[page - 1]
    return SCANNED_OCR if info.get("scanned_pages") or origins is None else BORN_DIGITAL
