-- Document-level privacy (plan 17, P1b) + lapsed staffing.
--
-- A document follows its matter's access unless it has a row in `document_access`:
--   private     the owner, the people and teams it is shared with, and holders of walls.manage
--   restricted  the same, plus the matter's managers (lead, manage grants)
-- Both only NARROW matter access: every read keeps the matter ACL (permissions) and adds
-- `visible_to` (compiled here, on documents and on their chunks). NULL = follows the matter.
--
-- Staff whose `ended_at` has passed no longer count as the matter team.
-- Safe to re-run.

ALTER TABLE documents ADD COLUMN IF NOT EXISTS visible_to TEXT[];
ALTER TABLE chunks    ADD COLUMN IF NOT EXISTS visible_to TEXT[];

CREATE TABLE IF NOT EXISTS document_access (
    document_id     TEXT PRIMARY KEY REFERENCES documents (document_id) ON DELETE CASCADE,
    visibility      TEXT NOT NULL CHECK (visibility IN ('private', 'restricted')),
    owner_member_id TEXT NOT NULL REFERENCES members (member_id),
    row_version     INTEGER NOT NULL DEFAULT 1,
    updated_by      TEXT REFERENCES members (member_id),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_shares (
    document_id    TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    principal_type TEXT NOT NULL CHECK (principal_type IN ('member', 'team')),
    principal_id   TEXT NOT NULL,
    level          TEXT NOT NULL DEFAULT 'read' CHECK (level IN ('read', 'edit')),
    added_by       TEXT,
    added_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, principal_type, principal_id)
);
CREATE INDEX IF NOT EXISTS idx_document_shares_principal ON document_shares (principal_type, principal_id);

