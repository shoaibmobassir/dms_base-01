-- The firm template library is a workspace too (plan 22, W6.2): its layout is saved like the others.
-- 20261007d allowed only matter, project and library scopes, so saving the templates layout failed. Safe to re-run.

ALTER TABLE workbench_state DROP CONSTRAINT IF EXISTS workbench_state_scope_key_check;
ALTER TABLE workbench_state ADD CONSTRAINT workbench_state_scope_key_check
    CHECK (scope_key ~ '^(matter|project|library|firm):[A-Za-z0-9_.-]{1,80}$');
