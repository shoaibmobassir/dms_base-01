-- Word review (plan 18): who changed what in each version's file, and Word comments.
-- Safe to re-run.

-- Per version: each person's tracked changes and comments inside the file (Word authors,
-- matched to firm members by name when possible).
CREATE TABLE IF NOT EXISTS document_revision_authors (
    version_id    TEXT NOT NULL REFERENCES document_versions (version_id) ON DELETE CASCADE,
    document_id   TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    author_name   TEXT NOT NULL,
    member_id     TEXT REFERENCES members (member_id),
    insertions    INTEGER NOT NULL DEFAULT 0,
    deletions     INTEGER NOT NULL DEFAULT 0,
    formats       INTEGER NOT NULL DEFAULT 0,
    moves         INTEGER NOT NULL DEFAULT 0,
    paragraphs    INTEGER NOT NULL DEFAULT 0,
    words_added   INTEGER NOT NULL DEFAULT 0,
    words_removed INTEGER NOT NULL DEFAULT 0,
    comments      INTEGER NOT NULL DEFAULT 0,
    replies       INTEGER NOT NULL DEFAULT 0,
    first_at      TIMESTAMPTZ,
    last_at       TIMESTAMPTZ,
    PRIMARY KEY (version_id, author_name)
);
CREATE INDEX IF NOT EXISTS idx_revision_authors_member ON document_revision_authors (member_id);
CREATE INDEX IF NOT EXISTS idx_revision_authors_document ON document_revision_authors (document_id);

ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS review_indexed_at TIMESTAMPTZ;

-- Comments that came from (or went to) a Word file.
ALTER TABLE annotations ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'precentis'
    CHECK (source IN ('precentis', 'word'));
ALTER TABLE annotations ADD COLUMN IF NOT EXISTS external_id TEXT;
ALTER TABLE annotations ADD COLUMN IF NOT EXISTS anchor_pid INTEGER;
CREATE UNIQUE INDEX IF NOT EXISTS uq_annotations_external ON annotations (document_id, external_id) WHERE external_id IS NOT NULL;
