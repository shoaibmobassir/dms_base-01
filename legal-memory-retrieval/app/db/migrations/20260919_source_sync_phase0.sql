-- Universal document sync / source connectors (Phase 0)
-- Additive only — safe to re-run.

CREATE TABLE IF NOT EXISTS source_connections (
    connection_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    created_by_member_id TEXT REFERENCES members (member_id),
    provider TEXT NOT NULL,
    provider_account_id TEXT,
    display_name TEXT,
    scopes TEXT[] NOT NULL DEFAULT '{}',
    encrypted_access_token TEXT,
    encrypted_refresh_token TEXT,
    token_expires_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'needs_reauth', 'paused', 'disconnected')),
    config JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_source_conn_org
    ON source_connections (organization_id, status);
CREATE INDEX IF NOT EXISTS idx_source_conn_provider
    ON source_connections (provider);

CREATE TABLE IF NOT EXISTS source_sync_state (
    connection_id TEXT NOT NULL REFERENCES source_connections (connection_id) ON DELETE CASCADE,
    scope_key TEXT NOT NULL DEFAULT 'default',
    cursor TEXT,
    cursor_kind TEXT,
    last_sync_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    sync_status TEXT NOT NULL DEFAULT 'idle'
        CHECK (sync_status IN ('idle', 'running', 'error', 'backoff')),
    error_code TEXT,
    error_message TEXT,
    consecutive_failures INT NOT NULL DEFAULT 0,
    PRIMARY KEY (connection_id, scope_key)
);

CREATE TABLE IF NOT EXISTS source_files (
    source_file_id TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL REFERENCES source_connections (connection_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    provider_file_id TEXT NOT NULL,
    name TEXT,
    mime_type TEXT,
    size_bytes BIGINT,
    parent_provider_file_id TEXT,
    path TEXT,
    web_url TEXT,
    created_at_remote TIMESTAMPTZ,
    modified_at_remote TIMESTAMPTZ,
    etag TEXT,
    content_hash TEXT,
    is_folder BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    document_id TEXT REFERENCES documents (document_id) ON DELETE SET NULL,
    matter_id TEXT REFERENCES matters (matter_id),
    status TEXT NOT NULL DEFAULT 'discovered'
        CHECK (status IN (
            'discovered', 'downloading', 'indexed', 'failed',
            'ignored', 'deleted', 'skipped_unchanged'
        )),
    error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (connection_id, provider_file_id)
);

CREATE INDEX IF NOT EXISTS idx_source_files_connection
    ON source_files (connection_id, status);
CREATE INDEX IF NOT EXISTS idx_source_files_matter
    ON source_files (matter_id) WHERE matter_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_source_files_document
    ON source_files (document_id) WHERE document_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS source_file_permissions (
    source_file_id TEXT NOT NULL REFERENCES source_files (source_file_id) ON DELETE CASCADE,
    principal_type TEXT NOT NULL
        CHECK (principal_type IN ('user', 'group', 'anyone', 'domain')),
    principal_id TEXT NOT NULL,
    permission TEXT NOT NULL DEFAULT 'read',
    mapped_member_id TEXT REFERENCES members (member_id),
    PRIMARY KEY (source_file_id, principal_type, principal_id)
);

CREATE TABLE IF NOT EXISTS identity_links (
    link_id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL REFERENCES members (member_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    provider_user_id TEXT,
    email TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_user_id)
);

CREATE INDEX IF NOT EXISTS idx_identity_links_member
    ON identity_links (member_id);

ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_connection_id TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_file_id TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS provider TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS provider_file_id TEXT;

CREATE INDEX IF NOT EXISTS idx_docs_source_file
    ON documents (source_file_id) WHERE source_file_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_docs_provider_file
    ON documents (provider, provider_file_id)
    WHERE provider_file_id IS NOT NULL;
