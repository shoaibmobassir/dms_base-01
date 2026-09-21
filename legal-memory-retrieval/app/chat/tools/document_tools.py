"""
Document tools: read_document, fetch_documents, find_in_document.
These tools give the LLM agent on-demand access to the full text of
documents in the DMS during a chat session.

Clean-room independent implementation for FirmOS legal assistant chatbot.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.chat.session_doc_cache import get as session_doc_get
from app.chat.session_doc_cache import put as session_doc_put
from app.chat.spotlight import spotlight
from app.retrieval.engine import retrieve

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Document index: maps chat-local slugs to real document metadata
# ---------------------------------------------------------------------------

class DocEntry:
    """Metadata for one document available in the chat context."""
    __slots__ = ("doc_id", "document_id", "filename", "text", "version_id", "version_number")

    def __init__(
        self,
        doc_id: str,
        document_id: str,
        filename: str,
        text: str = "",
        version_id: str | None = None,
        version_number: int | None = None,
    ):
        self.doc_id = doc_id
        self.document_id = document_id
        self.filename = filename
        self.text = text
        self.version_id = version_id
        self.version_number = version_number


DocIndex = dict[str, DocEntry]
DocStore = dict[str, str]  # doc_id → full extracted text


# ---------------------------------------------------------------------------
# Build a doc index from retrieval hits
# ---------------------------------------------------------------------------

def build_doc_index_from_hits(hits: list[dict[str, Any]]) -> DocIndex:
    """
    Build a chat-local document index from retrieval hits.
    Each unique document gets a slug like 'doc-0', 'doc-1', etc.
    """
    seen: dict[str, str] = {}  # document_id → doc_slug
    index: DocIndex = {}
    counter = 0

    for hit in hits:
        doc_uuid = str(hit.get("document_id", ""))
        if not doc_uuid:
            continue
        if doc_uuid in seen:
            continue
        slug = f"doc-{counter}"
        counter += 1
        seen[doc_uuid] = slug
        index[slug] = DocEntry(
            doc_id=slug,
            document_id=doc_uuid,
            filename=hit.get("filename", hit.get("title", f"Document {counter}")),
            text=hit.get("full_text", ""),
            version_id=_hit_version(hit),
        )
    return index


def build_doc_availability(index: DocIndex) -> list[dict[str, str]]:
    """Return a list of {doc_id, filename} for the system prompt."""
    return [
        {"doc_id": slug, "filename": entry.filename}
        for slug, entry in index.items()
    ]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def read_document(
    doc_id: str,
    doc_index: DocIndex,
    doc_store: DocStore,
    conn: Any = None,
    nonce: str | None = None,
    member_id: str | None = None,
) -> dict[str, Any]:
    """
    Read the full text of a document by its chat-local slug.
    If text is not already cached in the store, try to fetch from DB.
    """
    entry = doc_index.get(doc_id)
    if not entry:
        return {"error": f"Document '{doc_id}' not found."}

    text = resolve_document_text(entry, doc_store, conn, member_id)

    fenced = spotlight(text, nonce) if nonce else text
    return {
        "doc_id": doc_id,
        "filename": entry.filename,
        "text": fenced,
        "event": {
            "type": "doc_read",
            "filename": entry.filename,
            "document_id": entry.document_id,
            "version_id": entry.version_id,
            "version_number": entry.version_number,
        },
    }


def fetch_documents(
    doc_ids: list[str],
    doc_index: DocIndex,
    doc_store: DocStore,
    conn: Any = None,
    nonce: str | None = None,
    member_id: str | None = None,
) -> dict[str, Any]:
    """Batch-read multiple documents. Returns merged results."""
    results: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for doc_id in doc_ids:
        result = read_document(
            doc_id, doc_index, doc_store, conn, nonce, member_id=member_id,
        )
        results.append(result)
        if "event" in result:
            events.append(result["event"])
    return {"documents": results, "events": events}


def find_in_document(
    doc_id: str,
    query: str,
    doc_index: DocIndex,
    doc_store: DocStore,
    conn: Any = None,
    max_results: int = 20,
    context_chars: int = 80,
    member_id: str | None = None,
) -> dict[str, Any]:
    """
    Case-insensitive substring search within a document.
    Returns matches with surrounding context — like Ctrl+F.
    """
    entry = doc_index.get(doc_id)
    if not entry:
        return {"error": f"Document '{doc_id}' not found."}

    text = resolve_document_text(entry, doc_store, conn, member_id)
    if text == "Document could not be read.":
        return {"error": "Document could not be read.", "total_matches": 0, "matches": []}

    # Case-insensitive, whitespace-tolerant search
    # Build a regex that treats runs of whitespace as flexible
    escaped = re.escape(query)
    # re.escape turns spaces into '\ ' — replace those with \s+
    flexible = re.sub(r"(?:\\ )+", r"\\s+", escaped)
    pattern = re.compile(flexible, re.IGNORECASE)
    matches: list[dict[str, Any]] = []
    for m in pattern.finditer(text):
        if len(matches) >= max_results:
            break
        start = max(0, m.start() - context_chars)
        end = min(len(text), m.end() + context_chars)
        matches.append({
            "match": m.group(),
            "context": text[start:end],
            "start": m.start(),
            "end": m.end(),
        })

    return {
        "doc_id": doc_id,
        "filename": entry.filename,
        "query": query,
        "total_matches": len(matches),
        "matches": matches,
        "event": {
            "type": "doc_find",
            "filename": entry.filename,
            "document_id": entry.document_id,
            "version_id": entry.version_id,
            "version_number": entry.version_number,
            "query": query,
            "total_matches": len(matches),
        },
    }


def search_firm_records(
    query: str,
    doc_index: DocIndex,
    conn: Any,
    member_id: str | None = None,
    k: int = 8,
) -> dict[str, Any]:
    """Search the firm corpus and merge new documents into the chat-local index."""
    needle = (query or "").strip()
    if not needle:
        return {"error": "Search query is empty.", "results": []}
    if conn is None:
        return {"error": "Search is unavailable.", "results": []}

    hits, _latency = retrieve(conn, needle, member_id, k=max(1, min(int(k or 8), 20)))
    existing_docs = {entry.document_id for entry in doc_index.values()}
    next_idx = len(doc_index)
    results: list[dict[str, Any]] = []

    for hit in hits:
        document_id = str(hit.get("document_id") or "")
        if not document_id:
            continue
        slug = None
        for existing_slug, entry in doc_index.items():
            if entry.document_id == document_id:
                slug = existing_slug
                break
        if slug is None:
            slug = f"doc-{next_idx}"
            next_idx += 1
            filename = hit.get("title") or hit.get("filename") or document_id
            doc_index[slug] = DocEntry(
                doc_id=slug,
                document_id=document_id,
                filename=str(filename),
                text=str(hit.get("text") or ""),
                version_id=_hit_version(hit),
            )
        snippet = " ".join(str(hit.get("text") or "").split())[:280]
        results.append({
            "doc_id": slug,
            "document_id": document_id,
            "filename": doc_index[slug].filename,
            "matter_id": hit.get("matter_id"),
            "title": hit.get("title"),
            "snippet": snippet,
            "newly_added": document_id not in existing_docs,
        })
        existing_docs.add(document_id)

    return {
        "query": needle,
        "count": len(results),
        "results": results,
        "event": {
            "type": "search_results",
            "query": needle,
            "count": len(results),
            "filenames": [r["filename"] for r in results[:8]],
        },
    }


def _hit_version(hit: dict[str, Any]) -> str | None:
    for key in ("version_id", "current_version_id", "version"):
        value = hit.get(key)
        if value:
            return str(value)
    return None


def resolve_document_text(
    entry: DocEntry,
    doc_store: DocStore,
    conn: Any = None,
    member_id: str | None = None,
) -> str:
    """Return document text, filling the in-turn store and the member cache."""
    if entry.doc_id in doc_store:
        return doc_store[entry.doc_id]

    version = entry.version_id or _lookup_version(conn, entry.document_id)
    if version and not entry.version_id:
        entry.version_id = version
    if member_id and version:
        cached = session_doc_get(member_id, entry.document_id, version)
        if cached is not None:
            doc_store[entry.doc_id] = cached
            entry.text = cached
            return cached

    if entry.text:
        doc_store[entry.doc_id] = entry.text
        return entry.text

    if conn:
        text = _fetch_document_text(conn, entry.document_id)
        _remember(entry, doc_store, text, member_id)
        return text

    return "Document could not be read."


def _remember(
    entry: DocEntry,
    doc_store: DocStore,
    text: str,
    member_id: str | None,
) -> None:
    doc_store[entry.doc_id] = text
    entry.text = text
    session_doc_put(member_id, entry.document_id, entry.version_id, text)


def _lookup_version(conn: Any, document_id: str) -> str | None:
    if conn is None or not document_id:
        return None
    try:
        row = conn.execute(
            """
            SELECT current_version_id, version
            FROM documents
            WHERE document_id = %s
            """,
            (document_id,),
        ).fetchone()
    except Exception as exc:
        logger.debug("version lookup failed for %s: %s", document_id, exc)
        return None
    if not row:
        return None
    current = row.get("current_version_id") if isinstance(row, dict) else None
    label = row.get("version") if isinstance(row, dict) else None
    if current:
        return str(current)
    if label:
        return str(label)
    return None


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _fetch_document_text(conn, document_id: str) -> str:
    """Fetch the full extracted text for a document from the chunks table."""
    rows = conn.execute(
        """
        SELECT text FROM chunks
        WHERE document_id = %s
        ORDER BY chunk_index ASC
        """,
        (document_id,),
    ).fetchall()
    if not rows:
        return "Document could not be read."
    return "\n".join(str(r["text"] or "") for r in rows)
