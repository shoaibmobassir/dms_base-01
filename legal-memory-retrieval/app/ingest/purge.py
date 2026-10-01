"""Remove documents (and the upload batches that created them) completely.

Used by tests to clean up after themselves and by scripts/purge_test_uploads.py
to clear test artefacts from a demo database. Not exposed through the API:
documents in normal use are archived, never hard-deleted.
"""
from __future__ import annotations

from app.db.connection import connect


def purge_documents(conn, document_ids: list[str]) -> int:
    """Delete documents with their chunks, blocks and versions. Returns rows removed."""
    ids = [i for i in document_ids if i]
    if not ids:
        return 0
    conn.execute("DELETE FROM chunks WHERE document_id = ANY(%s)", (ids,))
    conn.execute("DELETE FROM document_blocks WHERE document_id = ANY(%s)", (ids,))
    conn.execute("UPDATE documents SET current_version_id = NULL WHERE document_id = ANY(%s)", (ids,))
    conn.execute("UPDATE document_versions SET parent_version_id = NULL WHERE document_id = ANY(%s)", (ids,))
    conn.execute("DELETE FROM document_versions WHERE document_id = ANY(%s)", (ids,))
    conn.execute("UPDATE upload_batch_files SET document_id = NULL, version_id = NULL WHERE document_id = ANY(%s)", (ids,))
    conn.execute("DELETE FROM ingest_items WHERE document_id = ANY(%s)", (ids,))
    return conn.execute("DELETE FROM documents WHERE document_id = ANY(%s)", (ids,)).rowcount


def purge_upload_batches(batch_ids: list[str]) -> int:
    """Delete upload batches and every document they created. Returns documents removed."""
    ids = [b for b in batch_ids if b]
    if not ids:
        return 0
    with connect() as conn, conn.transaction():
        docs = [
            r["document_id"]
            for r in conn.execute(
                "SELECT document_id FROM upload_batch_files WHERE batch_id = ANY(%s) AND document_id IS NOT NULL", (ids,)
            ).fetchall()
        ]
        removed = purge_documents(conn, docs)
        conn.execute("DELETE FROM upload_batches WHERE batch_id = ANY(%s)", (ids,))
    return removed
