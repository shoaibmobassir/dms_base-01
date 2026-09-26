"""
Review tools: propose_edits.

The assistant suggests concrete changes to one document. Each suggestion is
located in the document text so the lawyer can see it on the page, then
accepted or rejected in the chat. Accepted suggestions become a tracked-changes
Word file (see apply_accepted_edits).
"""

from __future__ import annotations

import uuid
from typing import Any

from app.chat.tools.document_tools import (
    PAGE_MARKER_RE,
    DocIndex,
    DocStore,
    page_at,
    resolve_document_text,
)
from app.chat.verify_citations import locate_quote

MAX_EDITS = 20
EDIT_STATUSES = ("pending", "accepted", "rejected")


def propose_edits(
    doc_id: str,
    edits: list[dict[str, Any]],
    doc_index: DocIndex,
    doc_store: DocStore,
    conn: Any = None,
    member_id: str | None = None,
) -> dict[str, Any]:
    """Validate suggested edits against the document text and package them for review."""
    entry = doc_index.get(doc_id)
    if not entry:
        return {"error": f"Document '{doc_id}' not found."}
    if not isinstance(edits, list) or not edits:
        return {"error": "No edits were provided."}

    text = resolve_document_text(entry, doc_store, conn, member_id)
    proposals: list[dict[str, Any]] = []
    for raw in edits[:MAX_EDITS]:
        if not isinstance(raw, dict):
            continue
        original = str(raw.get("original") or "").strip()
        proposed = str(raw.get("proposed") or "").strip()
        if not original and not proposed:
            continue
        location = locate_quote(text, original) if original else None
        proposals.append({
            "id": uuid.uuid4().hex[:10],
            "original": location.excerpt if location else original,
            "proposed": proposed,
            "reason": str(raw.get("reason") or "").strip(),
            "page": page_at(text, location.start) if location else None,
            "located": location is not None,
            "status": "pending",
        })

    if not proposals:
        return {"error": "None of the edits had text to change."}

    unlocated = [p["id"] for p in proposals if not p["located"]]
    return {
        "doc_id": doc_id,
        "filename": entry.filename,
        "proposed": len(proposals),
        "not_found_in_document": unlocated,
        "note": (
            "The edits are shown to the lawyer as cards to accept or reject. "
            "Summarise them briefly; do not repeat every edit in prose."
        ),
        "event": {
            "type": "edit_proposals",
            "document_id": entry.document_id,
            "version_id": entry.version_id,
            "filename": entry.filename,
            "edits": proposals,
        },
    }


def strip_page_markers(text: str) -> str:
    return PAGE_MARKER_RE.sub("", text).replace("\n\n\n", "\n\n").strip()


def apply_accepted_edits(text: str, edits: list[dict[str, Any]]) -> tuple[str, int]:
    """Apply accepted edits to plain document text. Returns (revised_text, applied_count).

    An edit whose original passage cannot be found is skipped, never guessed.
    """
    revised = text
    applied = 0
    for edit in edits:
        if edit.get("status") != "accepted":
            continue
        original = str(edit.get("original") or "")
        proposed = str(edit.get("proposed") or "")
        if not original:
            continue
        location = locate_quote(revised, original)
        if location is None:
            continue
        revised = revised[: location.start] + proposed + revised[location.end :]
        applied += 1
    return revised, applied
