-- The workbench remembers what each person had open in each workspace (plan 22, W1.6): tabs, split, panel
-- sizes. Only ids are stored; every id is re-checked when the layout is loaded. Safe to re-run.

CREATE TABLE IF NOT EXISTS workbench_state (
    member_id  TEXT NOT NULL REFERENCES members (member_id) ON DELETE CASCADE,
    scope_key  TEXT NOT NULL CHECK (scope_key ~ '^(matter|project|library):[A-Za-z0-9_.-]{1,80}$'),
    state      JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (octet_length(state::text) <= 65536),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (member_id, scope_key)
);
