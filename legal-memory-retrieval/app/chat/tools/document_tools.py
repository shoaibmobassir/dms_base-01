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
    __slots__ = ("doc_id", "document_id", "filename", "text", "version_id", "version_number", "attached")

    def __init__(
        self,
        doc_id: str,
        document_id: str,
        filename: str,
        text: str = "",
        version_id: str | None = None,
        version_number: int | None = None,
        attached: bool = False,
    ):
        self.attached = attached
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


def add_documents_to_index(index: DocIndex, documents: list[tuple[str, str]]) -> DocIndex:
    """Put documents the lawyer attached first in the index, ahead of retrieval hits.

    `documents` is [(document_id, filename)]. Existing entries keep their slug.
    """
    known = {entry.document_id for entry in index.values()}
    added: DocIndex = {}
    for document_id, filename in documents:
        if document_id in known:
            for entry in index.values():
                if entry.document_id == document_id:
                    entry.attached = True
            continue
        if not document_id:
            continue
        known.add(document_id)
        slug = f"doc-{len(index) + len(added)}"
        added[slug] = DocEntry(doc_id=slug, document_id=document_id, filename=filename or document_id, attached=True)
    return {**added, **index}


def build_doc_availability(index: DocIndex) -> list[dict[str, str]]:
    """Return a list of {doc_id, filename} for the system prompt."""
    return [
        {"doc_id": slug, "filename": entry.filename, "attached": entry.attached}
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
            "page": page_at(text, m.start()),
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
                # Leave text empty: a hit is one chunk, and read_document must load the whole document.
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

PAGE_MARKER_RE = re.compile(r"^\[Page (\d+)\]$", re.MULTILINE)


def fetch_document_pages(conn, document_id: str) -> list[tuple[int, str]]:
    """Return [(page_number, text)] for the current version, in reading order.

    Prefers extraction blocks (exact page per block). Falls back to leaf chunks,
    which carry the page of their first block. Parent chunks are skipped because
    they repeat their children's text.
    """
    rows = conn.execute(
        """
        SELECT b.page_number, b.text
        FROM document_blocks b
        JOIN documents d ON d.document_id = b.document_id
        WHERE b.document_id = %s
          AND (d.current_version_id IS NULL OR b.version_id = d.current_version_id)
        ORDER BY b.sequence ASC
        """,
        (document_id,),
    ).fetchall()
    if not rows:
        rows = conn.execute(
            """
            SELECT page_number, text FROM chunks
            WHERE document_id = %s AND NOT COALESCE(is_parent, false)
            ORDER BY chunk_index ASC
            """,
            (document_id,),
        ).fetchall()

    pages: list[tuple[int, list[str]]] = []
    for row in rows:
        page = int(row["page_number"] or 1)
        text = str(row["text"] or "").strip()
        if not text:
            continue
        if pages and pages[-1][0] == page:
            pages[-1][1].append(text)
        else:
            pages.append((page, [text]))
    return [(page, "\n".join(parts)) for page, parts in pages]


def paged_text(pages: list[tuple[int, str]]) -> str:
    """Join pages with the [Page N] markers the citation rules refer to."""
    return "\n\n".join(f"[Page {page}]\n{text}" for page, text in pages)


def page_at(text: str, offset: int) -> int | None:
    """Page number in effect at a character offset of paged_text output."""
    page = None
    for match in PAGE_MARKER_RE.finditer(text):
        if match.start() > offset:
            break
        page = int(match.group(1))
    return page


def _fetch_document_text(conn, document_id: str) -> str:
    """Full extracted text with [Page N] markers, so citations can name a real page."""
    pages = fetch_document_pages(conn, document_id)
    if not pages:
        return "Document could not be read."
    return paged_text(pages)
