"""Re-read Word versions whose stored text carries the old "SECTION " heading label (plan 21, E2).

Until 2026-10-04 the DOCX extractor wrote every Heading-style paragraph as "SECTION <text>". That text is what the
reader showed, search indexed and the Assistant quoted, so edits to headings could not be placed in the file. This
re-extracts each version's text from its own stored Word file (the file is not touched), re-parses its blocks with the
file's real headings, and rebuilds the current version's search chunks and embeddings. No new version is created.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.db.connection import connect

_DOCX = "%wordprocessingml%"


@dataclass
class DocPlan:
    document_id: str
    title: str
    versions: list[dict] = field(default_factory=list)  # {version_id, version_number, before, after, extracted}


def affected_documents(conn, document_ids: list[str] | None = None) -> list[dict]:
    """Word documents with at least one version whose text has a line starting "SECTION "."""
    return [dict(r) for r in conn.execute(
        f"""
        SELECT DISTINCT d.document_id, d.title
        FROM documents d JOIN document_versions v ON v.document_id = d.document_id
        WHERE (v.mime_type ILIKE %(docx)s OR d.mime_type ILIKE %(docx)s OR v.storage_uri ILIKE '%%.docx')
          AND v.body ~ '(^|\\n)SECTION '
          {"AND d.document_id = ANY(%(ids)s)" if document_ids else ""}
        ORDER BY d.document_id
        """,
        {"docx": _DOCX, "ids": document_ids},
    ).fetchall()]


def plan(conn, doc: dict) -> DocPlan:
    """What re-reading each version of ``doc`` would change (nothing is written)."""
    from app.documents import docx_review
    from app.ingest.extractors.docx import DocxExtractor
    from app.storage.object_store import get_object_store

    out = DocPlan(doc["document_id"], doc["title"])
    store = get_object_store()
    for v in conn.execute(
        "SELECT version_id, version_number, body, storage_uri FROM document_versions WHERE document_id = %s ORDER BY version_number",
        (doc["document_id"],),
    ):
        uri = v["storage_uri"]
        if not uri or not str(uri).lower().endswith(".docx"):
            continue
        try:
            data = store.get(uri)
        except Exception as exc:  # noqa: BLE001 — a missing file leaves that version as it is
            out.versions.append({"version_id": v["version_id"], "version_number": v["version_number"], "error": str(exc)})
            continue
        if docx_review.has_revisions(data):
            data = docx_review.accept_everything(data)  # the stored text is always the accepted reading
        extracted = DocxExtractor().extract_bytes(data)
        if extracted.text != (v["body"] or ""):
            out.versions.append({"version_id": v["version_id"], "version_number": v["version_number"],
                                 "before": v["body"] or "", "after": extracted.text, "extracted": extracted})
    return out


def apply(conn, p: DocPlan) -> dict:
    """Write the re-read text of each planned version, re-parse its blocks, and rebuild the current version's chunks."""
    from app.documents import content_sha256, reindex_current_version
    from app.documents.canonical import parse_canonical_blocks, save_canonical_blocks
    from app.embeddings.pending import embed_pending_chunks

    current = conn.execute("SELECT current_version_id FROM documents WHERE document_id = %s", (p.document_id,)).fetchone()
    written = 0
    for v in p.versions:
        if "error" in v:
            continue
        ex = v["extracted"]
        conn.execute("UPDATE document_versions SET body = %s, content_sha256 = %s WHERE version_id = %s",
                     (v["after"], content_sha256(v["after"]), v["version_id"]))
        if v["version_id"] == current["current_version_id"]:
            conn.execute("UPDATE documents SET body = %s WHERE document_id = %s", (v["after"], p.document_id))
        conn.commit()
        blocks = parse_canonical_blocks(v["after"], p.document_id, v["version_id"], page_spans=ex.pages, headings=ex.headings)
        save_canonical_blocks(blocks)
        conn.execute("DELETE FROM document_blocks WHERE version_id = %s AND sequence > %s", (v["version_id"], len(blocks)))
        conn.commit()
        written += 1
    chunks = reindex_current_version(p.document_id) if written else {"chunk_count": 0}
    embedded = embed_pending_chunks([p.document_id]) if written else 0
    return {"versions": written, "chunks": chunks["chunk_count"], "embedded": embedded}
