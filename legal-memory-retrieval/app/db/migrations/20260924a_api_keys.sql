-- API keys for AUTH_ENABLED=true. Keys are stored as SHA-256 hashes only.
-- Issue keys with: python scripts/issue_keys.py
-- Additive only — safe to re-run.

CREATE TABLE IF NOT EXISTS api_keys (
    member_id  TEXT NOT NULL REFERENCES members (member_id),
    key_hash   TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_member ON api_keys (member_id);
