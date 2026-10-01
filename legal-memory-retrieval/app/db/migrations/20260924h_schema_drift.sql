-- Schema drift: objects that existed only in databases touched by the old one-off
-- scripts/migrate_*.py and scripts/embed.py, never in schema.sql or a migration.
-- A fresh deployment lacked them (uploads failed on document_versions.mime_type).
-- Found by diffing a long-lived dev database against a freshly migrated one.
-- Safe to re-run.

ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS mime_type TEXT;

CREATE INDEX IF NOT EXISTS idx_docver_parent ON document_versions (parent_version_id);
CREATE INDEX IF NOT EXISTS idx_perm_restricted ON permissions (restricted);
CREATE INDEX IF NOT EXISTS idx_upload_batches_matter ON upload_batches (matter_id);
CREATE INDEX IF NOT EXISTS idx_upload_batches_status ON upload_batches (status);
CREATE INDEX IF NOT EXISTS idx_upload_files_batch ON upload_batch_files (batch_id);
CREATE INDEX IF NOT EXISTS idx_upload_files_status ON upload_batch_files (status);

-- Vector search index (previously created only by scripts/embed.py after a full embed).
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
