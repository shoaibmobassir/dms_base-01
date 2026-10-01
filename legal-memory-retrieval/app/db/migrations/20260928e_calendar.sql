-- Calendar (plan 17, P3): events beside court deadlines, second-lawyer confirmation of
-- court deadlines, and private ICS feeds. Safe to re-run.

CREATE TABLE IF NOT EXISTS calendar_events (
    event_id        TEXT PRIMARY KEY,
    matter_id       TEXT REFERENCES matters (matter_id) ON DELETE CASCADE,   -- NULL: a personal event
    title           TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'meeting'
                    CHECK (kind IN ('hearing', 'filing', 'limitation', 'compliance', 'meeting', 'internal', 'out_of_office')),
    starts_at       TIMESTAMPTZ NOT NULL,
    ends_at         TIMESTAMPTZ NOT NULL,
    all_day         BOOLEAN NOT NULL DEFAULT FALSE,
    location        TEXT NOT NULL DEFAULT '',
    detail          TEXT NOT NULL DEFAULT '',
    owner_member_id TEXT NOT NULL REFERENCES members (member_id),
    attendees       TEXT[] NOT NULL DEFAULT '{}',
    created_by      TEXT REFERENCES members (member_id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_version     INTEGER NOT NULL DEFAULT 1,
    CHECK (ends_at >= starts_at)
);
CREATE INDEX IF NOT EXISTS idx_calendar_events_time ON calendar_events (starts_at);
CREATE INDEX IF NOT EXISTS idx_calendar_events_matter ON calendar_events (matter_id);
CREATE INDEX IF NOT EXISTS idx_calendar_events_attendees ON calendar_events USING gin (attendees);

-- Court deadlines: who entered them, and a second lawyer's confirmation.
ALTER TABLE court_deadlines ADD COLUMN IF NOT EXISTS created_by_member_id TEXT REFERENCES members (member_id);
ALTER TABLE court_deadlines ADD COLUMN IF NOT EXISTS confirmed_by_member_id TEXT REFERENCES members (member_id);
ALTER TABLE court_deadlines ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ;
ALTER TABLE court_deadlines ADD COLUMN IF NOT EXISTS row_version INTEGER NOT NULL DEFAULT 1;
-- Deadlines that predate confirmation were imported from the docket: confirmed, by no one.
UPDATE court_deadlines SET confirmed_at = coalesce(confirmed_at, now())
WHERE created_by_member_id IS NULL AND confirmed_at IS NULL;

-- Private calendar subscriptions (calendar apps cannot send our headers: the token is the key).
CREATE TABLE IF NOT EXISTS calendar_feeds (
    member_id           TEXT PRIMARY KEY REFERENCES members (member_id) ON DELETE CASCADE,
    token_hash          TEXT NOT NULL UNIQUE,
    show_restricted     BOOLEAN NOT NULL DEFAULT FALSE,   -- titles of restricted matters, or "Restricted matter"
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at        TIMESTAMPTZ
);
