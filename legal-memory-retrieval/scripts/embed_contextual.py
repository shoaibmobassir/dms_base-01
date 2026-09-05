#!/usr/bin/env python3
"""Populate chunks.embedding_ctx with contextual MiniLM vectors (C5.5).

Does not overwrite chunks.embedding (production raw-chunk lane).

Usage:
  .venv/bin/python scripts/embed_contextual.py --semantic-themes
  .venv/bin/python scripts/embed_contextual.py --all
  .venv/bin/python scripts/embed_contextual.py --themes sebi_insider,jv
"""
from __future__ import annotations

import argparse
import json
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
from app.query.understand import understand
from app.retrieval.contextual_embed import CTX_EMBED_VERSION, format_contextual_chunk
from app.retrieval.theme_scoped import resolve_theme_keys

BATCH = 128

ENSURE_COL = """
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding_ctx vector(384);
"""

# Optional HNSW — skip if build is slow; ablation can order by <=> without index.
HNSW_SQL = """
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_ctx_hnsw
ON chunks USING hnsw (embedding_ctx vector_cosine_ops);
"""


def semantic_theme_keys() -> list[str]:
    themes: set[str] = set()
    for line in (ROOT / "evals" / "dataset.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        q = json.loads(line)
        if q.get("type") != "semantic":
            continue
        parsed = understand(q["question"])
        intent = resolve_theme_keys(
            q["question"],
            search_text=parsed.search_text,
            practice_area=parsed.practice_area,
            max_themes=1,
        )
        themes.update(intent.theme_keys)
    return sorted(themes)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--all", action="store_true", help="Embed every chunk missing embedding_ctx")
    p.add_argument("--semantic-themes", action="store_true", help="Only chunks in C5 semantic themes")
    p.add_argument("--themes", default="", help="Comma-separated theme_key list")
    p.add_argument("--hnsw", action="store_true", help="Build HNSW on embedding_ctx")
    p.add_argument("--batch", type=int, default=BATCH)
    args = p.parse_args()

    theme_filter: list[str] | None = None
    if args.themes.strip():
        theme_filter = [t.strip() for t in args.themes.split(",") if t.strip()]
    elif args.semantic_themes:
        theme_filter = semantic_theme_keys()
        print(f"semantic themes: {theme_filter}", flush=True)
    elif not args.all:
        p.error("Specify --semantic-themes, --themes, or --all")

    embedder = MiniLMEmbedder()
    total = 0
    with connect() as conn:
        register_vector(conn)
        conn.execute(ENSURE_COL)
        conn.commit()

        while True:
            if theme_filter:
                rows = conn.execute(
                    """
                    SELECT c.chunk_id, c.text, c.section_title, c.folder_path,
                           d.title, d.document_type, d.folder_path AS doc_folder_path
                    FROM chunks c
                    JOIN documents d ON d.document_id = c.document_id
                    JOIN matters m ON m.matter_id = d.matter_id
                    WHERE c.embedding_ctx IS NULL
                      AND m.theme_key = ANY(%s)
                    ORDER BY c.chunk_id
                    LIMIT %s
                    """,
                    (theme_filter, args.batch),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT c.chunk_id, c.text, c.section_title, c.folder_path,
                           d.title, d.document_type, d.folder_path AS doc_folder_path
                    FROM chunks c
                    JOIN documents d ON d.document_id = c.document_id
                    WHERE c.embedding_ctx IS NULL
                    ORDER BY c.chunk_id
                    LIMIT %s
                    """,
                    (args.batch,),
                ).fetchall()
            if not rows:
                break

            texts = [
                format_contextual_chunk(
                    title=r["title"],
                    document_type=r["document_type"],
                    section_title=r.get("section_title"),
                    folder_path=r.get("folder_path") or r.get("doc_folder_path"),
                    chunk_text=r["text"],
                )
                for r in rows
            ]
            vectors = embedder.encode(texts)
            with conn.cursor() as cur:
                for row, vec in zip(rows, vectors):
                    cur.execute(
                        "UPDATE chunks SET embedding_ctx = %s WHERE chunk_id = %s",
                        (Vector(vec), row["chunk_id"]),
                    )
            conn.commit()
            total += len(rows)
            print(f"embedded_ctx {total} ({CTX_EMBED_VERSION})", flush=True)

        if args.hnsw:
            print("building HNSW on embedding_ctx…", flush=True)
            conn.execute(HNSW_SQL)
            conn.commit()

        if theme_filter:
            stats = conn.execute(
                """
                SELECT COUNT(*) FILTER (WHERE c.embedding_ctx IS NOT NULL) AS with_ctx,
                       COUNT(*) AS n
                FROM chunks c
                JOIN documents d ON d.document_id = c.document_id
                JOIN matters m ON m.matter_id = d.matter_id
                WHERE m.theme_key = ANY(%s)
                """,
                (theme_filter,),
            ).fetchone()
        else:
            stats = conn.execute(
                """
                SELECT COUNT(*) FILTER (WHERE embedding_ctx IS NOT NULL) AS with_ctx,
                       COUNT(*) AS n
                FROM chunks
                """
            ).fetchone()

    print({
        "version": CTX_EMBED_VERSION,
        "embedded_this_run": total,
        "theme_scope_with_ctx": int(stats["with_ctx"]),
        "theme_scope_chunks": int(stats["n"]),
    })


if __name__ == "__main__":
    main()
