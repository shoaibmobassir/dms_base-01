"""Extract structured DMS metadata from PDF filenames and content.

Reasoning:
  The DMS portal returns responses with matter_id, document_type, client, forum,
  case_number, and tags. Our 7 PDFs contain this information embedded in their
  filenames and first-page text, but it isn't stored anywhere structured.
  This module extracts it using regex patterns tuned to Indian legal documents.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


# ── Document type inference ──────────────────────────────────────────────────

_DOCTYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Affidavit", re.compile(r"\baffidavit\b", re.I)),
    ("Written Submission", re.compile(r"\bwritten\s+submission\b", re.I)),
    ("Brief Note", re.compile(r"\bbrief\s+note\b", re.I)),
    ("Rejoinder", re.compile(r"\brejoinder\b", re.I)),
    ("Reply", re.compile(r"\breply\b", re.I)),
    ("Writ Petition", re.compile(r"\bwrit\s+petition\b", re.I)),
    ("Petition", re.compile(r"\bpetition\b", re.I)),
    ("Research Memo", re.compile(r"\bresearch\s+(memo|note)\b", re.I)),
    ("Final Reply", re.compile(r"\bfinal\s+reply\b", re.I)),
    ("Impleadment Application", re.compile(r"\bimpleadment\b", re.I)),
]

# ── Forum / court inference ──────────────────────────────────────────────────

_FORUM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("CERC", re.compile(r"\bCERC\b")),
    ("APTEL", re.compile(r"\bAPTEL\b")),
    ("MERC", re.compile(r"\bMERC\b")),
    ("MSEDCL", re.compile(r"\bMSEDCL\b")),
    ("Supreme Court", re.compile(r"\bSupreme\s+Court\b", re.I)),
    ("High Court", re.compile(r"\bHigh\s+Court\b", re.I)),
    ("NCLT", re.compile(r"\bNCLT\b")),
    ("NCLAT", re.compile(r"\bNCLAT\b")),
    ("SEBI", re.compile(r"\bSEBI\b")),
]

# ── Case number / petition number ────────────────────────────────────────────

_CASE_NUMBER_RES = [
    re.compile(r"P\.?\s*N\.?\s*(\d+\s+of\s+\d{4})", re.I),
    re.compile(r"Petition\s+No\.?\s*(\d+\s+of\s+\d{4})", re.I),
    re.compile(r"(?:CA|Civil\s+Appeal)\s+(\d+\s+of\s+\d{4})", re.I),
    re.compile(r"(?:MP|Misc\.?\s*Petition)\s+(\d+\s+of\s+\d{4})", re.I),
    re.compile(r"(?:APL|Appeal)\s*\.?\s*(\d+\s+of\s+\d{4})", re.I),
    re.compile(r"(\d+-MP-\d{4})", re.I),
]

# ── Matter ID ────────────────────────────────────────────────────────────────

_MATTER_ID_RE = re.compile(r"\bMWSP[_\-]PROJ\d+\b", re.I)
_MATTER_ID_ALT = re.compile(r"\bMTR-\d{4}-\d+\b", re.I)

# ── Client name heuristics ───────────────────────────────────────────────────

_CLIENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Avaada Energy Pvt. Ltd.", re.compile(r"\bAvaada\b", re.I)),
    ("MSEDCL", re.compile(r"\bMSEDCL\b")),
    ("Vector Green Energy Pvt. Ltd.", re.compile(r"\bVector\s+Green\b", re.I)),
    ("AEPL", re.compile(r"\bAEPL\b")),
    ("CTUIL", re.compile(r"\bCTUIL\b")),
]

# ── Tag inference ────────────────────────────────────────────────────────────

_TAG_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Force Majeure", re.compile(r"\bforce\s+majeure\b", re.I)),
    ("Wind Power", re.compile(r"\bwind\s+power\b|\bwind\s+energy\b", re.I)),
    ("Solar Power", re.compile(r"\bsolar\s+power\b|\bsolar\s+energy\b", re.I)),
    ("Regulatory", re.compile(r"\bregulatory\b|\bregulation\b", re.I)),
    ("Tariff", re.compile(r"\btariff\b", re.I)),
    ("PPA", re.compile(r"\bPPA\b|\bpower\s+purchase\s+agreement\b", re.I)),
    ("Arbitration", re.compile(r"\barbitration\b", re.I)),
    ("Commissioning", re.compile(r"\bcommission(?:ing)?\b", re.I)),
    ("Change in Law", re.compile(r"\bchange\s+in\s+law\b", re.I)),
    ("Electricity", re.compile(r"\belectricity\b", re.I)),
    ("Connectivity", re.compile(r"\bconnectivity\b", re.I)),
    ("Transmission", re.compile(r"\btransmission\b", re.I)),
    ("Flooding", re.compile(r"\bflood(?:ing|s)?\b", re.I)),
    ("Rainfall", re.compile(r"\brainfall\b|\bheavy\s+rain\b", re.I)),
    ("Gujarat", re.compile(r"\bGujarat\b", re.I)),
    ("Maharashtra", re.compile(r"\bMaharashtra\b", re.I)),
    ("Delay", re.compile(r"\bdelay(?:s|ed)?\b", re.I)),
    ("Indemnity", re.compile(r"\bindemnity\b|\bindemnification\b", re.I)),
]


def extract_document_type(filename: str, text: str) -> str:
    """Infer document type from filename first, then from body text."""
    combined = f"{filename}\n{text[:2000]}"
    for doc_type, pattern in _DOCTYPE_PATTERNS:
        if pattern.search(combined):
            return doc_type
    return "Legal Document"


def extract_forum(text: str) -> str | None:
    """Identify the court/forum from text content."""
    for forum, pattern in _FORUM_PATTERNS:
        if pattern.search(text[:5000]):
            return forum
    return None


def extract_case_number(text: str) -> str | None:
    """Extract case/petition number."""
    for regex in _CASE_NUMBER_RES:
        m = regex.search(text[:5000])
        if m:
            return m.group(0).strip()
    return None


def extract_matter_id(text: str) -> str | None:
    """Extract DMS matter ID like MWSP_PROJ000031537."""
    m = _MATTER_ID_RE.search(text[:10000])
    if m:
        return m.group(0)
    m = _MATTER_ID_ALT.search(text[:10000])
    if m:
        return m.group(0)
    return None


def extract_client(text: str) -> str | None:
    """Heuristic client name extraction from first pages."""
    for client, pattern in _CLIENT_PATTERNS:
        if pattern.search(text[:5000]):
            return client
    return None


def extract_tags(filename: str, text: str) -> list[str]:
    """Extract all matching topic tags from combined filename + text."""
    combined = f"{filename}\n{text[:8000]}"
    tags: list[str] = []
    for tag, pattern in _TAG_PATTERNS:
        if pattern.search(combined):
            tags.append(tag)
    return tags


def extract_all(filename: str, full_text: str) -> dict:
    """Extract all metadata from a PDF.

    Returns a dict with: document_type, forum, case_number, matter_id, client_name, tags
    """
    return {
        "document_type": extract_document_type(filename, full_text),
        "forum": extract_forum(full_text),
        "case_number": extract_case_number(full_text),
        "matter_id": extract_matter_id(full_text),
        "client_name": extract_client(full_text),
        "tags": extract_tags(filename, full_text),
    }


# ── Override file support ────────────────────────────────────────────────────

_OVERRIDE_PATH = Path(__file__).parent / "docs_metadata.json"


def load_overrides() -> dict[str, dict]:
    """Load manual metadata overrides from docs_metadata.json.

    Format: {"filename.pdf": {"matter_id": "...", "tags": [...]}, ...}
    Auto-extracted values are used for any field NOT present in the override.
    """
    if _OVERRIDE_PATH.exists():
        return json.loads(_OVERRIDE_PATH.read_text(encoding="utf-8"))
    return {}


def extract_with_overrides(filename: str, full_text: str) -> dict:
    """Extract metadata, then apply any manual overrides."""
    auto = extract_all(filename, full_text)
    overrides = load_overrides()
    manual = overrides.get(filename, {})
    for key, value in manual.items():
        if value is not None:
            auto[key] = value
    return auto
