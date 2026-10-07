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
from app.config import settings
from app.retrieval.engine import retrieve

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Document index: maps chat-local slugs to real document metadata
# ---------------------------------------------------------------------------

class DocEntry:
    """Metadata for one document available in the chat context."""
    __slots__ = ("doc_id", "document_id", "filename", "text", "version_id", "version_number", "attached",
                 "scanned_pages")

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
        self.scanned_pages: list[int] = []  # PDF pages whose text was read by OCR (set when the document is read)
        self.doc_id = doc_id
        self.document_id = document_id
        self.filename = filename
        self.text = text
        self.version_id = version_id
        self.version_number = version_number


DocIndex = dict[str, DocEntry]

PDF_NOT_EDITABLE = (
    "This document is a PDF, which cannot be changed in place, so accepting an edit would change nothing. "
    "Use comment_on_document to flag the passages and say what to change, or generate_docx to draft a revised version."
)


def is_pdf(entry: "DocEntry") -> bool:
    """A PDF original: edits cannot be written into it (comments can still be added)."""
    return str(entry.filename or "").lower().endswith(".pdf")
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


def add_documents_to_index(index: DocIndex, documents: list[tuple[str, str]], *, attached: bool = True) -> DocIndex:
    """Put documents first in the index, ahead of retrieval hits.

    `documents` is [(document_id, filename)]. Existing entries keep their slug. ``attached`` marks
    them as the lawyer's attachments; documents carried over from earlier turns are not.
    """
    known = {entry.document_id for entry in index.values()}
    added: DocIndex = {}
    for document_id, filename in documents:
        if document_id in known:
            for entry in index.values():
                if entry.document_id == document_id and attached:
                    entry.attached = True
            continue
        if not document_id:
            continue
        known.add(document_id)
        slug = f"doc-{len(index) + len(added)}"
        added[slug] = DocEntry(doc_id=slug, document_id=document_id, filename=filename or document_id, attached=attached)
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

def annotate_scanned(text: str, pages: list[int] | None) -> str:
    """Mark scanned pages inside the text the model reads, where it cannot overlook the warning.

    Only the copy shown to the model changes; the stored text keeps plain ``[Page N]`` markers, so quotes and
    citations are still checked against the document as it is.
    """
    if not pages:
        return text
    scanned = set(pages)
    return PAGE_MARKER_RE.sub(
        lambda m: (f"[Page {m.group(1)} - SCANNED PAGE: machine-read text, so spacing and letters may be misread; "
                   "do not report them as errors]") if int(m.group(1)) in scanned else m.group(0),
        text)


def source_notice(conn: Any, entry: "DocEntry") -> dict[str, Any] | None:
    """For a PDF: that it is read-only and which pages are scans read by OCR. ``None`` for other files."""
    from app.documents.text_origin import source_info

    info = source_info(conn, entry.document_id)
    if info["format"] != "pdf":
        return None
    notice: dict[str, Any] = {"format": "pdf", "editable": False,
                              "note": "A PDF cannot be edited. Suggestions are recommendations; there is no tracked-changes file."}
    if info["scanned_pages"]:
        notice["scanned_pages"] = info["scanned_pages"]
        notice["scanned_note"] = ("Text on the scanned pages was read by OCR. Spacing, line breaks and look-alike "
                                  "characters in it can be wrong without the printed page being wrong. Never suggest "
                                  "spacing, hyphenation or spelling corrections to it, and do not call them errors.")
    return notice


