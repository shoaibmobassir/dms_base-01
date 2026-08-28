from __future__ import annotations

import re

DOC_ID_RE = re.compile(r"\bDOC-\d+\b", re.I)


def extract_document_ids(text: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in DOC_ID_RE.findall(text or ""):
        doc_id = match.upper()
        if doc_id not in seen:
            seen.add(doc_id)
            ordered.append(doc_id)
    return ordered


def allowed_document_ids(hits: list[dict]) -> set[str]:
    return {str(h["document_id"]).upper() for h in hits if h.get("document_id")}


def filter_citations(cited: list[str], hits: list[dict]) -> list[str]:
    allowed = allowed_document_ids(hits)
    kept: list[str] = []
    seen: set[str] = set()
    for doc_id in cited:
        key = doc_id.upper()
        if key in allowed and key not in seen:
            seen.add(key)
            kept.append(key)
    return kept
