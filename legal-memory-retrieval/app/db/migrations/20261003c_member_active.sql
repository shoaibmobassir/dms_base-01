-- People can be deactivated (they left, or are on leave) without losing their history. Safe to re-run.
ALTER TABLE members ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE members ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ;
ALTER TABLE members ADD COLUMN IF NOT EXISTS deactivated_by TEXT;
