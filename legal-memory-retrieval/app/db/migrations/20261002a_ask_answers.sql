-- Stored Ask the Firm answers: question + grounded payload per member/scope.
-- Reading a saved answer still re-checks the matter ACL; the model is not re-run.
-- Safe to re-run.

CREATE TABLE IF NOT EXISTS ask_answers (
    id              TEXT PRIMARY KEY,
    member_id       TEXT NOT NULL REFERENCES members (member_id) ON DELETE CASCADE,
    query           TEXT NOT NULL,
    scope           TEXT,
    scope_type      TEXT,
    asked_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    answered_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    answer          TEXT NOT NULL DEFAULT '',
    key_finding     TEXT NOT NULL DEFAULT '',
    status          TEXT,
    provider        TEXT,
    model           TEXT,
    abstained       BOOLEAN NOT NULL DEFAULT FALSE,
    reason          TEXT,
    citations       JSONB NOT NULL DEFAULT '[]'::jsonb,
    span_citations  JSONB NOT NULL DEFAULT '[]'::jsonb,
    panel           JSONB,
    matter_cards    JSONB NOT NULL DEFAULT '[]'::jsonb,
    sources         JSONB NOT NULL DEFAULT '[]'::jsonb,
    people          JSONB NOT NULL DEFAULT '[]'::jsonb,
    resolved_scope  JSONB,
    grounding       JSONB,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ask_answers_question
    ON ask_answers (member_id, query, coalesce(scope, ''), coalesce(scope_type, ''));
CREATE INDEX IF NOT EXISTS idx_ask_answers_member ON ask_answers (member_id, answered_at DESC);
