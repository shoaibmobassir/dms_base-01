-- Access model (plan §5): firm roles, teams, matter access modes, grants,
-- screens (deny) and access requests.
--
-- `permissions` stays the table every query joins, but it is now COMPILED from
-- these tables by acl_compile_matter() (triggers keep it current):
--   restricted      = mode <> 'open'
--   allowed_members = member grants + members of granted teams
--                     + the matter team when mode = 'team'
--   denied_members  = screens; a screen always wins, even on firm-open matters
-- The backfill reproduces today's permissions exactly. Safe to re-run.

-- ── Firm roles ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS firm_roles (
    role_key    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_system   BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_key   TEXT NOT NULL REFERENCES firm_roles (role_key) ON DELETE CASCADE,
    permission TEXT NOT NULL,
    PRIMARY KEY (role_key, permission)
);

CREATE TABLE IF NOT EXISTS member_roles (
    member_id  TEXT NOT NULL REFERENCES members (member_id) ON DELETE CASCADE,
    role_key   TEXT NOT NULL REFERENCES firm_roles (role_key) ON DELETE CASCADE,
    granted_by TEXT,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (member_id, role_key)
);

INSERT INTO firm_roles (role_key, name, description) VALUES
    ('firm_admin', 'Firm administrator', 'Users, teams, roles, settings and integrations. No content access by role.'),
    ('risk_compliance', 'Risk & compliance', 'Ethical walls, screens, access requests and the audit log.'),
    ('knowledge_manager', 'Knowledge manager', 'Curates arguments, precedents and taxonomies.'),
    ('partner', 'Partner', 'Opens matters and manages the matters they lead.'),
    ('fee_earner', 'Fee earner', 'Works on matters they can access.'),
    ('staff', 'Staff', 'Support staff; works on matters they can access.')
ON CONFLICT (role_key) DO NOTHING;

INSERT INTO role_permissions (role_key, permission) VALUES
    ('firm_admin', 'users.manage'), ('firm_admin', 'teams.manage'), ('firm_admin', 'roles.manage'),
    ('firm_admin', 'settings.manage'), ('firm_admin', 'integrations.manage'), ('firm_admin', 'audit.read'),
    ('risk_compliance', 'walls.manage'), ('risk_compliance', 'access_requests.decide'),
    ('risk_compliance', 'audit.read'), ('risk_compliance', 'matters.create'),
    ('knowledge_manager', 'kb.curate'),
    ('partner', 'matters.create')
ON CONFLICT DO NOTHING;

-- Existing admins administer the firm and its walls; everyone gets a working role.
INSERT INTO member_roles (member_id, role_key, granted_by)
SELECT member_id, r.role_key, 'migration'
FROM members m
CROSS JOIN LATERAL (
    SELECT unnest(CASE
        WHEN m.is_admin THEN ARRAY['firm_admin', 'risk_compliance']
        ELSE ARRAY[]::text[] END
      || CASE
        WHEN m.role = 'Partner' THEN ARRAY['partner']
        WHEN m.role = 'Knowledge Manager' THEN ARRAY['knowledge_manager']
        WHEN m.role IN ('Paralegal') THEN ARRAY['staff']
        ELSE ARRAY['fee_earner'] END) AS role_key
) r
ON CONFLICT DO NOTHING;

-- ── Teams ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS teams (
    team_id           TEXT PRIMARY KEY,
    name              TEXT NOT NULL UNIQUE,
    kind              TEXT NOT NULL DEFAULT 'custom' CHECK (kind IN ('practice', 'office', 'matter', 'custom')),
    description       TEXT NOT NULL DEFAULT '',
    external_group_id TEXT,              -- Entra group object id when synced
    created_by        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS team_members (
    team_id   TEXT NOT NULL REFERENCES teams (team_id) ON DELETE CASCADE,
    member_id TEXT NOT NULL REFERENCES members (member_id) ON DELETE CASCADE,
    team_role TEXT NOT NULL DEFAULT 'member' CHECK (team_role IN ('member', 'lead')),
    added_by  TEXT,
    added_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, member_id)
);
CREATE INDEX IF NOT EXISTS idx_team_members_member ON team_members (member_id);

-- Seed practice and office teams from the directory.
INSERT INTO teams (team_id, name, kind, created_by)
SELECT DISTINCT 'TEAM-P-' || upper(regexp_replace(p, '[^A-Za-z0-9]+', '-', 'g')), p || ' practice', 'practice', 'migration'
FROM members, unnest(practice_areas) p
ON CONFLICT DO NOTHING;
INSERT INTO team_members (team_id, member_id, added_by)
SELECT 'TEAM-P-' || upper(regexp_replace(p, '[^A-Za-z0-9]+', '-', 'g')), member_id, 'migration'
FROM members, unnest(practice_areas) p
ON CONFLICT DO NOTHING;
INSERT INTO teams (team_id, name, kind, created_by)
SELECT DISTINCT 'TEAM-O-' || upper(regexp_replace(office, '[^A-Za-z0-9]+', '-', 'g')), office || ' office', 'office', 'migration'
FROM members WHERE office IS NOT NULL
ON CONFLICT DO NOTHING;
INSERT INTO team_members (team_id, member_id, added_by)
SELECT 'TEAM-O-' || upper(regexp_replace(office, '[^A-Za-z0-9]+', '-', 'g')), member_id, 'migration'
FROM members WHERE office IS NOT NULL
ON CONFLICT DO NOTHING;

