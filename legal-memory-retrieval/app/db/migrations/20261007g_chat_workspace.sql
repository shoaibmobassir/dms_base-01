-- A conversation can belong to a workspace (plan 22, W3): the workbench's Assistant for a matter, project or library.
-- Its tools then search that workspace's own documents too. Safe to re-run.
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS workspace_kind TEXT
    CHECK (workspace_kind IS NULL OR workspace_kind IN ('matter', 'project', 'library'));
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS workspace_id TEXT;
CREATE INDEX IF NOT EXISTS idx_chat_sessions_workspace ON chat_sessions (member_id, workspace_kind, workspace_id)
    WHERE workspace_kind IS NOT NULL;
