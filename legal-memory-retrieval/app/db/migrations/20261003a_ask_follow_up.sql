-- A follow-up answer depends on the answer it follows, so it is stored apart from a stand-alone answer
-- with the same words. Safe to re-run.

ALTER TABLE ask_answers ADD COLUMN IF NOT EXISTS follow_up_of TEXT;

DROP INDEX IF EXISTS uq_ask_answers_question;
CREATE UNIQUE INDEX IF NOT EXISTS uq_ask_answers_question_v2
    ON ask_answers (member_id, query, coalesce(scope, ''), coalesce(scope_type, ''), coalesce(follow_up_of, ''));
