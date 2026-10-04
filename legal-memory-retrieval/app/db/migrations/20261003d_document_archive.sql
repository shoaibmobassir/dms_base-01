-- Archive a document (plan 09, item 9): soft delete. It stays in the database with its versions and
-- history, but is hidden everywhere (lists, search, retrieval) by compiling an empty visibility list.
-- Only an administrator restores it. Safe to re-run.

ALTER TABLE documents ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS archived_by TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS archive_reason TEXT;

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
    -- An archived document is visible to nobody (an empty list); restoring recompiles it.
    IF EXISTS (SELECT 1 FROM documents WHERE document_id = p_doc AND archived_at IS NOT NULL) THEN
        v_list := ARRAY[]::TEXT[];
    END IF;
    UPDATE documents SET visible_to = v_list WHERE document_id = p_doc AND visible_to IS DISTINCT FROM v_list;
    UPDATE chunks SET visible_to = v_list WHERE document_id = p_doc AND visible_to IS DISTINCT FROM v_list;
    UPDATE doc_acl_state SET changed_at = clock_timestamp();
END $$;

CREATE OR REPLACE FUNCTION trg_doc_archived() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM doc_acl_compile(NEW.document_id);
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS doc_archived ON documents;
CREATE TRIGGER doc_archived AFTER UPDATE OF archived_at ON documents
    FOR EACH ROW WHEN (OLD.archived_at IS DISTINCT FROM NEW.archived_at) EXECUTE FUNCTION trg_doc_archived();
