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
