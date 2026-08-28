#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from pgvector import Vector
from pgvector.psycopg import register_vector

from app.db.connection import connect
from app.embeddings.minilm import MiniLMEmbedder

BATCH = 256
HNSW_SQL = """
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
ON chunks USING hnsw (embedding vector_cosine_ops);
"""


def main() -> None:
    embedder = MiniLMEmbedder()
    total = 0
    with connect() as conn:
        register_vector(conn)
        while True:
            rows = conn.execute(
                """
                SELECT chunk_id, text FROM chunks
                WHERE embedding IS NULL
                ORDER BY chunk_id
                LIMIT %s
                """,
                (BATCH,),
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
            print(f"embedded {total}", flush=True)
        conn.execute(HNSW_SQL)
        conn.commit()
        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE embedding IS NULL"
        ).fetchone()["n"]
        indexed = conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE embedding IS NOT NULL"
        ).fetchone()["n"]
    print({"embedded_this_run": total, "with_embedding": indexed, "still_null": remaining})


if __name__ == "__main__":
    main()
