-- Files the assistant generates (DOCX/XLSX). Previously they were served by id
-- prefix from disk with no owner, so anyone with the id could download them.
-- Download now requires the caller to be the owner. Safe to re-run.
CREATE TABLE IF NOT EXISTS generated_artifacts (
    artifact_id     TEXT PRIMARY KEY,
    owner_member_id TEXT REFERENCES members (member_id) ON DELETE SET NULL,
    filename        TEXT NOT NULL,
    storage_path    TEXT NOT NULL,
    mime_type       TEXT NOT NULL,
    size_bytes      BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_generated_owner ON generated_artifacts (owner_member_id, created_at DESC);