-- ── Matter staffing dates (who is working vs has worked) ─────────────────────
ALTER TABLE matter_members ADD COLUMN IF NOT EXISTS started_at DATE;
ALTER TABLE matter_members ADD COLUMN IF NOT EXISTS ended_at DATE;

-- ── Matter access ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS matter_access (
    matter_id      TEXT PRIMARY KEY REFERENCES matters (matter_id) ON DELETE CASCADE,
    mode           TEXT NOT NULL DEFAULT 'open' CHECK (mode IN ('open', 'team', 'restricted')),
    hide_existence BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by     TEXT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_version    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS matter_grants (
    grant_id       TEXT PRIMARY KEY,
    matter_id      TEXT NOT NULL REFERENCES matters (matter_id) ON DELETE CASCADE,
    principal_type TEXT NOT NULL CHECK (principal_type IN ('member', 'team')),
    principal_id   TEXT NOT NULL,
    level          TEXT NOT NULL DEFAULT 'read' CHECK (level IN ('read', 'edit', 'manage')),
    reason         TEXT NOT NULL DEFAULT '',
    expires_at     TIMESTAMPTZ,
    granted_by     TEXT,
    granted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (matter_id, principal_type, principal_id)
);
CREATE INDEX IF NOT EXISTS idx_matter_grants_principal ON matter_grants (principal_type, principal_id);

CREATE TABLE IF NOT EXISTS matter_screens (
    matter_id  TEXT NOT NULL REFERENCES matters (matter_id) ON DELETE CASCADE,
    member_id  TEXT NOT NULL REFERENCES members (member_id) ON DELETE CASCADE,
    reason     TEXT NOT NULL,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (matter_id, member_id)
);

CREATE TABLE IF NOT EXISTS access_requests (
    request_id    TEXT PRIMARY KEY,
    matter_id     TEXT NOT NULL REFERENCES matters (matter_id) ON DELETE CASCADE,
    requester_id  TEXT NOT NULL REFERENCES members (member_id) ON DELETE CASCADE,
    level         TEXT NOT NULL DEFAULT 'read' CHECK (level IN ('read', 'edit')),
    reason        TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'denied', 'cancelled')),
    decided_by    TEXT,
    decided_at    TIMESTAMPTZ,
    decision_note TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_access_requests_status ON access_requests (status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_access_requests_pending
    ON access_requests (matter_id, requester_id) WHERE status = 'pending';

ALTER TABLE permissions ADD COLUMN IF NOT EXISTS denied_members TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE permissions ADD COLUMN IF NOT EXISTS compiled_at TIMESTAMPTZ;

-- Backfill from today's permissions: restricted → restricted mode with member grants.
INSERT INTO matter_access (matter_id, mode, hide_existence, updated_by)
SELECT m.matter_id,
       CASE WHEN coalesce(p.restricted, FALSE) THEN 'restricted' ELSE 'open' END,
       coalesce(p.restricted, FALSE),
       'migration'
FROM matters m LEFT JOIN permissions p ON p.matter_id = m.matter_id
ON CONFLICT (matter_id) DO NOTHING;

INSERT INTO matter_grants (grant_id, matter_id, principal_type, principal_id, level, reason, granted_by)
SELECT 'GRT-' || substr(md5(p.matter_id || ':' || a), 1, 12), p.matter_id, 'member', a,
       CASE WHEN EXISTS (SELECT 1 FROM matter_members mm WHERE mm.matter_id = p.matter_id
                           AND mm.member_id = a AND mm.role_on_matter = 'Lead') THEN 'manage' ELSE 'edit' END,
       'Migrated from the matter allow-list', 'migration'
FROM permissions p, unnest(p.allowed_members) a
WHERE p.restricted AND EXISTS (SELECT 1 FROM members WHERE member_id = a)
ON CONFLICT DO NOTHING;

-- ── Compile ───────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION acl_compile_matter(p_matter_id TEXT) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
    v_mode    TEXT;
    v_allowed TEXT[];
    v_denied  TEXT[];
BEGIN
    IF NOT EXISTS (SELECT 1 FROM matters WHERE matter_id = p_matter_id) THEN
        RETURN;
    END IF;
    SELECT coalesce((SELECT mode FROM matter_access WHERE matter_id = p_matter_id), 'open') INTO v_mode;
    SELECT coalesce(array_agg(DISTINCT x.member_id ORDER BY x.member_id), '{}') INTO v_allowed FROM (
        SELECT g.principal_id AS member_id FROM matter_grants g
        WHERE g.matter_id = p_matter_id AND g.principal_type = 'member'
          AND (g.expires_at IS NULL OR g.expires_at > now())
        UNION
        SELECT tm.member_id FROM matter_grants g JOIN team_members tm ON tm.team_id = g.principal_id
        WHERE g.matter_id = p_matter_id AND g.principal_type = 'team'
          AND (g.expires_at IS NULL OR g.expires_at > now())
        UNION
        SELECT mm.member_id FROM matter_members mm
        WHERE mm.matter_id = p_matter_id AND v_mode = 'team'
    ) x;
    SELECT coalesce(array_agg(member_id ORDER BY member_id), '{}') INTO v_denied
    FROM matter_screens WHERE matter_id = p_matter_id;

    INSERT INTO permissions (matter_id, restricted, allowed_members, denied_members, practice_area, compiled_at)
    SELECT p_matter_id, v_mode <> 'open', v_allowed, v_denied, m.practice_area, now()
    FROM matters m WHERE m.matter_id = p_matter_id
    ON CONFLICT (matter_id) DO UPDATE SET
        restricted = EXCLUDED.restricted,
        allowed_members = EXCLUDED.allowed_members,
        denied_members = EXCLUDED.denied_members,
        compiled_at = EXCLUDED.compiled_at;
END $$;

CREATE OR REPLACE FUNCTION acl_compile_all() RETURNS INTEGER LANGUAGE plpgsql AS $$
DECLARE
    r RECORD;
    n INTEGER := 0;
BEGIN
    FOR r IN SELECT matter_id FROM matters LOOP
        PERFORM acl_compile_matter(r.matter_id);
        n := n + 1;
    END LOOP;
    RETURN n;
END $$;

CREATE OR REPLACE FUNCTION acl_matter_trigger() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        PERFORM acl_compile_matter(OLD.matter_id);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        PERFORM acl_compile_matter(NEW.matter_id);
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION acl_team_trigger() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    r RECORD;
    v_team TEXT := coalesce(NEW.team_id, OLD.team_id);
BEGIN
    FOR r IN SELECT DISTINCT matter_id FROM matter_grants
             WHERE principal_type = 'team' AND principal_id = v_team LOOP
        PERFORM acl_compile_matter(r.matter_id);
    END LOOP;
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS trg_acl_matter_access ON matter_access;
CREATE TRIGGER trg_acl_matter_access AFTER INSERT OR UPDATE OR DELETE ON matter_access
    FOR EACH ROW EXECUTE FUNCTION acl_matter_trigger();
DROP TRIGGER IF EXISTS trg_acl_matter_grants ON matter_grants;
CREATE TRIGGER trg_acl_matter_grants AFTER INSERT OR UPDATE OR DELETE ON matter_grants
    FOR EACH ROW EXECUTE FUNCTION acl_matter_trigger();
DROP TRIGGER IF EXISTS trg_acl_matter_screens ON matter_screens;
CREATE TRIGGER trg_acl_matter_screens AFTER INSERT OR UPDATE OR DELETE ON matter_screens
    FOR EACH ROW EXECUTE FUNCTION acl_matter_trigger();
DROP TRIGGER IF EXISTS trg_acl_matter_members ON matter_members;
CREATE TRIGGER trg_acl_matter_members AFTER INSERT OR UPDATE OR DELETE ON matter_members
    FOR EACH ROW EXECUTE FUNCTION acl_matter_trigger();
DROP TRIGGER IF EXISTS trg_acl_team_members ON team_members;
CREATE TRIGGER trg_acl_team_members AFTER INSERT OR UPDATE OR DELETE ON team_members
    FOR EACH ROW EXECUTE FUNCTION acl_team_trigger();

-- A new matter starts firm-open unless intake says otherwise (compiled by the trigger).
CREATE OR REPLACE FUNCTION acl_new_matter_trigger() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO matter_access (matter_id, mode, updated_by) VALUES (NEW.matter_id, 'open', 'system')
    ON CONFLICT (matter_id) DO NOTHING;
    PERFORM acl_compile_matter(NEW.matter_id);
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS trg_acl_new_matter ON matters;
CREATE TRIGGER trg_acl_new_matter AFTER INSERT ON matters
    FOR EACH ROW EXECUTE FUNCTION acl_new_matter_trigger();

-- Snapshot before compiling so the migration can prove it changed nothing.
CREATE TEMP TABLE acl_before AS SELECT matter_id, restricted, allowed_members FROM permissions;
SELECT acl_compile_all();
DO $$
DECLARE
    n INTEGER;
BEGIN
    SELECT count(*) INTO n
    FROM acl_before b JOIN permissions p USING (matter_id)
    WHERE b.restricted IS DISTINCT FROM p.restricted
       OR (b.restricted AND (SELECT array_agg(x ORDER BY x) FROM unnest(b.allowed_members) x)
              IS DISTINCT FROM (SELECT array_agg(x ORDER BY x) FROM unnest(p.allowed_members) x));
    IF n > 0 THEN
        RAISE EXCEPTION 'access model backfill changed % matters'' permissions', n;
    END IF;
END $$;
DROP TABLE acl_before;
