-- Workspaces: matters, projects and personal libraries over single-copy documents (plan 22, W0).
--
-- A document is stored once and has exactly one HOME, which governs who may read it:
--   matter    documents.matter_id (unchanged: the matter ACL, narrowed by document privacy)
--   project   documents.home_id = projects.project_id (the project's members, by role)
--   library   documents.home_id = members.member_id (the owner)
-- Other workspaces show the document through `document_links`. A link never widens access: a member sees a
-- linked document only if its home lets them read it.
--
-- For project and library homes the reader list is compiled into the existing `visible_to` (documents and
-- chunks), never NULL: an empty list means nobody. Matter-homed documents compile exactly as before (NULL =
-- follows the matter). Project and library documents have matter_id NULL, so every firm-wide read (which joins
-- the matter's compiled permissions) leaves them out: they never reach firm search, Ask the Firm or lists.
--
-- Stored bytes are de-duplicated by content hash (`blobs`); a version still records its own storage_uri.
-- Safe to re-run.

SET lock_timeout = '10s';

-- ── documents: home + provenance ──────────────────────────────────────────────
ALTER TABLE documents ALTER COLUMN matter_id DROP NOT NULL;
ALTER TABLE chunks ALTER COLUMN matter_id DROP NOT NULL;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS home_kind TEXT NOT NULL DEFAULT 'matter';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS home_id TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS derived_from_document_id TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS derived_from_version_id TEXT;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'documents_home_check') THEN
        ALTER TABLE documents ADD CONSTRAINT documents_home_check CHECK (
            (home_kind = 'matter' AND matter_id IS NOT NULL AND home_id IS NULL)
            OR (home_kind IN ('project', 'library') AND matter_id IS NULL AND home_id IS NOT NULL)
        ) NOT VALID;
        ALTER TABLE documents VALIDATE CONSTRAINT documents_home_check;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_docs_home ON documents (home_kind, home_id) WHERE home_kind <> 'matter';
CREATE INDEX IF NOT EXISTS idx_docs_sha ON documents (content_sha256) WHERE content_sha256 IS NOT NULL;

-- ── projects: standalone workspaces anyone can create ────────────────────────
ALTER TABLE projects ALTER COLUMN matter_id DROP NOT NULL;
ALTER TABLE projects ALTER COLUMN practice_team DROP NOT NULL;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS owner_member_id TEXT REFERENCES members (member_id);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE projects ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE projects ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS row_version INTEGER NOT NULL DEFAULT 1;
-- A project outlives the matter it was linked to.
ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_matter_id_fkey;
ALTER TABLE projects ADD CONSTRAINT projects_matter_id_fkey
    FOREIGN KEY (matter_id) REFERENCES matters (matter_id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects (owner_member_id);
CREATE SEQUENCE IF NOT EXISTS project_id_seq;

CREATE TABLE IF NOT EXISTS project_members (
    project_id     TEXT NOT NULL REFERENCES projects (project_id) ON DELETE CASCADE,
    principal_type TEXT NOT NULL CHECK (principal_type IN ('member', 'team')),
    principal_id   TEXT NOT NULL,
    role           TEXT NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
    added_by       TEXT,
    added_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, principal_type, principal_id)
);
CREATE INDEX IF NOT EXISTS idx_project_members_principal ON project_members (principal_type, principal_id);

-- Old seed folders whose project rows no longer exist (the projects table is empty).
DELETE FROM project_folders f WHERE NOT EXISTS (SELECT 1 FROM projects p WHERE p.project_id = f.project_id);

-- ── folders, links, tags, blobs ──────────────────────────────────────────────
-- Folders are paths (documents.folder_path / document_links.folder_path); this table keeps empty folders.
CREATE TABLE IF NOT EXISTS workspace_folders (
    container_kind TEXT NOT NULL CHECK (container_kind IN ('matter', 'project', 'library')),
    container_id   TEXT NOT NULL,
    path           TEXT NOT NULL CHECK (path <> '' AND path !~ '(^/|/$|//)'),
    created_by     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (container_kind, container_id, path)
);

CREATE TABLE IF NOT EXISTS document_links (
    link_id        BIGSERIAL PRIMARY KEY,
    document_id    TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    container_kind TEXT NOT NULL CHECK (container_kind IN ('matter', 'project', 'library')),
    container_id   TEXT NOT NULL,
    folder_path    TEXT NOT NULL DEFAULT '',
    added_by       TEXT,
    added_via      TEXT NOT NULL DEFAULT 'link' CHECK (added_via IN ('link', 'upload', 'file_into', 'assistant', 'import')),
    added_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, container_kind, container_id)
);
CREATE INDEX IF NOT EXISTS idx_document_links_container ON document_links (container_kind, container_id);

