-- Autosave for the Word editor (plan 22, W2b.2): the edited .docx the browser sends every half minute, one per person
-- per document, kept in the object store. It is offered back when that person reopens the editor on the same base
-- version, and removed when they save a version or discard it. Safe to re-run.
CREATE TABLE IF NOT EXISTS document_docx_drafts (
    document_id     TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    member_id       TEXT NOT NULL REFERENCES members (member_id) ON DELETE CASCADE,
    base_version_id TEXT NOT NULL,
    storage_uri     TEXT NOT NULL,
    size_bytes      BIGINT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, member_id)
);
