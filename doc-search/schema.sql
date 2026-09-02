CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS docs_files (
    file_id      TEXT PRIMARY KEY,
    filename     TEXT NOT NULL UNIQUE,
    filepath     TEXT NOT NULL,
    page_count   INT,
    -- DMS metadata
    matter_id    TEXT,
    client_name  TEXT,
    document_type TEXT,
    forum        TEXT,
    case_number  TEXT,
    tags         TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS docs_chunks (
    chunk_id    TEXT PRIMARY KEY,
    file_id     TEXT NOT NULL REFERENCES docs_files(file_id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    page_number INT NOT NULL,
    chunk_index INT NOT NULL,
    text        TEXT NOT NULL,
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    embedding   vector(384),
    -- Denormalized metadata for fast retrieval (avoid joins)
    matter_id   TEXT,
    document_type TEXT,
    tags        TEXT[] NOT NULL DEFAULT '{}',
    UNIQUE (file_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_dchunks_tsv ON docs_chunks USING gin(tsv);
CREATE INDEX IF NOT EXISTS idx_dchunks_emb ON docs_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_dchunks_matter ON docs_chunks (matter_id);
CREATE INDEX IF NOT EXISTS idx_dchunks_tags ON docs_chunks USING gin(tags);
