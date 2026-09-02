"""Batch writer — insert documents + chunks into Postgres.

Reasoning:
  Uses executemany in batches of 500 (matching existing scripts/ingest.py L233).
  Idempotent via content_sha256: if a doc with the same (matter_id, sha) exists,
  skip insertion. No inline embedding — embed.py handles that separately.
"""
from __future__ import annotations

import psycopg

from app.db.chunking import chunk_text
from app.ingest.models import DocumentRecord


def write_document(conn: psycopg.Connection, doc: DocumentRecord) -> tuple[int, bool]:
    """Insert one document + its chunks. Returns (chunk_count, was_skipped).

    Skips if content_sha256 already exists for this matter_id.
    """
    # ── Idempotency check ────────────────────────────────────────────
    existing = conn.execute(
        """
        SELECT document_id FROM documents
        WHERE matter_id = %s AND content_sha256 = %s
        """,
        (doc.matter_id, doc.content_sha256),
    ).fetchone()
    if existing:
        return 0, True  # skipped

    # ── Insert document ──────────────────────────────────────────────
    conn.execute(
        """
        INSERT INTO documents (
            document_id, matter_id, matter_code, client_id, title,
            document_type, author_name, doc_date, body,
            source_uri, content_sha256, mime_type, ingested_at,
            status, version
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(),
            'Active', '1'
        )
        ON CONFLICT (document_id) DO NOTHING
        """,
        (
            doc.document_id, doc.matter_id, doc.matter_code,
            doc.client_id, doc.title, doc.document_type,
            doc.author_name, doc.doc_date, doc.body,
            doc.source_uri, doc.content_sha256, doc.mime_type,
        ),
    )

    # ── Chunk + insert chunks ────────────────────────────────────────
    chunks = chunk_text(doc.body)
    if not chunks:
        conn.commit()
        return 0, False

    batch = []
    for idx, piece in enumerate(chunks):
        chunk_id = f"{doc.document_id}-C{idx:03d}"
        batch.append((chunk_id, doc.document_id, doc.matter_id, idx, piece, piece))

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO chunks (chunk_id, document_id, matter_id, chunk_index, text, tsv)
            VALUES (%s, %s, %s, %s, %s, to_tsvector('english', %s))
            ON CONFLICT (document_id, chunk_index) DO UPDATE SET text = EXCLUDED.text, tsv = EXCLUDED.tsv
            """,
            batch,
        )
    conn.commit()
    return len(chunks), False
