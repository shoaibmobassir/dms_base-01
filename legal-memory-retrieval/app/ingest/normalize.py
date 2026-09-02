"""Normalizer: map filenames → document_type, extract matter metadata.

Reasoning:
  The 7 real PDFs don't have structured metadata. This module infers
  document_type from filename patterns, and uses the manifest to map
  files to matter_ids. Reuses regex patterns from doc-search's
  metadata_extractor but adapted for legal-memory-retrieval's schema.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.ingest.models import MatterManifest

# ── Document type inference from filename ────────────────────────────

_DOCTYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Affidavit", re.compile(r"\baffidavit\b", re.I)),
    ("Written Submission", re.compile(r"\bwritten\s+submission\b", re.I)),
    ("Brief Note", re.compile(r"\bbrief\s+note\b", re.I)),
    ("Rejoinder", re.compile(r"\brejoinder\b", re.I)),
    ("Final Reply", re.compile(r"\bfinal\s+reply\b", re.I)),
    ("Reply", re.compile(r"\breply\b", re.I)),
    ("Writ Petition", re.compile(r"\bwrit\s+petition\b", re.I)),
    ("Petition", re.compile(r"\bpetition\b", re.I)),
    ("Research Memo", re.compile(r"\bresearch\s+(memo|note)\b", re.I)),
    ("Impleadment Application", re.compile(r"\bimpleadment\b", re.I)),
]


def infer_document_type(filename: str, text: str = "") -> str:
    """Infer document type from filename, fallback to first 2000 chars of text."""
    combined = f"{filename}\n{text[:2000]}"
    for doc_type, pattern in _DOCTYPE_PATTERNS:
        if pattern.search(combined):
            return doc_type
    return "Legal Document"


def match_matter(filename: str, manifests: list[MatterManifest]) -> MatterManifest | None:
    """Match a filename to a matter manifest using file_patterns."""
    for manifest in manifests:
        for pattern in manifest.file_patterns:
            if re.search(pattern, filename, re.I):
                return manifest
    return None


def normalize_title(filename: str) -> str:
    """Convert filename to a readable title."""
    stem = Path(filename).stem
    # Remove common suffixes like dates
    stem = re.sub(r"\s*\d{2}\.\d{2}\.\d{4}\s*$", "", stem)
    return stem.strip()