def read_document(
    doc_id: str,
    doc_index: DocIndex,
    doc_store: DocStore,
    conn: Any = None,
    nonce: str | None = None,
    member_id: str | None = None,
    *,
    section_id: str | None = None,
    pages: str | None = None,
    cursor: int | None = None,
    max_chars: int | None = None,
) -> dict[str, Any]:
    """
    Read a document by its chat-local slug: whole when it fits, otherwise one slice.

    A document longer than ``max_chars`` (``settings.chat_read_max_chars``) is never returned
    whole: the first read gives its outline and opening slice, and later reads ask for a
    ``section_id``, a ``pages`` range ("12-18") or continue from ``cursor``. The full text
    still goes into ``doc_store`` so citations are checked against the whole document.
    """
    from app.chat import doc_nav

    entry = doc_index.get(doc_id)
    if not entry:
        return {"error": f"Document '{doc_id}' not found."}

    text = resolve_document_text(entry, doc_store, conn, member_id)
    budget = max_chars or settings.chat_read_max_chars
    event = {
        "type": "doc_read",
        "filename": entry.filename,
        "document_id": entry.document_id,
        "version_id": entry.version_id,
        "version_number": entry.version_number,
    }
    whole = not (section_id or pages or cursor)
    notice = source_notice(conn, entry)
    scanned = (notice or {}).get("scanned_pages")
    entry.scanned_pages = list(scanned or [])
    if whole and len(text) <= budget:
        shown = annotate_scanned(text, scanned)
        return {"doc_id": doc_id, "filename": entry.filename, "complete": True,
                "text": spotlight(shown, nonce) if nonce else shown, "event": event,
                **({"source": notice} if notice else {})}

    lo, hi, label = 0, len(text), ""
    if section_id:
        sec = doc_nav.section(text, section_id)
        if sec is None:
            return {"error": f"No section '{section_id}' in {doc_id}; call get_outline for section ids."}
        lo, hi, label = sec.start, sec.end, f"{sec.section_id} {sec.title}"
    elif pages:
        span = doc_nav.page_range(text, pages)
        if span is None:
            return {"error": f"Pages '{pages}' not found in {doc_id} ({doc_nav.page_count(text)} pages)."}
        lo, hi, label = span[0], span[1], f"pages {pages}"
    start = cursor if cursor is not None and lo <= cursor < hi else lo
    win = doc_nav.window(text, start, hi, budget)
    out: dict[str, Any] = {
        "doc_id": doc_id,
        "filename": entry.filename,
        "complete": False,
        "total_pages": doc_nav.page_count(text),
        "total_chars": len(text),
        "showing": {"part": label or "document", "pages": f"{win.first_page}–{win.last_page}", "chars": [win.start, win.end]},
        "text": spotlight(annotate_scanned(win.text, scanned), nonce) if nonce else annotate_scanned(win.text, scanned),
    }
    if notice:
        out["source"] = notice
    if win.next_cursor is not None:
        out["next_cursor"] = win.next_cursor
        out["remaining_chars"] = win.remaining_chars
    if whole:
        # First look at a long document: give the map so the next read can be targeted.
        out["outline"] = doc_nav.outline_rows(text)
        out["note"] = ("This document is too long to read at once. Use the outline: read_document with "
                       "section_id or pages for the parts you need, or find_in_document for exact terms.")
    event["part"] = out["showing"]["part"]
    out["event"] = event
    return out


def get_outline(
    doc_id: str,
    doc_index: DocIndex,
    doc_store: DocStore,
    conn: Any = None,
    member_id: str | None = None,
) -> dict[str, Any]:
    """Sections of a document with ids, titles, page ranges and sizes (no body text)."""
    from app.chat import doc_nav

    entry = doc_index.get(doc_id)
    if not entry:
        return {"error": f"Document '{doc_id}' not found."}
    text = resolve_document_text(entry, doc_store, conn, member_id)
    return {
        "doc_id": doc_id,
        "filename": entry.filename,
        "total_pages": doc_nav.page_count(text),
        "total_chars": len(text),
        "fits_in_one_read": len(text) <= settings.chat_read_max_chars,
        "sections": doc_nav.outline_rows(text),
    }


