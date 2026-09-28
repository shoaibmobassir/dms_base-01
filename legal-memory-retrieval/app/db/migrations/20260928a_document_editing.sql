-- In-browser document editing and file-based versions (plan 16, E1–E2).
--   * versions record WHO created them (member id from the session), and how
--   * one edit lock per document (web editor, Word add-in, later Collabora/WOPI)
--   * per-member autosaved drafts
--   * an append-only document activity log (viewed, edited, uploaded, locked, …)
-- Safe to re-run.

ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS created_by_member_id TEXT REFERENCES members (member_id);
ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS origin TEXT;  -- upload | editor | word | assistant | sync

CREATE TABLE IF NOT EXISTS document_locks (
    document_id TEXT PRIMARY KEY REFERENCES documents (document_id) ON DELETE CASCADE,
    member_id   TEXT NOT NULL REFERENCES members (member_id) ON DELETE CASCADE,
    source      TEXT NOT NULL DEFAULT 'web' CHECK (source IN ('web', 'word', 'collabora')),
    lock_token  TEXT NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS document_drafts (
    document_id     TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    member_id       TEXT NOT NULL REFERENCES members (member_id) ON DELETE CASCADE,
    base_version_id TEXT NOT NULL,
    ops             JSONB NOT NULL DEFAULT '[]',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, member_id)
);

CREATE TABLE IF NOT EXISTS document_events (
    seq         BIGSERIAL PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    version_id  TEXT,
    member_id   TEXT,
    action      TEXT NOT NULL,
    detail      JSONB NOT NULL DEFAULT '{}',
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_document_events_doc ON document_events (document_id, seq DESC);
