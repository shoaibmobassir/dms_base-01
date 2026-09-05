#!/usr/bin/env python3
"""Apply Document Intelligence + Version Control schema (additive).

Idempotent. Safe to re-run.
See docs/plan/13_document_intelligence_version_control.md Phase 0.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from app.db.connection import connect

MIGRATION_FILE = ROOT / "app" / "db" / "migrations" / "20260905_doc_intelligence_version_control.sql"

EXTRA = """
-- Version lineage + object storage pointer + human change note
ALTER TABLE document_versions
    ADD COLUMN IF NOT EXISTS parent_version_id TEXT REFERENCES document_versions (version_id);
ALTER TABLE document_versions
    ADD COLUMN IF NOT EXISTS storage_uri TEXT;
ALTER TABLE document_versions
    ADD COLUMN IF NOT EXISTS change_summary TEXT;

CREATE INDEX IF NOT EXISTS idx_docver_parent
    ON document_versions (parent_version_id);

-- Materialized folder path for retrieval context envelopes
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS folder_path TEXT;

-- Section / document intelligence cache (per version)
CREATE TABLE IF NOT EXISTS document_intelligence (
    version_id TEXT PRIMARY KEY REFERENCES document_versions (version_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    executive_summary TEXT,
    section_summaries JSONB NOT NULL DEFAULT '{}',
    entities JSONB NOT NULL DEFAULT '[]',
    clauses TEXT[] NOT NULL DEFAULT '{}',
    summary_version TEXT NOT NULL DEFAULT 'summary_v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_docintel_doc ON document_intelligence (document_id);
"""


def main() -> int:
    sql = MIGRATION_FILE.read_text(encoding="utf-8")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(EXTRA)
        conn.commit()

    required = [
        "document_blocks",
        "version_diffs",
        "review_jobs",
        "findings",
        "evidence_anchors",
        "annotations",
        "document_intelligence",
    ]
    with connect() as conn:
        with conn.cursor() as cur:
            for t in required:
                cur.execute("SELECT to_regclass(%s) AS r", (t,))
                row = cur.fetchone()
                name = row["r"] if isinstance(row, dict) else row[0]
                if not name:
                    print(f"MISSING: {t}", file=sys.stderr)
                    return 1
                print(f"OK {t}")
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'document_versions'
                  AND column_name IN ('parent_version_id', 'storage_uri', 'change_summary')
                ORDER BY column_name
                """
            )
            cols = [r["column_name"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
            print("version cols:", ", ".join(cols))
    print("migrate_doc_intelligence: done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
