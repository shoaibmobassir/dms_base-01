-- Firm sign-in (OIDC) and browser sessions (production plan 08, step C).
-- Only SHA-256 hashes of session and CSRF tokens are stored. Safe to re-run.

-- Pending authorization-code logins: state -> PKCE verifier + nonce, single use, short-lived.
CREATE TABLE IF NOT EXISTS oidc_login_requests (
    state_hash    TEXT PRIMARY KEY,
    code_verifier TEXT NOT NULL,
    nonce         TEXT NOT NULL,
    next_path     TEXT NOT NULL DEFAULT '/ui/',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    session_hash TEXT PRIMARY KEY,
    member_id    TEXT NOT NULL REFERENCES members (member_id) ON DELETE CASCADE,
    csrf_hash    TEXT NOT NULL,
    idp_subject  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    revoked_at   TIMESTAMPTZ,
    ip           TEXT,
    user_agent   TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_member ON auth_sessions (member_id) WHERE revoked_at IS NULL;
