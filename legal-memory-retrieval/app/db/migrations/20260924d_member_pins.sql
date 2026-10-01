-- Matters a member pins to their sidebar. Visibility is still decided by the
-- matter ACL at read time: a pin never grants access. Safe to re-run.
CREATE TABLE IF NOT EXISTS member_pins (
    member_id  TEXT NOT NULL REFERENCES members (member_id) ON DELETE CASCADE,
    matter_id  TEXT NOT NULL REFERENCES matters (matter_id) ON DELETE CASCADE,
    pinned_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (member_id, matter_id)
);