def fetch_documents(
    doc_ids: list[str],
    doc_index: DocIndex,
    doc_store: DocStore,
    conn: Any = None,
    nonce: str | None = None,
    member_id: str | None = None,
) -> dict[str, Any]:
    """Batch-read multiple documents within one shared size budget.

    The budget (twice a single read) is split across the documents; a document larger
    than its share comes back as its outline and opening slice, like ``read_document``.
    """
    results: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    share = max(6000, (2 * settings.chat_read_max_chars) // max(1, len(doc_ids)))
    for doc_id in doc_ids:
        result = read_document(
            doc_id, doc_index, doc_store, conn, nonce, member_id=member_id, max_chars=share,
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
    from app.chat import doc_nav

    sections = doc_nav.outline(text)
    matches: list[dict[str, Any]] = []
    total = 0
    for m in pattern.finditer(text):
        total += 1  # every occurrence is counted, even past max_results
        if len(matches) >= max_results:
            continue
        start = max(0, m.start() - context_chars)
        end = min(len(text), m.end() + context_chars)
        sec = next((s for s in sections if s.start <= m.start() < s.end), None)
        matches.append({
            "match": m.group(),
            "context": text[start:end],
            "page": page_at(text, m.start()),
            "section_id": sec.section_id if sec else None,
            "section": sec.title if sec else None,
            "start": m.start(),
            "end": m.end(),
        })

    return {
        "doc_id": doc_id,
        "filename": entry.filename,
        "query": query,
        "total_matches": total,
        "returned": len(matches),
        "matches": matches,
        "event": {
            "type": "doc_find",
            "filename": entry.filename,
            "document_id": entry.document_id,
            "version_id": entry.version_id,
            "version_number": entry.version_number,
            "query": query,
            "total_matches": total,
        },
    }


def search_firm_records(
    query: str,
    doc_index: DocIndex,
    conn: Any,
    member_id: str | None = None,
    k: int = 8,
    matter_id: str | None = None,
) -> dict[str, Any]:
    """Search the firm corpus (or one matter's records) and merge new documents into the chat-local index."""
    needle = (query or "").strip()
    if not needle:
        return {"error": "Search query is empty.", "results": []}
    if conn is None:
        return {"error": "Search is unavailable.", "results": []}

    k = max(1, min(int(k or 8), 20))
    if matter_id:
        from app.km.passages import scoped_passages

        hits = scoped_passages(conn, needle, [matter_id], member_id, limit=k, per_doc=2)
    else:
        hits, _latency = retrieve(conn, needle, member_id, k=k)
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
    """Return document text, filling the in-turn store and the member cache.

    Every read re-checks that the member may read the document (matter ACL + document
    privacy), so text cached earlier in the conversation is not served after access ends.
    """
    if conn is not None and entry.document_id and not _readable(conn, member_id, entry.document_id):
        doc_store.pop(entry.doc_id, None)
        return "Document could not be read."
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


def _readable(conn: Any, member_id: str | None, document_id: str) -> bool:
    """False when a firm document is outside the member's access. Ids that are not firm
    documents (e.g. generated files) are left to their own owner check."""
    from psycopg.rows import dict_row

    from app.api.acl import ACL_CLAUSE, doc_acl, doc_read

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""SELECT ({doc_read('d')}) AS ok FROM documents d
                LEFT JOIN permissions p ON p.matter_id = d.matter_id WHERE d.document_id = %(id)s""",
            {"id": str(document_id).upper(), "member_id": member_id},
        )
        row = cur.fetchone()
    return True if row is None else bool(row["ok"])


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
        if not rows or all(row["page_number"] is None for row in rows):
            # Scanned reports often have no page per chunk, but their stored text keeps the PDF's
            # form-feed page breaks: use those so citations name the real (PDF) page.
            doc = conn.execute("SELECT body FROM documents WHERE document_id = %s", (document_id,)).fetchone()
            text = str((doc or {}).get("body") or "")
            if "\f" in text:
                return [(i, p.strip()) for i, p in enumerate(text.split("\f"), 1) if p.strip()]

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
