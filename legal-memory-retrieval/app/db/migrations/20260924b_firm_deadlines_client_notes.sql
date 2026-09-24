-- Data models behind UI sections that previously rendered hard-coded content.
-- Populated for demos by scripts/seed_demo.py. Additive only — safe to re-run.

-- Single-row firm identity (replaces "Apex Chambers" literals in API + UI).
CREATE TABLE IF NOT EXISTS firm_profile (
    id         BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
    name       TEXT NOT NULL,
    descriptor TEXT,
    office     TEXT,
    tenant_id  TEXT NOT NULL
);

-- Court / filing / limitation deadlines per matter (backs /api/tasks).
CREATE TABLE IF NOT EXISTS court_deadlines (
    deadline_id     TEXT PRIMARY KEY,
    matter_id       TEXT NOT NULL REFERENCES matters (matter_id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    kind            TEXT NOT NULL
        CHECK (kind IN ('hearing', 'filing', 'limitation', 'compliance')),
    due_date        DATE NOT NULL,
    court           TEXT,
    owner_member_id TEXT REFERENCES members (member_id),
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_deadlines_due ON court_deadlines (status, due_date);
CREATE INDEX IF NOT EXISTS idx_deadlines_matter ON court_deadlines (matter_id);

-- Observed client preferences, each traceable to the matter it came from.
CREATE TABLE IF NOT EXISTS client_notes (
    note_id          TEXT PRIMARY KEY,
    client_id        TEXT NOT NULL REFERENCES clients (client_id) ON DELETE CASCADE,
    kind             TEXT NOT NULL CHECK (kind IN ('prefers', 'avoid', 'terms')),
    text             TEXT NOT NULL,
    source_matter_id TEXT REFERENCES matters (matter_id) ON DELETE SET NULL,
    author_member_id TEXT REFERENCES members (member_id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_client_notes_client ON client_notes (client_id);
