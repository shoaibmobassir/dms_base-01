-- +goose Up

-- =====================================================
-- Migration 003: Documents, Versions, Chunks, Types
-- =====================================================

CREATE TABLE document_types (
    type_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id    UUID NOT NULL REFERENCES firms(firm_id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    color      TEXT DEFAULT '#8b5cf6',
    icon       TEXT DEFAULT 'file',
    sort_order INT DEFAULT 0,
    UNIQUE (firm_id, name)
);

CREATE TABLE documents (
    document_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         UUID NOT NULL REFERENCES firms(firm_id) ON DELETE CASCADE,
    matter_id       UUID REFERENCES matters(matter_id) ON DELETE SET NULL,
    folder_id       UUID REFERENCES matter_folders(folder_id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    filename        TEXT NOT NULL,
    document_type   TEXT,
    tags            TEXT[] DEFAULT '{}',
    custom_metadata JSONB DEFAULT '{}',
    created_by      UUID NOT NULL REFERENCES users(user_id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX idx_documents_firm ON documents(firm_id);
CREATE INDEX idx_documents_matter ON documents(matter_id);
CREATE INDEX idx_documents_tags ON documents USING gin(tags);

CREATE TABLE document_versions (
    version_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id       UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    version_number    INT NOT NULL,
    storage_key       TEXT NOT NULL,
    file_size         BIGINT NOT NULL,
    mime_type         TEXT NOT NULL,
    page_count        INT,
    content_hash      TEXT NOT NULL,
    uploaded_by       UUID NOT NULL REFERENCES users(user_id),
    uploaded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_current        BOOLEAN NOT NULL DEFAULT TRUE,
    processing_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (processing_status IN ('pending', 'processing', 'completed', 'failed')),
    UNIQUE (document_id, version_number)
);

-- =====================================================
-- Migration 003b: Conversations, Messages, Citations
-- =====================================================

CREATE TABLE conversations (
    conversation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         UUID NOT NULL REFERENCES firms(firm_id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    matter_id       UUID REFERENCES matters(matter_id) ON DELETE SET NULL,
    title           TEXT,
    model_id        TEXT DEFAULT 'gemini-2.0-flash',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX idx_conversations_user ON conversations(user_id);
CREATE INDEX idx_conversations_firm ON conversations(firm_id);

CREATE TABLE messages (
    message_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content         TEXT NOT NULL,
    model_used      TEXT,
    tokens_input    INT,
    tokens_output   INT,
    latency_ms      INT,
    abstained       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_messages_conv ON messages(conversation_id, created_at);

-- =====================================================
-- Migration 003c: Audit Log
-- =====================================================

CREATE TABLE audit_log (
    log_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id       UUID NOT NULL,
    user_id       UUID,
    action        TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id   UUID,
    details       JSONB,
    ip_address    INET,
    user_agent    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_firm_date ON audit_log(firm_id, created_at DESC);
CREATE INDEX idx_audit_resource ON audit_log(resource_type, resource_id);

-- =====================================================
-- Migration 003d: User Preferences & Firm Settings
-- =====================================================

CREATE TABLE user_preferences (
    user_id       UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    theme         TEXT NOT NULL DEFAULT 'system' CHECK (theme IN ('light', 'dark', 'system')),
    default_model TEXT DEFAULT 'gemini-2.0-flash',
    sidebar_mode  TEXT NOT NULL DEFAULT 'expanded' CHECK (sidebar_mode IN ('expanded', 'collapsed', 'auto')),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- +goose Down
DROP TABLE IF EXISTS user_preferences;
DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS messages;
DROP TABLE IF EXISTS conversations;
DROP TABLE IF EXISTS document_versions;
DROP TABLE IF EXISTS documents;
DROP TABLE IF EXISTS document_types;
