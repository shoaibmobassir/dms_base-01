"""comment_on_document: the Assistant leaves comments on passages of a document.

Each comment is anchored to a quoted passage. The reader finds the passage again by its text, so the comment
shows on the page like one a colleague wrote by selecting text. Reading the document is enough to comment on it.
"""
from __future__ import annotations

import re
from typing import Any

from app.chat.tools.document_tools import DocIndex
from app.chat.tools.edit_guard import scan_only_words, scrub_scan_claims
from app.documents.text_origin import source_info
from app.documents import comments
from app.documents.editing import EditError

MAX_COMMENTS = 25
_MIN_QUOTE = 8
_FIND_CHARS = 140


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _locate(blocks: list[dict[str, Any]], quote: str) -> dict[str, Any] | None:
    """The block that holds the quote (its opening words are enough for a long quote)."""
    needle = _norm(quote)[:_FIND_CHARS]
    if len(needle) < _MIN_QUOTE:
        return None
    for block in blocks:
        if needle in _norm(str(block.get("text") or "")):
            return block
    return None


def comment_on_document_tool(
    arguments: dict[str, Any], doc_index: DocIndex, conn: Any, member_id: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from app.documents.canonical import get_version_blocks

    entry = doc_index.get(str(arguments.get("doc_id") or ""))
    items = arguments.get("comments") or []
    if not entry:
        return {"error": f"Document '{arguments.get('doc_id')}' not found."}, []
    if not isinstance(items, list) or not items:
        return {"error": "Give the comments to add: each with the exact quote it is about and the comment."}, []
    if not entry.version_id:
        return {"error": "That document has no readable version to comment on."}, []
    blocks = get_version_blocks(entry.version_id)
    if not blocks:
        return {"error": "The text of this document is not ready to comment on yet."}, []

    # On scanned pages the text is an OCR reading: a comment calling its spacing or spelling an error describes the
    # scan, not the document, and once added it stays on the document for everyone. Such comments are not added.
    info = source_info(conn, entry.document_id)
    paged = "".join(f"[Page {int(b.get('page_number') or 1)}]\n{b.get('text') or ''}\n" for b in blocks)
    scan_only = scan_only_words(paged, info.get("scanned_pages") or []) if info.get("format") == "pdf" else set()
    added: list[dict[str, Any]] = []
    missing: list[str] = []
    artifacts: list[str] = []
    for item in items[:MAX_COMMENTS]:
        quote = str(item.get("quote") or "").strip()
        body = str(item.get("comment") or "").strip()
        if scan_only and scrub_scan_claims(f'"{quote}": {body}', scan_only, paged)[1]:
            artifacts.append(quote[:80])
            continue
        block = _locate(blocks, quote)
        if block is None:
            missing.append(quote[:80])
            continue
        try:
            made = comments.add_comment(
                conn, entry.document_id, member_id, body=body, version_id=entry.version_id,
                page=int(block.get("page_number") or 1), rects=[], quote=quote[:600],
            )
        except EditError as exc:
            return {"error": exc.detail if hasattr(exc, "detail") else str(exc), "added": len(added)}, []
        added.append({"comment_id": made["comment_id"], "quote": quote[:300], "body": body, "page": made.get("page")})

    if not added:
        if artifacts and not missing:
            return {"doc_id": entry.doc_id, "filename": entry.filename, "added": 0, "dropped_as_reading_artifacts": artifacts,
                    "note": ("Every comment was about spacing or spelling in text machine-read from a scanned page. Those "
                             "are not defects in the document; do not report them.")}, []
        return {"doc_id": entry.doc_id, "filename": entry.filename, "added": 0, "not_found": missing,
                "note": "None of the quotes matched the document text. Copy each quote verbatim from the text you read."}, []
    event = {"type": "comments_added", "document_id": entry.document_id, "filename": entry.filename,
             "version_id": entry.version_id, "comments": added}
    return {
        "doc_id": entry.doc_id, "filename": entry.filename, "added": len(added), "not_found": missing,
        **({"dropped_as_reading_artifacts": artifacts,
            "dropped_note": "These were OCR reading differences, not document defects. Do not mention them."} if artifacts else {}),
        "note": "The comments are on the document now and listed to the lawyer. Say briefly what you flagged and why.",
    }, [event]
