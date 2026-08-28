# Feature: Document Review — Clause-Level Edit Suggestions

**Sprint:** 11  
**Priority:** P2  
**Mike observation (product level):** Legal AI platforms can read a document and surface specific clause-level issues and proposed redlines that the user can accept or reject, turning first-pass review from blank-page reading into a decision queue.  
**Mike source used as coding basis:** NO  
**Date:** 2026-08-28

---

## Problem

A lawyer receives a 40-clause NDA from a counterparty. They need to identify which clauses are non-standard or risky, and propose amendments. Currently they read the whole document manually or use the Ask AI with free-form questions. There is no structured "review this document" flow that produces an actionable, clause-by-clause result.

---

## User need

A lawyer selects a document from a matter, triggers a review, and receives a list of flagged clauses — each with: what the issue is, the current clause text, a suggested redline, and the supporting precedent or firm standard from the institutional memory. They accept or reject each suggestion. The output is a tracked-changes memo.

---

## Requirements

1. `POST /documents/{document_id}/review` — starts a review run for a document
2. Review engine chunks the document, retrieves firm precedents for each clause type, generates a suggestion list
3. Each suggestion: `clause_label`, `issue_description`, `original_text`, `suggested_text`, `supporting_doc_ids` (from retrieval)
4. `GET /documents/{document_id}/reviews` — list review runs for a document
5. `GET /reviews/{review_id}` — full review result with all suggestions
6. `PATCH /reviews/{review_id}/suggestions/{suggestion_id}` — mark as accepted/rejected
7. `GET /reviews/{review_id}/memo` — export accepted suggestions as a structured memo (plain text)
8. Review view in UI: two-column layout — original clause left, suggestion right, accept/reject buttons

---

## Our independent design decisions

**Review engine architecture:**
1. Load document chunks for `document_id` from `chunks` table
2. For each chunk, call `understand(chunk_text)` to detect clause type / practice area
3. Retrieve firm precedents: `POST /retrieve` with `query = "{clause_type} standard clause"`, `member_id = reviewer`
4. Call LLM (same provider chain as `/ask`) with system: "You are a contract reviewer for Apex Chambers. Review this clause against the provided firm precedents. Identify issues and propose redline language. Respond with JSON: `{issue, suggested_text, confidence}`"
5. Store all suggestions in `review_suggestions` table with `supporting_doc_ids` filtered to retrieved hits

**Schema:**
```sql
CREATE TABLE document_reviews (
    review_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    member_id TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE review_suggestions (
    suggestion_id TEXT PRIMARY KEY,
    review_id TEXT NOT NULL REFERENCES document_reviews(review_id),
    chunk_id TEXT REFERENCES chunks(chunk_id),
    clause_label TEXT,
    issue_description TEXT,
    original_text TEXT,
    suggested_text TEXT,
    supporting_doc_ids TEXT[] NOT NULL DEFAULT '{}',
    confidence FLOAT,
    decision TEXT   -- NULL | 'accepted' | 'rejected'
);
```

**Citation integrity:** `supporting_doc_ids` is populated from `filter_citations(retrieved_ids, hits)` — same function as `/ask`. Suggestions without supporting precedents have `supporting_doc_ids = []` and are flagged as `confidence < 0.5`.

**UI layout:**
```
Document: Share Purchase Agreement v3 (DOC-00122)
[Run Review]                              Status: Complete — 8 suggestions

┌─────────────────────────────┬────────────────────────────────────────┐
│ Clause 4.2 — Indemnification│ SUGGESTED REDLINE                      │
│ Original: "...unlimited      │ "...liability capped at the purchase    │
│ liability for..."            │ price paid under this Agreement..."     │
│                              │ Based on: [DOC-00451] [DOC-00789]      │
│                              │ [Accept ✓]  [Reject ✗]                 │
├─────────────────────────────┼────────────────────────────────────────┤
│ Clause 7.1 — Governing Law  │ No suggestion — matches firm standard. │
│ "...governed by laws of...   │ Supported by: [DOC-00122]              │
│                              │ [No action needed]                      │
└─────────────────────────────┴────────────────────────────────────────┘
[Export accepted redlines as memo]
```

---

## Files affected

- `app/api/main.py` — 4 new routes
- New module: `app/review/engine.py`
- Migration: `20260828_04_document_reviews.sql`
- `static/app.js` — Document Review view, two-column layout

---

## PM Gate

**Status:** PENDING

- [ ] Feature doc written ✓
- [ ] IP_ORIGIN_RECORD entry required (Mike-inspired — document review with suggestions)
- [ ] Citation integrity reuses `filter_citations` — no new hallucination risk ✓
- [ ] Schema independently designed ✓
- [ ] No new LLM dependency — extends existing provider chain ✓
- [ ] Test plan: review a short test document, assert at least one suggestion produced with non-empty supporting_doc_ids
