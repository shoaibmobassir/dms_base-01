#!/usr/bin/env python3
"""Add version-scoped hierarchical chunk columns (FirmOS tasks 6+8)."""
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
-- Version-scoped hierarchical chunk metadata
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS version_id TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS folder_path TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS section_id TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS section_title TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS page_number INT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS parent_chunk_id TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS block_ids TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS is_parent BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_chunks_version ON chunks (version_id);
CREATE INDEX IF NOT EXISTS idx_chunks_version_section ON chunks (version_id, section_id);
CREATE INDEX IF NOT EXISTS idx_chunks_parent ON chunks (parent_chunk_id);

-- Allow multiple versions per document: drop legacy unique if present
ALTER TABLE chunks DROP CONSTRAINT IF EXISTS chunks_document_id_chunk_index_key;

-- Legacy rows (no version): keep unique on (document_id, chunk_index)
CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_legacy_doc_idx
    ON chunks (document_id, chunk_index) WHERE version_id IS NULL;

-- Version-scoped rows
CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_version_idx
    ON chunks (version_id, chunk_index) WHERE version_id IS NOT NULL;
"""


def main() -> int:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(SQL)
        conn.commit()
    print("migrate_version_chunks: done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
