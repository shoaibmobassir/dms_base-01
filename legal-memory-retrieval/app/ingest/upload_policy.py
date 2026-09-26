"""What may be uploaded, checked from the file's own bytes (not its name or the
client-declared content type)."""
from __future__ import annotations

import hashlib
import socket
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.config import settings

CHUNK = 1024 * 1024

_ZIP = b"PK\x03\x04"
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy Office (doc/xls/msg)

# extension -> accepted leading bytes (None = must look like text)
ALLOWED: dict[str, tuple[bytes, ...] | None] = {
    ".pdf": (b"%PDF-",),
    ".docx": (_ZIP,),
    ".xlsx": (_ZIP,),
    ".pptx": (_ZIP,),
    ".odt": (_ZIP,),
    ".doc": (_OLE,),
    ".xls": (_OLE,),
    ".msg": (_OLE,),
    ".rtf": (b"{\\rtf",),
    ".txt": None,
    ".md": None,
    ".csv": None,
    ".eml": None,
}


class UploadRejected(ValueError):
    """The upload violates the policy; the message is safe to show the user."""


@dataclass
class ScannedFile:
    sha256: str
    size: int


def check_type(name: str, head: bytes) -> None:
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        raise UploadRejected(f"{name}: file type {ext or '(none)'} is not accepted")
    signatures = ALLOWED[ext]
    if signatures is None:
        if b"\x00" in head:
            raise UploadRejected(f"{name}: expected a text file but found binary content")
        return
    if not any(head.startswith(sig) for sig in signatures):
        raise UploadRejected(f"{name}: content does not match its {ext} extension")


def hash_and_measure(name: str, fileobj: BinaryIO, max_bytes: int) -> ScannedFile:
    """Stream the file once: type check on the first bytes, SHA-256, size cap."""
    fileobj.seek(0)
    digest = hashlib.sha256()
    size = 0
    first = True
    while chunk := fileobj.read(CHUNK):
        if first:
            check_type(name, chunk[:8192])
            first = False
        size += len(chunk)
        if size > max_bytes:
            raise UploadRejected(f"{name}: larger than the {max_bytes // (1024 * 1024)} MB limit")
        digest.update(chunk)
    if first:
        raise UploadRejected(f"{name}: file is empty")
    fileobj.seek(0)
    return ScannedFile(sha256=digest.hexdigest(), size=size)


def scan_for_malware(data: bytes) -> str | None:
    """Return a signature name if the scanner flags ``data``; None if clean or scanning is off.

    Talks to a ClamAV daemon with its INSTREAM protocol (no client library needed).
    Scanner errors raise, so an unavailable scanner never silently passes a file.
    """
    if settings.malware_scanner == "off":
        return None
    if settings.malware_scanner != "clamd":
        raise RuntimeError(f"unknown MALWARE_SCANNER {settings.malware_scanner!r}")
    with socket.create_connection((settings.clamd_host, settings.clamd_port), timeout=60) as sock:
        sock.sendall(b"zINSTREAM\0")
        for i in range(0, len(data), CHUNK):
            part = data[i : i + CHUNK]
            sock.sendall(struct.pack("!L", len(part)) + part)
        sock.sendall(struct.pack("!L", 0))
        reply = b""
        while not reply.endswith(b"\0"):
            got = sock.recv(4096)
            if not got:
                break
            reply += got
    text = reply.rstrip(b"\0").decode(errors="replace")
    if text.endswith("OK"):
        return None
    if "FOUND" in text:
        return text.split(":", 1)[-1].replace("FOUND", "").strip() or "malware"
    raise RuntimeError(f"malware scanner error: {text}")
