-- Document versions as commits (plan 21, C2).
--
-- A version's stored file is the *clean* document: every tracked change accepted. Who changed what is the
-- difference between a version and its parent, computed on demand, not markup kept inside the file. Before this,
-- each save left the author's tracked changes in the stored .docx, so the current version was never clean and a
-- download carried the whole edit trail.
--
--   is_clean                   the stored file has no tracked changes (NULL = not checked yet, e.g. old rows)
--   restored_from_version_id   set when the version was made by restoring an earlier one (a new commit, like git revert)
--   source_storage_uri         the raw file as uploaded, kept as evidence when the stored file is its clean copy
--
-- ``origin`` (existing) gains the values 'import' (a Word file's text before its tracked changes) and 'restore';
-- ``change_summary`` (existing) is the commit message. Safe to re-run.

ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS is_clean boolean;
ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS restored_from_version_id text;
ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS source_storage_uri text;

CREATE INDEX IF NOT EXISTS idx_docver_doc_number ON document_versions (document_id, version_number);
