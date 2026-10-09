-- 20261007a replaced doc_acl_compile without the archive rule of 20261003d (an archived document is visible
-- to nobody). This restores it. Safe to re-run.

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

    IF v_kind = 'matter' AND NOT has_a THEN
        v_list := NULL;
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
        -- Project / library home: the home's readers (or, if made private, its owner), plus explicit shares,
        -- plus walls.manage holders (reads by them are audited by the application).
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

-- Archived documents compiled while the rule was missing.
DO $$ DECLARE r RECORD; BEGIN
    FOR r IN SELECT document_id FROM documents WHERE archived_at IS NOT NULL AND visible_to IS DISTINCT FROM ARRAY[]::TEXT[] LOOP
        PERFORM doc_acl_compile(r.document_id);
    END LOOP;
END $$;
