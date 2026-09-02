#!/usr/bin/env python3
"""Ingest all PDFs from DOCS_DIR into Postgres docs_* tables.

Reasoning:
  Original ingest stored only filename/page/text. Now we also extract and store
  DMS metadata (matter_id, document_type, forum, case_number, client, tags) so
  that the API can return DMS-portal-style responses with tags attached.
"""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from pypdf import PdfReader

from chunking import chunk_text
from config import settings
from embedder import MiniLMEmbedder
from metadata_extractor import extract_with_overrides


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

    # ── Extract metadata ─────────────────────────────────────────────────
    full_text = "\n\n".join(text for _, text in pages)
    meta = extract_with_overrides(filename, full_text)
    print(f"  Metadata: type={meta['document_type']}, forum={meta['forum']}, "
          f"case={meta['case_number']}, matter={meta['matter_id']}, "
          f"client={meta['client_name']}, tags={meta['tags']}")

    # ── Chunk text ────────────────────────────────────────────────────────
    chunks: list[dict] = []
    idx = 0
    for page_num, page_text in pages:
        for piece in chunk_text(page_text, max_chars=1200, overlap=150):
            chunks.append({
                "chunk_id": chunk_id(fid, idx),
                "file_id": fid,
                "filename": filename,
                "page_number": page_num,
                "chunk_index": idx,
                "text": piece,
                "matter_id": meta["matter_id"],
                "document_type": meta["document_type"],
                "tags": meta["tags"],
            })
            idx += 1

    if not chunks:
        print(f"  SKIP (no chunks): {filename}")
        return 0

    # ── Upsert file record ────────────────────────────────────────────────
    conn.execute(
        """
        INSERT INTO docs_files (file_id, filename, filepath, page_count,
                                matter_id, client_name, document_type, forum,
                                case_number, tags)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (filename) DO UPDATE
            SET filepath = EXCLUDED.filepath,
                page_count = EXCLUDED.page_count,
                matter_id = EXCLUDED.matter_id,
                client_name = EXCLUDED.client_name,
                document_type = EXCLUDED.document_type,
                forum = EXCLUDED.forum,
                case_number = EXCLUDED.case_number,
                tags = EXCLUDED.tags
        """,
        (
            fid, filename, str(pdf_path), max(p for p, _ in pages),
            meta["matter_id"], meta["client_name"], meta["document_type"],
            meta["forum"], meta["case_number"], meta["tags"],
        ),
    )

    # ── Upsert chunks ─────────────────────────────────────────────────────
    with conn.pipeline():
        for c in chunks:
            conn.execute(
                """
                INSERT INTO docs_chunks (chunk_id, file_id, filename, page_number,
                                         chunk_index, text, matter_id, document_type, tags)
                VALUES (%(chunk_id)s, %(file_id)s, %(filename)s, %(page_number)s,
                        %(chunk_index)s, %(text)s, %(matter_id)s, %(document_type)s, %(tags)s)
                ON CONFLICT (file_id, chunk_index) DO UPDATE
                    SET text = EXCLUDED.text,
                        page_number = EXCLUDED.page_number,
                        matter_id = EXCLUDED.matter_id,
                        document_type = EXCLUDED.document_type,
                        tags = EXCLUDED.tags
                """,
                c,
            )
    conn.commit()

    # ── Embed chunks ──────────────────────────────────────────────────────
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
