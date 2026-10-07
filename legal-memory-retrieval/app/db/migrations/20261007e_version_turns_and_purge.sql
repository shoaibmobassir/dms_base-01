-- Versions (plan 22, W2a). Safe to re-run.
--
--   source_turn_id   the Assistant message whose accepted edits made this version. While it is still the newest
--                    version, by the same person, with nothing attached to it, more edits accepted from that same
--                    message amend it, so one Assistant turn makes one version (W-R9).
--   deleted_at/_by, delete_reason
--                    the version's file was purged (e.g. on a client instruction). The row stays in the history as
--                    "deleted — cannot be restored"; its text, file and index are gone (W-R8).
-- ``origin`` gains 'assistant' (accepted Assistant edits) and 'copy' (a copy of another document).

ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS source_turn_id TEXT;
ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS deleted_by TEXT;
ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS delete_reason TEXT;
