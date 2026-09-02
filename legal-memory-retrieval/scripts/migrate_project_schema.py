#!/usr/bin/env python3
"""Apply additive project-workspace schema (folders, versions, activity)."""
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
CREATE TABLE IF NOT EXISTS document_versions (
    version_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    version_number INT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    author_name TEXT,
    source TEXT NOT NULL DEFAULT 'upload',
    version_status TEXT NOT NULL DEFAULT 'draft',
    version_label TEXT,
    file_size_bytes INT,
    page_count INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_docver_document ON document_versions (document_id, version_number DESC);

ALTER TABLE documents ADD COLUMN IF NOT EXISTS current_version_id TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS folder_id TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

CREATE TABLE IF NOT EXISTS project_folders (
    folder_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects (project_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    parent_folder_id TEXT REFERENCES project_folders (folder_id) ON DELETE CASCADE,
    created_by TEXT REFERENCES members (member_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_projfolder_project ON project_folders (project_id);
CREATE INDEX IF NOT EXISTS idx_projfolder_parent ON project_folders (parent_folder_id);

CREATE TABLE IF NOT EXISTS project_activity (
    activity_id BIGSERIAL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects (project_id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    actor_id TEXT REFERENCES members (member_id),
    target_id TEXT,
    target_title TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_projact_project ON project_activity (project_id, created_at DESC);

ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS version_status TEXT NOT NULL DEFAULT 'draft';
ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS version_label TEXT;
"""


def main() -> None:
    with connect() as conn:
        for stmt in MIGRATION.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()
    print("Project workspace schema migration applied.")


if __name__ == "__main__":
    main()
