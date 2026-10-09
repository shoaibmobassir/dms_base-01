-- Playbooks (plan 22, W5): reusable ways of doing a job.
--   kind instructions  Markdown the Assistant reads and follows (subject to system rules), with reference documents
--   kind columns       a set of review questions that starts a tabular review
-- Three sources: shipped with the product (read-only, synced from app/playbooks/catalog by content hash), published by
-- the firm (km.publish holders edit), personal (owner + shares). A shipped or firm playbook is duplicated to edit.
-- Safe to re-run.

CREATE TABLE IF NOT EXISTS playbooks (
    playbook_id     TEXT PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('instructions', 'columns')),
    source          TEXT NOT NULL CHECK (source IN ('shipped', 'firm', 'personal')),
    title           TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    summary         TEXT,
    practice_area   TEXT,
    jurisdiction    TEXT,
    language        TEXT,
    body_md         TEXT NOT NULL DEFAULT '' CHECK (char_length(body_md) <= 60000),
    columns         JSONB NOT NULL DEFAULT '[]'::jsonb,
    owner_member_id TEXT REFERENCES members (member_id),
    origin_playbook_id TEXT,
    content_sha256  TEXT,
    version         INTEGER NOT NULL DEFAULT 1,
    row_version     INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_playbooks_source ON playbooks (source, kind) WHERE archived_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_playbooks_owner ON playbooks (owner_member_id) WHERE source = 'personal';

CREATE TABLE IF NOT EXISTS playbook_shares (
    playbook_id    TEXT NOT NULL REFERENCES playbooks (playbook_id) ON DELETE CASCADE,
    principal_type TEXT NOT NULL CHECK (principal_type IN ('member', 'team')),
    principal_id   TEXT NOT NULL,
    level          TEXT NOT NULL DEFAULT 'view' CHECK (level IN ('view', 'edit')),
    added_by       TEXT,
    added_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (playbook_id, principal_type, principal_id)
);

CREATE TABLE IF NOT EXISTS playbook_files (
    playbook_id TEXT NOT NULL REFERENCES playbooks (playbook_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    position    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (playbook_id, document_id)
);

-- Publishing firm playbooks (and firm templates, W6): knowledge managers, partners and firm administrators.
INSERT INTO role_permissions (role_key, permission)
SELECT r, 'km.publish' FROM unnest(ARRAY['knowledge_manager', 'partner', 'firm_admin']) AS r
WHERE EXISTS (SELECT 1 FROM firm_roles f WHERE f.role_key = r)
ON CONFLICT DO NOTHING;
