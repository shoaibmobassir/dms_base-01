-- +goose Up

-- =====================================================
-- Migration 002: Matters, Clients, Practice Areas
-- =====================================================

CREATE TABLE clients (
    client_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id       UUID NOT NULL REFERENCES firms(firm_id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    client_type   TEXT NOT NULL CHECK (client_type IN ('individual', 'organisation')),
    contact_email TEXT,
    contact_phone TEXT,
    address       JSONB,
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_clients_firm ON clients(firm_id);

CREATE TABLE practice_areas (
    area_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id    UUID NOT NULL REFERENCES firms(firm_id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    color      TEXT DEFAULT '#6366f1',
    sort_order INT DEFAULT 0,
    UNIQUE (firm_id, name)
);

CREATE TABLE matters (
    matter_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id          UUID NOT NULL REFERENCES firms(firm_id) ON DELETE CASCADE,
    matter_code      TEXT NOT NULL,
    title            TEXT NOT NULL,
    description      TEXT,
    practice_area_id UUID REFERENCES practice_areas(area_id) ON DELETE SET NULL,
    client_id        UUID REFERENCES clients(client_id) ON DELETE SET NULL,
    status           TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('draft', 'active', 'on_hold', 'closed', 'archived')),
    lead_user_id     UUID REFERENCES users(user_id) ON DELETE SET NULL,
    metadata         JSONB DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at        TIMESTAMPTZ,
    archived_at      TIMESTAMPTZ,
    deleted_at       TIMESTAMPTZ,
    UNIQUE (firm_id, matter_code)
);

CREATE INDEX idx_matters_firm ON matters(firm_id);
CREATE INDEX idx_matters_status ON matters(firm_id, status);
CREATE INDEX idx_matters_client ON matters(client_id);
CREATE INDEX idx_matters_lead ON matters(lead_user_id);

CREATE TABLE matter_members (
    matter_id   UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    matter_role TEXT NOT NULL DEFAULT 'contributor'
                CHECK (matter_role IN ('lead', 'contributor', 'observer')),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    assigned_by UUID REFERENCES users(user_id),
    PRIMARY KEY (matter_id, user_id)
);

CREATE TABLE matter_folders (
    folder_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id        UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    parent_folder_id UUID REFERENCES matter_folders(folder_id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    sort_order       INT DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (matter_id, parent_folder_id, name)
);

CREATE TABLE matter_relationships (
    from_matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    to_matter_id   UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    relationship   TEXT NOT NULL CHECK (relationship IN (
        'related_to', 'appeal_of', 'continuation_of', 'opposing'
    )),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by     UUID NOT NULL REFERENCES users(user_id),
    PRIMARY KEY (from_matter_id, to_matter_id)
);

CREATE TABLE matter_code_sequences (
    firm_id     UUID PRIMARY KEY REFERENCES firms(firm_id) ON DELETE CASCADE,
    last_number INT NOT NULL DEFAULT 0
);

-- +goose Down
DROP TABLE IF EXISTS matter_code_sequences;
DROP TABLE IF EXISTS matter_relationships;
DROP TABLE IF EXISTS matter_folders;
DROP TABLE IF EXISTS matter_members;
DROP TABLE IF EXISTS matters;
DROP TABLE IF EXISTS practice_areas;
DROP TABLE IF EXISTS clients;
