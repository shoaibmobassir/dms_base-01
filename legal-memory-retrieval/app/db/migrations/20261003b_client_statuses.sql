-- A client can be put on hold or made inactive (after its matters are done). Safe to re-run.
ALTER TABLE clients DROP CONSTRAINT IF EXISTS clients_status_check;
ALTER TABLE clients ADD CONSTRAINT clients_status_check
    CHECK (status IN ('prospective', 'active', 'on_hold', 'inactive', 'declined'));