-- One row: moves forward on every document-ACL change (part of the retrieval cache key).
CREATE TABLE IF NOT EXISTS doc_acl_state (
    id         BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO doc_acl_state (id) VALUES (TRUE) ON CONFLICT DO NOTHING;

-- ── compile one document ─────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION doc_acl_compile(p_doc TEXT) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
    a        document_access%ROWTYPE;
    v_matter TEXT;
    v_list   TEXT[];
BEGIN
    SELECT * INTO a FROM document_access WHERE document_id = p_doc;
    IF NOT FOUND THEN
        v_list := NULL;
    ELSE
        SELECT matter_id INTO v_matter FROM documents WHERE document_id = p_doc;
        SELECT array_agg(DISTINCT x ORDER BY x) INTO v_list FROM (
            SELECT a.owner_member_id AS x
            UNION SELECT s.principal_id FROM document_shares s
                  WHERE s.document_id = p_doc AND s.principal_type = 'member'
            UNION SELECT tm.member_id FROM document_shares s JOIN team_members tm ON tm.team_id = s.principal_id
                  WHERE s.document_id = p_doc AND s.principal_type = 'team'
            UNION SELECT mr.member_id FROM member_roles mr JOIN role_permissions rp USING (role_key)
                  WHERE rp.permission = 'walls.manage'
            UNION SELECT mm.member_id FROM matter_members mm
                  WHERE a.visibility = 'restricted' AND mm.matter_id = v_matter
                    AND lower(coalesce(mm.role_on_matter, '')) = 'lead'
                    AND (mm.ended_at IS NULL OR mm.ended_at >= current_date)
            UNION SELECT g.principal_id FROM matter_grants g
                  WHERE a.visibility = 'restricted' AND g.matter_id = v_matter AND g.level = 'manage'
                    AND g.principal_type = 'member' AND (g.expires_at IS NULL OR g.expires_at > now())
            UNION SELECT tm.member_id FROM matter_grants g JOIN team_members tm ON tm.team_id = g.principal_id
                  WHERE a.visibility = 'restricted' AND g.matter_id = v_matter AND g.level = 'manage'
                    AND g.principal_type = 'team' AND (g.expires_at IS NULL OR g.expires_at > now())
        ) q WHERE x IS NOT NULL;
    END IF;
    UPDATE documents SET visible_to = v_list WHERE document_id = p_doc AND visible_to IS DISTINCT FROM v_list;
    UPDATE chunks SET visible_to = v_list WHERE document_id = p_doc AND visible_to IS DISTINCT FROM v_list;
    UPDATE doc_acl_state SET changed_at = clock_timestamp();
END $$;

CREATE OR REPLACE FUNCTION doc_acl_compile_where(p_sql_filter TEXT, p_value TEXT) RETURNS INTEGER LANGUAGE plpgsql AS $$
DECLARE
    r RECORD;
    n INTEGER := 0;
BEGIN
    FOR r IN EXECUTE 'SELECT da.document_id FROM document_access da JOIN documents d USING (document_id) WHERE ' || p_sql_filter
             USING p_value LOOP
        PERFORM doc_acl_compile(r.document_id);
        n := n + 1;
    END LOOP;
    RETURN n;
END $$;

-- ── triggers ─────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION trg_doc_access_changed() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM doc_acl_compile(coalesce(NEW.document_id, OLD.document_id));
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS doc_access_changed ON document_access;
CREATE TRIGGER doc_access_changed AFTER INSERT OR UPDATE OR DELETE ON document_access
    FOR EACH ROW EXECUTE FUNCTION trg_doc_access_changed();
DROP TRIGGER IF EXISTS doc_shares_changed ON document_shares;
CREATE TRIGGER doc_shares_changed AFTER INSERT OR UPDATE OR DELETE ON document_shares
    FOR EACH ROW EXECUTE FUNCTION trg_doc_access_changed();

-- A team's membership changed: documents shared with that team.
CREATE OR REPLACE FUNCTION trg_doc_acl_team() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM doc_acl_compile_where(
        'EXISTS (SELECT 1 FROM document_shares s WHERE s.document_id = da.document_id AND s.principal_type = ''team'' AND s.principal_id = $1)
         OR (da.visibility = ''restricted'' AND EXISTS (SELECT 1 FROM matter_grants g WHERE g.matter_id = d.matter_id AND g.principal_type = ''team'' AND g.principal_id = $1))',
        coalesce(NEW.team_id, OLD.team_id));
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS doc_acl_team ON team_members;
CREATE TRIGGER doc_acl_team AFTER INSERT OR UPDATE OR DELETE ON team_members
    FOR EACH ROW EXECUTE FUNCTION trg_doc_acl_team();

-- Who holds walls.manage changed: every private/restricted document (there are few).
CREATE OR REPLACE FUNCTION trg_doc_acl_all() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM doc_acl_compile_where('TRUE', NULL);
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS doc_acl_roles ON member_roles;
CREATE TRIGGER doc_acl_roles AFTER INSERT OR UPDATE OR DELETE ON member_roles
    FOR EACH STATEMENT EXECUTE FUNCTION trg_doc_acl_all();
DROP TRIGGER IF EXISTS doc_acl_role_permissions ON role_permissions;
CREATE TRIGGER doc_acl_role_permissions AFTER INSERT OR UPDATE OR DELETE ON role_permissions
    FOR EACH STATEMENT EXECUTE FUNCTION trg_doc_acl_all();

-- A matter's lead or manage grants changed: its restricted documents.
CREATE OR REPLACE FUNCTION trg_doc_acl_matter() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM doc_acl_compile_where('d.matter_id = $1 AND da.visibility = ''restricted''', coalesce(NEW.matter_id, OLD.matter_id));
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS doc_acl_matter_members ON matter_members;
CREATE TRIGGER doc_acl_matter_members AFTER INSERT OR UPDATE OR DELETE ON matter_members
    FOR EACH ROW EXECUTE FUNCTION trg_doc_acl_matter();
DROP TRIGGER IF EXISTS doc_acl_matter_grants ON matter_grants;
CREATE TRIGGER doc_acl_matter_grants AFTER INSERT OR UPDATE OR DELETE ON matter_grants
    FOR EACH ROW EXECUTE FUNCTION trg_doc_acl_matter();

-- New chunks inherit their document's list (a new version of a private document stays private).
CREATE OR REPLACE FUNCTION trg_chunk_visible_to() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    SELECT visible_to INTO NEW.visible_to FROM documents WHERE document_id = NEW.document_id;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS chunk_visible_to ON chunks;
CREATE TRIGGER chunk_visible_to BEFORE INSERT ON chunks
    FOR EACH ROW EXECUTE FUNCTION trg_chunk_visible_to();

-- ── lapsed staffing: an ended assignment no longer counts as the matter team ──
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
          AND (mm.ended_at IS NULL OR mm.ended_at >= current_date)
          AND (mm.started_at IS NULL OR mm.started_at <= current_date)
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
        compiled_at = EXCLUDED.compiled_at
    WHERE permissions.restricted IS DISTINCT FROM EXCLUDED.restricted
       OR permissions.allowed_members IS DISTINCT FROM EXCLUDED.allowed_members
       OR permissions.denied_members IS DISTINCT FROM EXCLUDED.denied_members;
END $$;

-- Matters whose compiled list is out of date because time passed (an assignment ended or
-- started, a grant expired): the app's refresher calls this every few minutes.
CREATE OR REPLACE FUNCTION acl_refresh_lapsed() RETURNS INTEGER LANGUAGE plpgsql AS $$
DECLARE
    r RECORD;
    n INTEGER := 0;
BEGIN
    FOR r IN
        SELECT DISTINCT p.matter_id FROM permissions p
        WHERE EXISTS (SELECT 1 FROM matter_members mm WHERE mm.matter_id = p.matter_id
                        AND (mm.ended_at < current_date OR mm.started_at > current_date)
                        AND mm.member_id = ANY (p.allowed_members))
           OR EXISTS (SELECT 1 FROM matter_grants g WHERE g.matter_id = p.matter_id AND g.expires_at <= now())
    LOOP
        PERFORM acl_compile_matter(r.matter_id);
        n := n + 1;
    END LOOP;
    PERFORM doc_acl_compile_where(
        'EXISTS (SELECT 1 FROM matter_members mm WHERE mm.matter_id = d.matter_id AND mm.ended_at < current_date AND mm.member_id = ANY (d.visible_to))
         OR EXISTS (SELECT 1 FROM matter_grants g WHERE g.matter_id = d.matter_id AND g.expires_at <= now())', NULL);
    RETURN n;
END $$;
