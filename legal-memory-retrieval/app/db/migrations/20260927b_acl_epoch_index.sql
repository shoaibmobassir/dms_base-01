-- max(compiled_at) is read on every retrieval as the ACL cache epoch (app/api/acl.py).
CREATE INDEX IF NOT EXISTS idx_permissions_compiled_at ON permissions (compiled_at);
