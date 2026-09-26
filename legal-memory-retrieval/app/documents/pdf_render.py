"""
PDF rendering for the in-app document viewer.

PDFs pass through unchanged. Word and other office files are converted with a
LibreOffice binary run as a separate process, if one is installed on the server
(it is not bundled or linked). Results are cached by content hash so a document
is converted once.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import settings

PDF_MIME = "application/pdf"
CONVERTIBLE_SUFFIXES = {".docx", ".doc", ".odt", ".rtf", ".txt", ".xlsx", ".pptx"}
CONVERT_TIMEOUT_SECONDS = 90
_MAC_APP_BINARY = "/Applications/LibreOffice.app/Contents/MacOS/soffice"


class RenderUnavailable(Exception):
    """The file cannot be shown as PDF on this server."""


def converter_path() -> str | None:
    configured = os.environ.get("OFFICE_CONVERTER_PATH")
    if configured and Path(configured).is_file():
        return configured
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return _MAC_APP_BINARY if Path(_MAC_APP_BINARY).is_file() else None


def _cache_dir() -> Path:
    path = Path(settings.object_store_root) / "render_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_pdf(data: bytes, mime: str | None, filename: str) -> bool:
    return data[:5] == b"%PDF-" or mime == PDF_MIME or filename.lower().endswith(".pdf")


def to_pdf(data: bytes, mime: str | None, filename: str) -> bytes:
    """Return PDF bytes for the viewer, converting office files when possible."""
    if _is_pdf(data, mime, filename):
        return data

    suffix = Path(filename).suffix.lower()
    if suffix not in CONVERTIBLE_SUFFIXES:
        raise RenderUnavailable(f"{suffix or 'This file type'} cannot be shown as pages.")

    digest = hashlib.sha256(data).hexdigest()
    cached = _cache_dir() / f"{digest}.pdf"
    if cached.is_file():
        return cached.read_bytes()

    binary = converter_path()
    if binary is None:
        raise RenderUnavailable("No document converter is installed on the server.")

    with tempfile.TemporaryDirectory(prefix="render-") as work:
        source = Path(work) / f"source{suffix}"
        source.write_bytes(data)
        try:
            subprocess.run(
                [
                    binary,
                    "--headless",
                    "--norestore",
                    f"-env:UserInstallation=file://{work}/profile",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    work,
                    str(source),
                ],
                check=True,
                capture_output=True,
                timeout=CONVERT_TIMEOUT_SECONDS,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise RenderUnavailable("The document could not be converted for viewing.") from exc
        produced = Path(work) / "source.pdf"
        if not produced.is_file():
            raise RenderUnavailable("The document could not be converted for viewing.")
        pdf = produced.read_bytes()

    cached.write_bytes(pdf)
    return pdf
