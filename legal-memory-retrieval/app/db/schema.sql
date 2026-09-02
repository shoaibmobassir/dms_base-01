CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

DROP TABLE IF EXISTS chunks CASCADE;
DROP TABLE IF EXISTS documents CASCADE;
DROP TABLE IF EXISTS projects CASCADE;
DROP TABLE IF EXISTS arguments CASCADE;
DROP TABLE IF EXISTS relationships CASCADE;
DROP TABLE IF EXISTS matter_members CASCADE;
DROP TABLE IF EXISTS permissions CASCADE;
DROP TABLE IF EXISTS matters CASCADE;
DROP TABLE IF EXISTS clients CASCADE;
DROP TABLE IF EXISTS members CASCADE;

CREATE TABLE members (
    member_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    practice_areas TEXT[] NOT NULL DEFAULT '{}',
    specializations TEXT[] NOT NULL DEFAULT '{}',
    office TEXT,
    joined_year INT,
    email TEXT,
    is_lawyer BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE clients (
    client_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    industry TEXT,
    size TEXT,
    headquarters TEXT,
    locations TEXT[] NOT NULL DEFAULT '{}',
    subsidiaries TEXT[] NOT NULL DEFAULT '{}',
    preferred_lawyer_ids TEXT[] NOT NULL DEFAULT '{}',
    aliases TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE matters (
    matter_id TEXT PRIMARY KEY,
    matter_code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    client_id TEXT NOT NULL REFERENCES clients (client_id),
    client_name TEXT,
    opposing_party TEXT,
    practice_area TEXT NOT NULL,
    matter_type TEXT NOT NULL,
    theme_key TEXT,
    jurisdiction TEXT,
    court TEXT,
    opened_date DATE,
    closed_date DATE,
    status TEXT,
    office TEXT,
    claim_amount TEXT,
    outcome TEXT,
    legal_issues TEXT[] NOT NULL DEFAULT '{}',
    facts TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE matter_members (
    matter_id TEXT NOT NULL REFERENCES matters (matter_id) ON DELETE CASCADE,
    member_id TEXT NOT NULL REFERENCES members (member_id),
    role_on_matter TEXT,
    PRIMARY KEY (matter_id, member_id)
);

CREATE TABLE permissions (
    matter_id TEXT PRIMARY KEY REFERENCES matters (matter_id) ON DELETE CASCADE,
    classification TEXT,
    restricted BOOLEAN NOT NULL DEFAULT FALSE,
    allowed_members TEXT[] NOT NULL DEFAULT '{}',
    practice_area TEXT
);

CREATE TABLE documents (
    document_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES matters (matter_id),
    matter_code TEXT,
    client_id TEXT,
    title TEXT NOT NULL,
    document_type TEXT NOT NULL,
    author_id TEXT REFERENCES members (member_id),
    author_name TEXT,
    doc_date DATE,
    status TEXT,
    version TEXT,
    parent_document_id TEXT,
    version_group TEXT,
    body TEXT NOT NULL
);

CREATE TABLE chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    matter_id TEXT NOT NULL REFERENCES matters (matter_id),
    chunk_index INT NOT NULL,
    text TEXT NOT NULL,
    tsv tsvector,
    embedding vector(384),
    UNIQUE (document_id, chunk_index)
);

CREATE TABLE relationships (
    id BIGSERIAL PRIMARY KEY,
    source_id TEXT NOT NULL,
    rel_type TEXT NOT NULL,
    target_id TEXT NOT NULL
);

CREATE TABLE arguments (
    argument_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES matters (matter_id),
    issue TEXT,
    position TEXT,
    argument TEXT,
    outcome TEXT,
    supporting_documents TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES matters (matter_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    practice_team TEXT NOT NULL,
    lead_member_id TEXT REFERENCES members (member_id),
    lead_lawyer TEXT,
    status TEXT NOT NULL DEFAULT 'In Progress',
    progress INT NOT NULL DEFAULT 0,
    deadline DATE,
    scope TEXT,
    milestones JSONB NOT NULL DEFAULT '[]'
);

CREATE INDEX idx_projects_matter ON projects (matter_id);
CREATE INDEX idx_projects_status ON projects (status);

CREATE INDEX idx_matters_client ON matters (client_id);
CREATE INDEX idx_matters_theme ON matters (theme_key);
CREATE INDEX idx_matters_practice ON matters (practice_area);
CREATE INDEX idx_matters_code_trgm ON matters USING gin (matter_code gin_trgm_ops);
CREATE INDEX idx_matters_title_trgm ON matters USING gin (title gin_trgm_ops);
CREATE INDEX idx_clients_name_trgm ON clients USING gin (name gin_trgm_ops);
CREATE INDEX idx_members_name_trgm ON members USING gin (name gin_trgm_ops);
CREATE INDEX idx_docs_matter ON documents (matter_id);
CREATE INDEX idx_docs_type ON documents (document_type);
CREATE INDEX idx_chunks_matter ON chunks (matter_id);
CREATE INDEX idx_chunks_tsv ON chunks USING gin (tsv);
CREATE INDEX idx_rel_source ON relationships (source_id, rel_type);
CREATE INDEX idx_rel_target ON relationships (target_id);
CREATE INDEX idx_perm_restricted ON permissions (restricted);

-- ═══════════════════════════════════════════════════════════════════
-- Sprint: Production Ingest Pipeline (additive — no DROP)
-- ═══════════════════════════════════════════════════════════════════

-- documents: provenance + dedup
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_uri TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_sha256 TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS mime_type TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS ingest_job_id TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMPTZ;
CREATE UNIQUE INDEX IF NOT EXISTS idx_docs_source_sha
    ON documents (matter_id, content_sha256) WHERE content_sha256 IS NOT NULL;

-- job tracking
CREATE TABLE IF NOT EXISTS ingest_jobs (
    job_id TEXT PRIMARY KEY,
    source_root TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|running|completed|failed
    total_items INT NOT NULL DEFAULT 0,
    indexed_items INT NOT NULL DEFAULT 0,
    failed_items INT NOT NULL DEFAULT 0,
    skipped_items INT NOT NULL DEFAULT 0,
    workers INT NOT NULL DEFAULT 1,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS ingest_items (
    item_id BIGSERIAL PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES ingest_jobs (job_id),
    source_uri TEXT NOT NULL,
    content_sha256 TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    document_id TEXT,
    error TEXT,
    processed_at TIMESTAMPTZ,
    UNIQUE (job_id, source_uri)
);

-- ═══════════════════════════════════════════════════════════════════
-- Projects Improvement: Document Versioning + Folders + Activity
-- ═══════════════════════════════════════════════════════════════════

-- Immutable version chain per document
CREATE TABLE IF NOT EXISTS document_versions (
    version_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    version_number INT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    author_name TEXT,
    source TEXT NOT NULL DEFAULT 'upload',  -- upload | edit | ingest | import | developing
    version_status TEXT NOT NULL DEFAULT 'draft',  -- draft | developing | review | final | executed
    version_label TEXT,
    file_size_bytes INT,
    page_count INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_docver_document ON document_versions (document_id, version_number DESC);

-- documents: pointer to active version + folder assignment
ALTER TABLE documents ADD COLUMN IF NOT EXISTS current_version_id TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS folder_id TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- Nested folder tree within projects
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

-- Project activity audit trail
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
