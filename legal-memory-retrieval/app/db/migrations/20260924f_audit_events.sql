-- Append-only, hash-chained audit stream (production plan 08, step B).
--
-- * UPDATE / DELETE / TRUNCATE are rejected by triggers — even for the table owner
--   through normal SQL. (A superuser can still disable triggers; ship the stream to
--   write-once storage — S3 Object Lock / immutable Blob — for that threat.)
-- * Each row's hash covers the previous row's hash, so any edit made with triggers
--   disabled is detectable by GET /api/audit/events/verify.
-- Safe to re-run.

ALTER TABLE members ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS audit_events (
    seq          BIGINT PRIMARY KEY,
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    member_id    TEXT,
    action       TEXT NOT NULL,
    outcome      TEXT NOT NULL DEFAULT 'success' CHECK (outcome IN ('success', 'denied', 'failure')),
    object_type  TEXT,
    object_id    TEXT,
    matter_id    TEXT,
    request_id   TEXT,
    ip           TEXT,
    detail       JSONB NOT NULL DEFAULT '{}'::jsonb,
    prev_hash    TEXT,
    hash         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_events (occurred_at);
CREATE INDEX IF NOT EXISTS idx_audit_member ON audit_events (member_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_audit_matter ON audit_events (matter_id, occurred_at);

CREATE OR REPLACE FUNCTION audit_events_chain() RETURNS trigger AS $$
DECLARE
    last_seq  BIGINT;
    last_hash TEXT;
BEGIN
    -- Serialise writers so seq and the chain have one order.
    PERFORM pg_advisory_xact_lock(hashtext('audit_events_chain'));
    SELECT seq, hash INTO last_seq, last_hash FROM audit_events ORDER BY seq DESC LIMIT 1;
    NEW.seq := COALESCE(last_seq, 0) + 1;
    NEW.prev_hash := last_hash;
    NEW.hash := encode(sha256(convert_to(
        COALESCE(last_hash, '') || '|' || NEW.seq || '|' ||
        to_char(NEW.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US') || '|' ||
        COALESCE(NEW.member_id, '') || '|' || NEW.action || '|' || NEW.outcome || '|' ||
        COALESCE(NEW.object_type, '') || '|' || COALESCE(NEW.object_id, '') || '|' ||
        COALESCE(NEW.matter_id, '') || '|' || NEW.detail::text,
        'UTF8')), 'hex');
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION audit_events_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only (% rejected)', TG_OP;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_chain ON audit_events;
CREATE TRIGGER trg_audit_chain BEFORE INSERT ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_chain();

DROP TRIGGER IF EXISTS trg_audit_no_update ON audit_events;
CREATE TRIGGER trg_audit_no_update BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_append_only();

DROP TRIGGER IF EXISTS trg_audit_no_truncate ON audit_events;
CREATE TRIGGER trg_audit_no_truncate BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only();
