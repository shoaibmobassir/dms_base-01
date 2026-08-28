# Feature: Conversation History — Persistent Session Log

**Sprint:** 10  
**Priority:** P1  
**Mike observation (product level):** Legal AI platforms keep a history of past AI conversations so lawyers can return to research done days ago without repeating queries.  
**Mike source used as coding basis:** NO  
**Date:** 2026-08-28

---

## Problem

All current session state is lost on page reload. Lawyers frequently revisit questions they asked about a matter earlier. Without persistence, every session starts cold.

---

## User problem

A lawyer asks ten questions about a client acquisition. They close the browser. Next morning they need to see what the AI said about one specific clause. Without history they have to ask again, and may get a different answer from cached retrieval.

---

## Requirements

1. Every `POST /ask` call is persisted server-side linked to a `(session_token, member_id)` pair
2. `GET /history` returns the last 50 conversations for the current member, ordered by recency
3. `GET /history/{conversation_id}` returns the full conversation (query, answer, citations, understanding, hits)
4. `DELETE /history/{conversation_id}` deletes a single conversation
5. History view in the left sidebar shows conversation list — click to re-open a past result in the Ask view
6. Session token is a browser-generated UUID stored in `localStorage`, passed as `X-Session-Id` header. No login required for Sprint 10 (auth hardens this in Sprint 12).

---

## Our independent design decisions

**Schema — new table:**
```sql
CREATE TABLE conversations (
    conversation_id TEXT PRIMARY KEY,
    session_token TEXT NOT NULL,
    member_id TEXT,
    query TEXT NOT NULL,
    answer TEXT,
    citations TEXT[] NOT NULL DEFAULT '{}',
    abstained BOOLEAN NOT NULL DEFAULT FALSE,
    reason TEXT,
    provider TEXT,
    hits JSONB,
    understanding JSONB,
    latency_ms JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_conv_session ON conversations (session_token, created_at DESC);
CREATE INDEX idx_conv_member ON conversations (member_id, created_at DESC);
```

**API:**
- `GET /history?limit=50` — reads from `conversations` filtered by `X-Session-Id` header
- `GET /history/{conversation_id}` — single conversation
- `DELETE /history/{conversation_id}` — soft-deletes (adds `deleted_at` column)

**Privacy:** Conversations are session-scoped. A `member_id` query filters by member when present. No member can see another member's history. In Sprint 12, auth hardens this — `member_id` comes from the validated API key, not a trusted header.

**UI — History sidebar section:**
```
HISTORY
  • What is the position in MTR-2021-0...   2h ago
  • Which lawyers handled arbitration...    Yesterday
  • Have we dealt with non-compete...       3 days ago
```

Each item click loads the conversation into the Ask view as a read-only replay. A `[Re-run]` button re-executes the query live.

---

## Files affected

- `app/db/schema.sql` — add `conversations` table
- New migration: `20260828_01_conversations.sql`
- `app/api/main.py` — 3 new routes
- New module: `app/history/store.py` — save and retrieve conversations
- `static/app.js` — History view, session token management

---

## PM Gate

**Status:** PENDING

- [ ] Feature doc written ✓
- [ ] Schema designed ✓ (our own table structure, not Mike's)
- [ ] Privacy model defined ✓
- [ ] No IP concern — conversation storage is a generic pattern
- [ ] Test plan: save a conversation, retrieve it, assert fields match
- [ ] Retrieval eval: no regression (this feature does not touch retrieval)
