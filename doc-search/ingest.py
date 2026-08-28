#!/usr/bin/env python3
"""Ingest all PDFs from DOCS_DIR into Postgres docs_* tables."""
from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from pypdf import PdfReader

from chunking import chunk_text
from config import settings
from embedder import MiniLMEmbedder


def file_id(path: Path) -> str:
    return hashlib.sha1(path.name.encode()).hexdigest()[:16]


def chunk_id(fid: str, idx: int) -> str:
    return f"{fid}_{idx:05d}"


def run_schema(conn: psycopg.Connection) -> None:
    schema = (Path(__file__).parent / "schema.sql").read_text()
    conn.execute(schema)
    conn.commit()
    print("Schema applied.")


def extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    """Returns list of (1-indexed page_number, text)."""
    reader = PdfReader(str(pdf_path))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append((i, text))
    return pages


def ingest_file(conn: psycopg.Connection, pdf_path: Path, embedder: MiniLMEmbedder) -> int:
    fid = file_id(pdf_path)
    filename = pdf_path.name

    pages = extract_pages(pdf_path)
    if not pages:
        print(f"  SKIP (no text): {filename}")
        return 0

    chunks: list[dict] = []
    idx = 0
    for page_num, page_text in pages:
        for piece in chunk_text(page_text, max_chars=900, overlap=90):
            chunks.append({
                "chunk_id": chunk_id(fid, idx),
                "file_id": fid,
                "filename": filename,
                "page_number": page_num,
                "chunk_index": idx,
                "text": piece,
            })
            idx += 1

    if not chunks:
        print(f"  SKIP (no chunks): {filename}")
        return 0

    conn.execute(
        """
        INSERT INTO docs_files (file_id, filename, filepath, page_count)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (filename) DO UPDATE
            SET filepath = EXCLUDED.filepath,
                page_count = EXCLUDED.page_count
        """,
        (fid, filename, str(pdf_path), max(p for p, _ in pages)),
    )

    with conn.pipeline():
        for c in chunks:
            conn.execute(
                """
                INSERT INTO docs_chunks (chunk_id, file_id, filename, page_number, chunk_index, text)
                VALUES (%(chunk_id)s, %(file_id)s, %(filename)s, %(page_number)s, %(chunk_index)s, %(text)s)
                ON CONFLICT (file_id, chunk_index) DO UPDATE
                    SET text = EXCLUDED.text,
                        page_number = EXCLUDED.page_number
                """,
                c,
            )
    conn.commit()

    texts = [c["text"] for c in chunks]
    print(f"  Embedding {len(texts)} chunks ...", end=" ", flush=True)
    t0 = time.perf_counter()
    batch_size = 256
    all_vecs: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        all_vecs.extend(embedder.encode(texts[i : i + batch_size]))
    print(f"{time.perf_counter()-t0:.1f}s")

    with conn.pipeline():
        for c, vec in zip(chunks, all_vecs):
            conn.execute(
                "UPDATE docs_chunks SET embedding = %s WHERE chunk_id = %s",
                (vec, c["chunk_id"]),
            )
    conn.commit()

    return len(chunks)


def main() -> None:
    docs_dir = Path(settings.docs_dir)
    pdfs = sorted(docs_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {docs_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(pdfs)} PDFs in {docs_dir}")
    print("Loading embedder model ...")
    embedder = MiniLMEmbedder()
    print("Model loaded.\n")

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        run_schema(conn)
        total = 0
        for pdf in pdfs:
            print(f"[{pdf.name}]")
            n = ingest_file(conn, pdf, embedder)
            print(f"  -> {n} chunks stored")
            total += n

    print(f"\nDone. {total} chunks total across {len(pdfs)} files.")


if __name__ == "__main__":
    main()
