#!/usr/bin/env python3
"""Apply upload_batches + object-storage-related schema (FirmOS Phase 3–4)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from app.db.connection import connect

SQL = """
ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS mime_type TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS folder_path TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_uri TEXT;

CREATE TABLE IF NOT EXISTS upload_batches (
    batch_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'harbour',
    matter_id TEXT NOT NULL REFERENCES matters (matter_id),
    client_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    total_files INT NOT NULL DEFAULT 0,
    processed_files INT NOT NULL DEFAULT 0,
    failed_files INT NOT NULL DEFAULT 0,
    ingest_job_id TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error_summary TEXT,
    manifest JSONB NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_upload_batches_matter ON upload_batches (matter_id);
CREATE INDEX IF NOT EXISTS idx_upload_batches_status ON upload_batches (status);

CREATE TABLE IF NOT EXISTS upload_batch_files (
    item_id BIGSERIAL PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES upload_batches (batch_id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    size_bytes INT NOT NULL DEFAULT 0,
    mime_type TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    provisional_document_id TEXT,
    document_id TEXT,
    version_id TEXT,
    error TEXT,
    processed_at TIMESTAMPTZ,
    UNIQUE (batch_id, relative_path)
);

CREATE INDEX IF NOT EXISTS idx_upload_files_batch ON upload_batch_files (batch_id);
CREATE INDEX IF NOT EXISTS idx_upload_files_status ON upload_batch_files (status);
"""


def main() -> int:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(SQL)
        conn.commit()
    print("migrate_upload_batches: done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
