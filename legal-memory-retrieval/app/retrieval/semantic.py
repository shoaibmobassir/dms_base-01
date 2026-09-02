from __future__ import annotations

from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from app.embeddings.minilm import MiniLMEmbedder

_embedder: MiniLMEmbedder | None = None


def _model() -> MiniLMEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = MiniLMEmbedder()
    return _embedder


def semantic_search(conn, query: str, member_id: str | None, limit: int = 50) -> list[dict]:
    register_vector(conn)
    qvec = _model().encode([query])[0]
    sql = """
        SELECT d.document_id, d.matter_id, d.matter_code, d.title, d.document_type,
               d.author_name, d.doc_date,
               m.client_name, m.court, m.practice_area,
               c.chunk_id, c.chunk_index, c.text,
               1.0 - (c.embedding <=> %(qvec)s) AS score,
               'vector' AS channel
        FROM chunks c
        JOIN documents d ON d.document_id = c.document_id
        JOIN matters m ON m.matter_id = d.matter_id
        JOIN permissions p ON p.matter_id = c.matter_id
        WHERE c.embedding IS NOT NULL
        AND (
            (%(member_id)s::text IS NULL)
            OR p.restricted = FALSE
            OR %(member_id)s::text = ANY (p.allowed_members)
        )
        ORDER BY c.embedding <=> %(qvec)s
        LIMIT %(limit)s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"qvec": Vector(qvec), "member_id": member_id, "limit": limit})
        return list(cur.fetchall())
