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
    embedding_ctx vector(384),  -- C5.5 contextual chunk (title+type+section+text); optional
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

ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS parent_version_id TEXT;
ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS storage_uri TEXT;
ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS change_summary TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS folder_path TEXT;

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

-- ═══════════════════════════════════════════════════════════════════
-- Document Intelligence + Immutable Version Control & Review Engine
-- ═══════════════════════════════════════════════════════════════════

-- 1. Canonical Document Blocks (AST Nodes)
CREATE TABLE IF NOT EXISTS document_blocks (
    block_id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES document_versions (version_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    page_number INT NOT NULL DEFAULT 1,
    sequence INT NOT NULL,
    section_id TEXT,                    -- e.g. "8.2", "Clause 4.1"
    section_title TEXT,
    block_type TEXT NOT NULL,           -- heading | paragraph | clause | table | table_cell | footnote | header | footer | list | signature | citation
    text TEXT NOT NULL,
    text_hash VARCHAR(64) NOT NULL,     -- SHA-256 hex digest of block text
    start_offset INT NOT NULL,          -- Character offset within document version
    end_offset INT NOT NULL,            -- Character offset end within document version
    embedding vector(384),
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_docblocks_ver_seq ON document_blocks (version_id, sequence);
CREATE INDEX IF NOT EXISTS idx_docblocks_doc ON document_blocks (document_id);
CREATE INDEX IF NOT EXISTS idx_docblocks_type ON document_blocks (block_type);
CREATE INDEX IF NOT EXISTS idx_docblocks_hash ON document_blocks (text_hash);

-- 2. Version Diffs (Lexical + Semantic Legal Delta)
CREATE TABLE IF NOT EXISTS version_diffs (
    diff_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    source_version_id TEXT NOT NULL REFERENCES document_versions (version_id) ON DELETE CASCADE,
    target_version_id TEXT NOT NULL REFERENCES document_versions (version_id) ON DELETE CASCADE,
    lexical_diff JSONB NOT NULL DEFAULT '{}',
    semantic_diff JSONB NOT NULL DEFAULT '{}',
    material_changes_count INT NOT NULL DEFAULT 0,
    risk_level TEXT NOT NULL DEFAULT 'neutral', -- low | medium | high | critical | neutral
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_version_id, target_version_id)
);

CREATE INDEX IF NOT EXISTS idx_verdiffs_doc ON version_diffs (document_id);
CREATE INDEX IF NOT EXISTS idx_verdiffs_source_target ON version_diffs (source_version_id, target_version_id);

-- 3. Review Jobs (High-concurrency Map-Reduce-Verify Review Runs)
CREATE TABLE IF NOT EXISTS review_jobs (
    job_id TEXT PRIMARY KEY,
    matter_id TEXT REFERENCES matters (matter_id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    features_requested TEXT[] NOT NULL DEFAULT '{}',
    target_document_ids TEXT[] NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending', -- pending | running | completed | failed
    total_documents INT NOT NULL DEFAULT 0,
    relevant_documents_count INT NOT NULL DEFAULT 0,
    findings_count INT NOT NULL DEFAULT 0,
    duration_ms INT,
    error_summary TEXT,
    created_by TEXT REFERENCES members (member_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_reviewjobs_matter ON review_jobs (matter_id);
CREATE INDEX IF NOT EXISTS idx_reviewjobs_status ON review_jobs (status);

-- 4. Structured Legal Findings
CREATE TABLE IF NOT EXISTS findings (
    finding_id TEXT PRIMARY KEY,
    review_job_id TEXT REFERENCES review_jobs (job_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    version_id TEXT NOT NULL REFERENCES document_versions (version_id) ON DELETE CASCADE,
    category TEXT NOT NULL,             -- indemnity | liability | termination | change_of_control | governing_law | assignment | compliance | other
    severity TEXT NOT NULL DEFAULT 'medium', -- critical | high | medium | low | info
    title TEXT NOT NULL,
    explanation TEXT NOT NULL,
    risk_direction TEXT NOT NULL DEFAULT 'neutral', -- risk_increased | risk_decreased | neutral
    financial_impact_usd NUMERIC(15, 2),
    confidence_score FLOAT NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'open', -- open | reviewed | accepted | dismissed
    created_by TEXT DEFAULT 'AI',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_findings_job ON findings (review_job_id);
CREATE INDEX IF NOT EXISTS idx_findings_doc_ver ON findings (document_id, version_id);
CREATE INDEX IF NOT EXISTS idx_findings_category ON findings (category);
CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings (severity);

-- 5. Evidence Anchors (3-Tier Durable Anchoring to Blocks)
CREATE TABLE IF NOT EXISTS evidence_anchors (
    anchor_id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL REFERENCES findings (finding_id) ON DELETE CASCADE,
    version_id TEXT NOT NULL REFERENCES document_versions (version_id) ON DELETE CASCADE,
    block_id TEXT NOT NULL REFERENCES document_blocks (block_id) ON DELETE CASCADE,
    page_number INT NOT NULL DEFAULT 1,
    start_offset INT NOT NULL,
    end_offset INT NOT NULL,
    quoted_text TEXT NOT NULL,
    text_hash VARCHAR(64) NOT NULL,
    anchor_confidence FLOAT NOT NULL DEFAULT 1.0,
    resolution_tier TEXT NOT NULL DEFAULT 'exact', -- exact | fuzzy | semantic
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_anchors_finding ON evidence_anchors (finding_id);
CREATE INDEX IF NOT EXISTS idx_anchors_ver_block ON evidence_anchors (version_id, block_id);

-- 6. Durable Annotations (AI Highlights, Lawyer Highlights, Comments, Issues, Redlines, Citations)
CREATE TABLE IF NOT EXISTS annotations (
    annotation_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    version_id TEXT NOT NULL REFERENCES document_versions (version_id) ON DELETE CASCADE,
    block_id TEXT REFERENCES document_blocks (block_id) ON DELETE SET NULL,
    annotation_type TEXT NOT NULL,      -- ai_highlight | user_highlight | comment | issue | redline | citation
    author_id TEXT REFERENCES members (member_id),
    author_name TEXT,
    finding_id TEXT REFERENCES findings (finding_id) ON DELETE SET NULL,
    page_number INT NOT NULL DEFAULT 1,
    start_offset INT NOT NULL,
    end_offset INT NOT NULL,
    quoted_text TEXT NOT NULL,
    text_hash VARCHAR(64) NOT NULL,
    content TEXT,                       -- Comment body or reason note
    status TEXT NOT NULL DEFAULT 'active', -- active | resolved | dismissed
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_annotations_doc_ver ON annotations (document_id, version_id);
CREATE INDEX IF NOT EXISTS idx_annotations_block ON annotations (block_id);
CREATE INDEX IF NOT EXISTS idx_annotations_type ON annotations (annotation_type);

-- Per-version intelligence cache (summaries / entities / clauses)
CREATE TABLE IF NOT EXISTS document_intelligence (
    version_id TEXT PRIMARY KEY REFERENCES document_versions (version_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    executive_summary TEXT,
    section_summaries JSONB NOT NULL DEFAULT '{}',
    entities JSONB NOT NULL DEFAULT '[]',
    clauses TEXT[] NOT NULL DEFAULT '{}',
    summary_version TEXT NOT NULL DEFAULT 'summary_v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_docintel_doc ON document_intelligence (document_id);

-- Upload batches (FirmOS Phase 3–4)
CREATE TABLE IF NOT EXISTS upload_batches (
    batch_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'harbour',
    matter_id TEXT NOT NULL REFERENCES matters (matter_id),
    client_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    total_files INT NOT NULL DEFAULT 0,
    processed_files INT NOT NULL DEFAULT 0,
    failed_files INT NOT NULL DEFAULT 0,
    ingest_job_id TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error_summary TEXT,
    manifest JSONB NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS upload_batch_files (
    item_id BIGSERIAL PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES upload_batches (batch_id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    size_bytes INT NOT NULL DEFAULT 0,
    mime_type TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    provisional_document_id TEXT,
    document_id TEXT,
    version_id TEXT,
    error TEXT,
    processed_at TIMESTAMPTZ,
    UNIQUE (batch_id, relative_path)
);

-- Version-scoped hierarchical chunk metadata
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS version_id TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS folder_path TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS section_id TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS section_title TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS page_number INT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS parent_chunk_id TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS block_ids TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS is_parent BOOLEAN NOT NULL DEFAULT FALSE;

