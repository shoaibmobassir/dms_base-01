-- Pinned conversations and a per-member list of Ask the Firm questions.
-- Both are personal conveniences: reading a pinned session or a past question
-- still goes through the session owner check and the matter ACL. Safe to re-run.
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS pinned_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS ask_history (
    id          TEXT PRIMARY KEY,
    member_id   TEXT NOT NULL REFERENCES members (member_id) ON DELETE CASCADE,
    query       TEXT NOT NULL,
    scope       TEXT,
    scope_type  TEXT,
    asked_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per distinct question and scope; asking again moves it to the top.
CREATE UNIQUE INDEX IF NOT EXISTS uq_ask_history_question
    ON ask_history (member_id, query, coalesce(scope, ''), coalesce(scope_type, ''));
CREATE INDEX IF NOT EXISTS idx_ask_history_member ON ask_history (member_id, asked_at DESC);
