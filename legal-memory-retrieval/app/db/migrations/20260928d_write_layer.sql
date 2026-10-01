-- Write layer (plan 17, P2): matters, staffing, timeline events, arguments, related matters,
-- client intake with conflict checks, and a domain-event outbox for live updates.
-- Safe to re-run.

-- ── matters / arguments: who changed what, optimistic concurrency ────────────
ALTER TABLE matters ADD COLUMN IF NOT EXISTS created_by_member_id TEXT REFERENCES members (member_id);
ALTER TABLE matters ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
ALTER TABLE matters ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
ALTER TABLE matters ADD COLUMN IF NOT EXISTS row_version INTEGER NOT NULL DEFAULT 1;
CREATE SEQUENCE IF NOT EXISTS matter_number_seq START 10000;

ALTER TABLE arguments ADD COLUMN IF NOT EXISTS author_member_id TEXT REFERENCES members (member_id);
ALTER TABLE arguments ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
ALTER TABLE arguments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
ALTER TABLE arguments ADD COLUMN IF NOT EXISTS row_version INTEGER NOT NULL DEFAULT 1;

-- ── timeline events entered by people (the timeline also shows document dates) ─
CREATE TABLE IF NOT EXISTS matter_events (
    event_id           TEXT PRIMARY KEY,
    matter_id          TEXT NOT NULL REFERENCES matters (matter_id) ON DELETE CASCADE,
    occurred_on        DATE NOT NULL,
    title              TEXT NOT NULL,
    detail             TEXT NOT NULL DEFAULT '',
    kind               TEXT NOT NULL DEFAULT 'event'
                       CHECK (kind IN ('event', 'filing', 'hearing', 'order', 'correspondence', 'meeting', 'milestone')),
    source_document_id TEXT REFERENCES documents (document_id) ON DELETE SET NULL,
    created_by         TEXT REFERENCES members (member_id),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_version        INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_matter_events_matter ON matter_events (matter_id, occurred_on);

-- ── related matters linked by people (generated links stay in `relationships`) ─
CREATE TABLE IF NOT EXISTS matter_links (
    matter_id         TEXT NOT NULL REFERENCES matters (matter_id) ON DELETE CASCADE,
    related_matter_id TEXT NOT NULL REFERENCES matters (matter_id) ON DELETE CASCADE,
    relation          TEXT NOT NULL DEFAULT 'related'
                      CHECK (relation IN ('related', 'follow_up_to', 'parallel_proceeding', 'appeal_of', 'same_transaction', 'precedent_for')),
    note              TEXT NOT NULL DEFAULT '',
    created_by        TEXT REFERENCES members (member_id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (matter_id, related_matter_id),
    CHECK (matter_id <> related_matter_id)
);
CREATE INDEX IF NOT EXISTS idx_matter_links_related ON matter_links (related_matter_id);

-- ── clients: intake status ──────────────────────────────────────────────────
ALTER TABLE clients ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('prospective', 'active', 'declined'));
ALTER TABLE clients ADD COLUMN IF NOT EXISTS intake_check_id TEXT;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS created_by_member_id TEXT REFERENCES members (member_id);
ALTER TABLE clients ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;

-- ── conflict checks ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conflict_checks (
    check_id     TEXT PRIMARY KEY,
    names        TEXT[] NOT NULL,
    purpose      TEXT NOT NULL DEFAULT '',
    requested_by TEXT REFERENCES members (member_id),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    results      JSONB NOT NULL DEFAULT '[]'::jsonb,   -- full hits (risk sees all; requesters see a redacted view)
    decision     TEXT CHECK (decision IN ('clear', 'potential', 'conflict', 'waived')),
    decided_by   TEXT REFERENCES members (member_id),
    decided_at   TIMESTAMPTZ,
    notes        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_conflict_checks_open ON conflict_checks (requested_at) WHERE decision IS NULL;

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS idx_clients_name_trgm ON clients USING gin (lower(name) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_matters_opposing_trgm ON matters USING gin (lower(coalesce(opposing_party, '')) gin_trgm_ops);

-- ── domain events (outbox for live updates) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS domain_events (
    seq         BIGSERIAL PRIMARY KEY,
    topic       TEXT NOT NULL,             -- e.g. matter.updated, matter.team, client.created
    entity_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    matter_id   TEXT,
    document_id TEXT,
    actor       TEXT,
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_domain_events_occurred ON domain_events (occurred_at);

-- ── permissions ─────────────────────────────────────────────────────────────
INSERT INTO role_permissions (role_key, permission) VALUES
    ('partner', 'clients.create'),
    ('risk_compliance', 'clients.create'),
    ('firm_admin', 'clients.create'),
    ('risk_compliance', 'conflicts.decide')
ON CONFLICT DO NOTHING;
