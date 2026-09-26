"""
Word positions for scanned PDF pages.

Scanned pages carry no text layer, so the viewer cannot find a cited quote on
them. This module renders one page, reads it with OCR in word-box mode, and
returns each word with its box as fractions of the page (0..1), so the viewer
can draw highlights at any zoom. Results are cached by file hash and page.

Uses the same system tools as ingest OCR (pdftoppm, tesseract), run as separate
processes.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.config import settings

RENDER_DPI = 200
OCR_TIMEOUT_SECONDS = 60


class WordsUnavailable(Exception):
    """OCR tools are missing or the page could not be read."""


def ocr_available() -> bool:
    return shutil.which("pdftoppm") is not None and shutil.which("tesseract") is not None


def _cache_path(pdf: bytes, page_number: int) -> Path:
    folder = Path(settings.object_store_root) / "render_cache"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{hashlib.sha256(pdf).hexdigest()}-p{page_number}-words.json"


def parse_tesseract_tsv(tsv: str, image_width: int, image_height: int) -> list[dict[str, Any]]:
    """Turn Tesseract TSV rows into words with page-relative boxes and a line key."""
    words: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row.get("level") != "5":
            continue
        text = (row.get("text") or "").strip()
        if not text:
            continue
        left, top = int(row["left"]), int(row["top"])
        width, height = int(row["width"]), int(row["height"])
        words.append({
            "text": text,
            "line": f'{row["block_num"]}.{row["par_num"]}.{row["line_num"]}',
            "x0": round(left / image_width, 5),
            "y0": round(top / image_height, 5),
            "x1": round((left + width) / image_width, 5),
            "y1": round((top + height) / image_height, 5),
        })
    return words


def page_words(pdf: bytes, page_number: int) -> dict[str, Any]:
    """OCR word boxes for one page (1-based). Cached."""
    cached = _cache_path(pdf, page_number)
    if cached.is_file():
        return json.loads(cached.read_text())
    if not ocr_available():
        raise WordsUnavailable("OCR tools are not installed on the server.")

    with tempfile.TemporaryDirectory(prefix="page-words-") as work:
        source = Path(work) / "doc.pdf"
        source.write_bytes(pdf)
        prefix = Path(work) / "page"
        try:
            subprocess.run(
                ["pdftoppm", "-r", str(RENDER_DPI), "-f", str(page_number), "-l", str(page_number),
                 "-png", "-singlefile", str(source), str(prefix)],
                check=True, capture_output=True, timeout=OCR_TIMEOUT_SECONDS,
            )
            image = prefix.with_suffix(".png")
            if not image.is_file():
                raise WordsUnavailable("That page does not exist.")
            ocr = subprocess.run(
                ["tesseract", str(image), "stdout", "-l", "eng", "tsv"],
                check=True, capture_output=True, text=True, timeout=OCR_TIMEOUT_SECONDS,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise WordsUnavailable("The page could not be read.") from exc
        width, height = _png_size(image)

    result = {"page": page_number, "words": parse_tesseract_tsv(ocr.stdout, width, height)}
    cached.write_text(json.dumps(result))
    return result


def _png_size(path: Path) -> tuple[int, int]:
    """Width and height from the PNG header (no imaging library needed)."""
    with path.open("rb") as fh:
        header = fh.read(24)
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")
