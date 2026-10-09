-- Durable tabular reviews (plan 22, W4): many questions over many documents, one cell per (row, column).
--
-- A review belongs to a workspace (matter, project or a person's library) and follows its access. Rows are documents,
-- or folders (all the documents in a folder answer together). A run is done as the person who started it: a row they
-- cannot read is never sent to the model. Each cell records the documents its answer was drawn from
-- (`source_documents`), so a viewer who cannot read one of them sees the cell as restricted.
--
-- Rows are claimed by a worker with a lease (`lease_until`), FOR UPDATE SKIP LOCKED, so two runs never fill the same
-- cell and a crashed run is picked up again once its lease lapses. Safe to re-run.

CREATE TABLE IF NOT EXISTS tab_reviews (
    review_id       TEXT PRIMARY KEY,
    title           TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    container_kind  TEXT NOT NULL CHECK (container_kind IN ('matter', 'project', 'library')),
    container_id    TEXT NOT NULL,
    owner_member_id TEXT REFERENCES members (member_id),
    group_by        TEXT NOT NULL DEFAULT 'document' CHECK (group_by IN ('document', 'folder')),
    model           TEXT,
    playbook_id     TEXT,
    run_by          TEXT REFERENCES members (member_id),
    run_started_at  TIMESTAMPTZ,
    row_version     INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tab_reviews_container ON tab_reviews (container_kind, container_id);

CREATE TABLE IF NOT EXISTS tab_columns (
    column_id     TEXT PRIMARY KEY,
    review_id     TEXT NOT NULL REFERENCES tab_reviews (review_id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    label         TEXT NOT NULL CHECK (char_length(label) BETWEEN 1 AND 120),
    question      TEXT NOT NULL CHECK (char_length(question) BETWEEN 1 AND 2000),
    answer_format TEXT NOT NULL DEFAULT 'text'
                  CHECK (answer_format IN ('text', 'date', 'yes_no', 'number', 'money', 'list', 'choice')),
    choices       TEXT[] NOT NULL DEFAULT '{}',
    revision      INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_tab_columns_review ON tab_columns (review_id, position);

CREATE TABLE IF NOT EXISTS tab_rows (
    row_id      TEXT PRIMARY KEY,
    review_id   TEXT NOT NULL REFERENCES tab_reviews (review_id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    document_id TEXT REFERENCES documents (document_id) ON DELETE CASCADE,
    folder_path TEXT,
    lease_owner TEXT,
    lease_until TIMESTAMPTZ,
    CHECK ((document_id IS NULL) <> (folder_path IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_tab_rows_review ON tab_rows (review_id, position);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tab_rows_doc ON tab_rows (review_id, document_id) WHERE document_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_tab_rows_folder ON tab_rows (review_id, folder_path) WHERE folder_path IS NOT NULL;

CREATE TABLE IF NOT EXISTS tab_cells (
    row_id           TEXT NOT NULL REFERENCES tab_rows (row_id) ON DELETE CASCADE,
    column_id        TEXT NOT NULL REFERENCES tab_columns (column_id) ON DELETE CASCADE,
    column_revision  INTEGER NOT NULL DEFAULT 1,
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'running', 'done', 'not_found', 'failed', 'stale')),
    answer           TEXT,
    citations        JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_documents TEXT[] NOT NULL DEFAULT '{}',
    error            TEXT,
    model_answer     TEXT,
    edited_by        TEXT REFERENCES members (member_id),
    edited_at        TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (row_id, column_id)
);
CREATE INDEX IF NOT EXISTS idx_tab_cells_pending ON tab_cells (row_id) WHERE status IN ('pending', 'stale');
