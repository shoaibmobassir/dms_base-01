#!/usr/bin/env python3
"""Apply additive ingest-pipeline schema extensions to an existing database."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from app.db.connection import connect

MIGRATION = """
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_uri TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_sha256 TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS mime_type TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS ingest_job_id TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMPTZ;
CREATE UNIQUE INDEX IF NOT EXISTS idx_docs_source_sha
    ON documents (matter_id, content_sha256) WHERE content_sha256 IS NOT NULL;

CREATE TABLE IF NOT EXISTS ingest_jobs (
    job_id TEXT PRIMARY KEY,
    source_root TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    total_items INT NOT NULL DEFAULT 0,
    indexed_items INT NOT NULL DEFAULT 0,
    failed_items INT NOT NULL DEFAULT 0,
    skipped_items INT NOT NULL DEFAULT 0,
    workers INT NOT NULL DEFAULT 1,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS ingest_items (
    item_id BIGSERIAL PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES ingest_jobs (job_id),
    source_uri TEXT NOT NULL,
    content_sha256 TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    document_id TEXT,
    error TEXT,
    processed_at TIMESTAMPTZ,
    UNIQUE (job_id, source_uri)
);
"""


def main() -> None:
    with connect() as conn:
        for stmt in MIGRATION.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()
    print("Ingest schema migration applied.")


if __name__ == "__main__":
    main()
