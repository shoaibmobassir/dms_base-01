"""Embed chunks that have no vector yet, for specific documents.

Upload ingest writes chunks (keyword-searchable) but not vectors; without this,
uploaded documents were invisible to vector retrieval until someone ran
``scripts/embed.py`` by hand. The chunk index is MiniLM 384-d, so this always uses
MiniLM regardless of EMBEDDING_PROVIDER (which is for experiments only).
"""
from __future__ import annotations

import logging
import threading

from pgvector import Vector
from pgvector.psycopg import register_vector

from app.db.connection import connect

log = logging.getLogger(__name__)

_BATCH = 128
_embedder = None
_lock = threading.Lock()


def _get_embedder():
    global _embedder
    with _lock:
        if _embedder is None:
            from app.embeddings.minilm import MiniLMEmbedder

            _embedder = MiniLMEmbedder()
        return _embedder


def embed_pending_chunks(document_ids: list[str]) -> int:
    """Embed every un-embedded chunk of ``document_ids``. Returns chunks embedded."""
    if not document_ids:
        return 0
    embedder = _get_embedder()
    total = 0
    with connect() as conn:
        register_vector(conn)
        while True:
            rows = conn.execute(
                """
                SELECT chunk_id, text FROM chunks
                WHERE embedding IS NULL AND document_id = ANY(%s)
                ORDER BY chunk_id LIMIT %s
                """,
                (document_ids, _BATCH),
            ).fetchall()
            if not rows:
                break
            vectors = embedder.encode([r["text"] for r in rows])
            with conn.cursor() as cur:
                for row, vec in zip(rows, vectors):
                    cur.execute(
                        "UPDATE chunks SET embedding = %s WHERE chunk_id = %s",
                        (Vector(vec), row["chunk_id"]),
                    )
            conn.commit()
            total += len(rows)
    log.info("embedded %d chunks for %d documents", total, len(document_ids))
    return total