-- People's own tags. Tags that come from where a document lives (workspace, folder, client, type) are derived
-- when read, so they follow links, moves and filing without a sync step.
CREATE TABLE IF NOT EXISTS document_tags (
    document_id TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    tag         TEXT NOT NULL CHECK (char_length(tag) BETWEEN 1 AND 60 AND tag = lower(tag) AND tag !~ ':'),
    created_by  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_document_tags_tag ON document_tags (tag);

CREATE TABLE IF NOT EXISTS blobs (
    content_sha256 TEXT PRIMARY KEY,
    storage_uri    TEXT NOT NULL,
    byte_size      BIGINT,
    mime_type      TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── uploads carry their workspace ────────────────────────────────────────────
ALTER TABLE upload_batches ALTER COLUMN matter_id DROP NOT NULL;
ALTER TABLE upload_batches ADD COLUMN IF NOT EXISTS container_kind TEXT NOT NULL DEFAULT 'matter';
ALTER TABLE upload_batches ADD COLUMN IF NOT EXISTS container_id TEXT;
ALTER TABLE upload_batches ADD COLUMN IF NOT EXISTS folder_prefix TEXT NOT NULL DEFAULT '';
UPDATE upload_batches SET container_id = matter_id WHERE container_id IS NULL AND container_kind = 'matter';

-- ── compile one document's reader list ───────────────────────────────────────
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

-- Every project/library document of one home.
CREATE OR REPLACE FUNCTION doc_acl_compile_home(p_kind TEXT, p_id TEXT) RETURNS INTEGER LANGUAGE plpgsql AS $$
DECLARE
    r RECORD;
    n INTEGER := 0;
BEGIN
    FOR r IN SELECT document_id FROM documents WHERE home_kind = p_kind AND home_id = p_id LOOP
        PERFORM doc_acl_compile(r.document_id);
        n := n + 1;
    END LOOP;
    RETURN n;
END $$;

-- Every project/library document (few compared with the firm corpus).
CREATE OR REPLACE FUNCTION doc_acl_compile_homes() RETURNS INTEGER LANGUAGE plpgsql AS $$
DECLARE
    r RECORD;
    n INTEGER := 0;
BEGIN
    FOR r IN SELECT document_id FROM documents WHERE home_kind <> 'matter' LOOP
        PERFORM doc_acl_compile(r.document_id);
        n := n + 1;
    END LOOP;
    RETURN n;
END $$;

-- ── triggers ─────────────────────────────────────────────────────────────────
-- A new project/library document, or a document whose home changed (moved into a project, filed into a matter).
CREATE OR REPLACE FUNCTION trg_doc_home_changed() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM doc_acl_compile(NEW.document_id);
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS doc_home_inserted ON documents;
CREATE TRIGGER doc_home_inserted AFTER INSERT ON documents
    FOR EACH ROW WHEN (NEW.home_kind <> 'matter') EXECUTE FUNCTION trg_doc_home_changed();
DROP TRIGGER IF EXISTS doc_home_changed ON documents;
CREATE TRIGGER doc_home_changed AFTER UPDATE OF home_kind, home_id, matter_id ON documents
    FOR EACH ROW WHEN (OLD.home_kind IS DISTINCT FROM NEW.home_kind OR OLD.home_id IS DISTINCT FROM NEW.home_id
                       OR OLD.matter_id IS DISTINCT FROM NEW.matter_id)
    EXECUTE FUNCTION trg_doc_home_changed();

-- A project's members changed.
CREATE OR REPLACE FUNCTION trg_doc_acl_project() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM doc_acl_compile_home('project', coalesce(NEW.project_id, OLD.project_id));
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS doc_acl_project_members ON project_members;
CREATE TRIGGER doc_acl_project_members AFTER INSERT OR UPDATE OR DELETE ON project_members
    FOR EACH ROW EXECUTE FUNCTION trg_doc_acl_project();

-- A team's membership changed: also project/library documents reached through that team.
CREATE OR REPLACE FUNCTION trg_doc_acl_team() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_team TEXT := coalesce(NEW.team_id, OLD.team_id);
    r RECORD;
BEGIN
    PERFORM doc_acl_compile_where(
        'EXISTS (SELECT 1 FROM document_shares s WHERE s.document_id = da.document_id AND s.principal_type = ''team'' AND s.principal_id = $1)
         OR (da.visibility = ''restricted'' AND EXISTS (SELECT 1 FROM matter_grants g WHERE g.matter_id = d.matter_id AND g.principal_type = ''team'' AND g.principal_id = $1))',
        v_team);
    FOR r IN
        SELECT d.document_id FROM documents d
        WHERE d.home_kind <> 'matter'
          AND (EXISTS (SELECT 1 FROM document_shares s WHERE s.document_id = d.document_id
                         AND s.principal_type = 'team' AND s.principal_id = v_team)
               OR (d.home_kind = 'project' AND EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id = d.home_id
                         AND pm.principal_type = 'team' AND pm.principal_id = v_team)))
    LOOP
        PERFORM doc_acl_compile(r.document_id);
    END LOOP;
    RETURN NULL;
END $$;

-- Who holds walls.manage changed: every private/restricted document and every project/library document.
CREATE OR REPLACE FUNCTION trg_doc_acl_all() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM doc_acl_compile_where('TRUE', NULL);
    PERFORM doc_acl_compile_homes();
    RETURN NULL;
END $$;

RESET lock_timeout;
