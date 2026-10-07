-- The firm's template and precedent library (plan 22, W6): a fourth home, ``firm`` / ``templates``.
-- Every signed-in member reads its documents (unless one is made private); people with km.publish curate it.
-- They are not part of firm search or Ask the Firm; they are used through "New from template", which copies one into
-- a workspace (the template itself is never edited by drafting). Safe to re-run.

SET lock_timeout = '10s';

ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_home_check;
ALTER TABLE documents ADD CONSTRAINT documents_home_check CHECK (
    (home_kind = 'matter' AND matter_id IS NOT NULL AND home_id IS NULL)
    OR (home_kind IN ('project', 'library') AND matter_id IS NULL AND home_id IS NOT NULL)
    OR (home_kind = 'firm' AND matter_id IS NULL AND home_id = 'templates')
) NOT VALID;
ALTER TABLE documents VALIDATE CONSTRAINT documents_home_check;

ALTER TABLE document_links DROP CONSTRAINT IF EXISTS document_links_container_kind_check;
ALTER TABLE document_links ADD CONSTRAINT document_links_container_kind_check
    CHECK (container_kind IN ('matter', 'project', 'library', 'firm'));
ALTER TABLE workspace_folders DROP CONSTRAINT IF EXISTS workspace_folders_container_kind_check;
ALTER TABLE workspace_folders ADD CONSTRAINT workspace_folders_container_kind_check
    CHECK (container_kind IN ('matter', 'project', 'library', 'firm'));

-- A firm template follows the firm (NULL = every member) unless made private (owner, shares, walls.manage).
CREATE OR REPLACE FUNCTION doc_acl_compile(p_doc TEXT) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
    a        document_access%ROWTYPE;
    has_a    BOOLEAN;
    v_matter TEXT;
    v_kind   TEXT;
    v_home   TEXT;
    v_list   TEXT[];
BEGIN
    SELECT matter_id, home_kind, home_id INTO v_matter, v_kind, v_home FROM documents WHERE document_id = p_doc;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    SELECT * INTO a FROM document_access WHERE document_id = p_doc;
    has_a := FOUND;

    IF v_kind IN ('matter', 'firm') AND NOT has_a THEN
        v_list := NULL;
    ELSIF v_kind = 'firm' THEN
        SELECT array_agg(DISTINCT x ORDER BY x) INTO v_list FROM (
            SELECT a.owner_member_id AS x
            UNION SELECT s.principal_id FROM document_shares s WHERE s.document_id = p_doc AND s.principal_type = 'member'
            UNION SELECT tm.member_id FROM document_shares s JOIN team_members tm ON tm.team_id = s.principal_id
                  WHERE s.document_id = p_doc AND s.principal_type = 'team'
            UNION SELECT mr.member_id FROM member_roles mr JOIN role_permissions rp USING (role_key)
                  WHERE rp.permission IN ('walls.manage', 'km.publish')
        ) q WHERE x IS NOT NULL;
        v_list := coalesce(v_list, '{}');
    ELSIF v_kind = 'matter' THEN
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
    ELSE
        SELECT array_agg(DISTINCT x ORDER BY x) INTO v_list FROM (
            SELECT a.owner_member_id AS x WHERE has_a
            UNION SELECT v_home WHERE v_kind = 'library' AND NOT has_a
            UNION SELECT pm.principal_id FROM project_members pm
                  WHERE v_kind = 'project' AND NOT has_a AND pm.project_id = v_home AND pm.principal_type = 'member'
            UNION SELECT tm.member_id FROM project_members pm JOIN team_members tm ON tm.team_id = pm.principal_id
                  WHERE v_kind = 'project' AND NOT has_a AND pm.project_id = v_home AND pm.principal_type = 'team'
            UNION SELECT s.principal_id FROM document_shares s
                  WHERE s.document_id = p_doc AND s.principal_type = 'member'
            UNION SELECT tm.member_id FROM document_shares s JOIN team_members tm ON tm.team_id = s.principal_id
                  WHERE s.document_id = p_doc AND s.principal_type = 'team'
            UNION SELECT mr.member_id FROM member_roles mr JOIN role_permissions rp USING (role_key)
                  WHERE rp.permission = 'walls.manage'
        ) q WHERE x IS NOT NULL;
        v_list := coalesce(v_list, '{}');
    END IF;
    -- An archived document is visible to nobody (an empty list); restoring recompiles it (20261003d).
    IF EXISTS (SELECT 1 FROM documents WHERE document_id = p_doc AND archived_at IS NOT NULL) THEN
        v_list := ARRAY[]::TEXT[];
    END IF;
    UPDATE documents SET visible_to = v_list WHERE document_id = p_doc AND visible_to IS DISTINCT FROM v_list;
    UPDATE chunks SET visible_to = v_list WHERE document_id = p_doc AND visible_to IS DISTINCT FROM v_list;
    UPDATE doc_acl_state SET changed_at = clock_timestamp();
END $$;

RESET lock_timeout;
