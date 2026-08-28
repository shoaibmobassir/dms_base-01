# Feature: Tabular Review — Bulk Extraction into Table

**Sprint:** 11  
**Priority:** P2  
**Mike observation (product level):** Legal platforms let users apply a structured extraction task to a set of documents and see the results as a comparison table — useful for due diligence when reading many contracts of the same type.  
**Mike source used as coding basis:** NO  
**Date:** 2026-08-28

---

## Problem

When a lawyer does due diligence on 30 contracts, they need to extract the same fields (governing law, limitation of liability cap, termination notice period, etc.) from each one. Doing this manually is slow. The Ask Firm AI can answer one question at a time, but cannot extract the same fields from all 30 documents in a single operation with a tabular output.

---

## User need

A corporate associate selects a set of documents from a matter (e.g. all NDAs in a data room), defines a set of columns to extract (e.g. "Governing Law", "Non-Disclosure Period", "Exceptions"), and gets a table where each row is a document and each column is an extracted value — with the source chunk cited for each cell.

---

## Requirements

1. User selects a set of document IDs from a matter or from search results
2. User defines a column schema: each column has a `label` and an `extraction_query` (e.g. "What is the governing law clause?")
3. System runs extraction: for each `(document_id, column)` pair, calls `POST /ask` scoped to that document, extracts the answer
4. Results displayed as a table: rows = documents, columns = user-defined fields, cells = extracted values with citation chip
5. Cells where the model abstained show "—" with a light tooltip "Not found in document"
6. Table is exportable as CSV
7. Run is persisted to `tabular_runs` table and viewable in a history list

---

## Our independent design decisions

**Extraction is document-scoped:** Each cell is a dedicated `/ask` call with `member_id` ACL, and a modified query: `"[column.extraction_query] in document [document_id]"`. The retrieval is filtered to `matter_id` + `document_id` via a new `document_filter` parameter added to `RetrieveRequest`.

**Schema:**
```sql
CREATE TABLE tabular_runs (
    run_id TEXT PRIMARY KEY,
    member_id TEXT,
    session_token TEXT,
    title TEXT,
    document_ids TEXT[] NOT NULL DEFAULT '{}',
    columns JSONB NOT NULL DEFAULT '[]',
    cells JSONB NOT NULL DEFAULT '{}',   -- {"DOC-00122": {"Governing Law": {answer, citation, abstained}}}
    status TEXT NOT NULL DEFAULT 'running',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
```

**API:**
- `POST /tabular/run` — start a run (async, queued)
- `GET /tabular/{run_id}` — poll status and results
- `GET /tabular/{run_id}/csv` — export as CSV

**Extraction is sequential per document, not parallel** in Sprint 11 (no job queue yet). A run of 10 docs × 5 columns = 50 sequential asks. With the Redis cache, repeated queries for the same document should hit cache.

**UI layout:**
```
Documents selected: 12      Columns: 5
[+ Add column]              [Run extraction]  [Export CSV]

┌──────────────────┬────────────────┬──────────────┬───────────────┐
│ Document         │ Governing Law  │ Notice Period│ Liability Cap │
├──────────────────┼────────────────┼──────────────┼───────────────┤
│ DOC-00122 (NDA)  │ English Law    │ 30 days      │ —             │
│                  │ [DOC-00122]    │ [DOC-00122]  │               │
├──────────────────┼────────────────┼──────────────┼───────────────┤
│ DOC-00451 (NDA)  │ Indian Law     │ —            │ ₹2 crore      │
│                  │ [DOC-00451]    │              │ [DOC-00451]   │
└──────────────────┴────────────────┴──────────────┴───────────────┘
```

**Document filter in retrieval:** Add `document_ids: list[str] | None = None` to `RetrieveRequest`. When set, all channels apply an additional SQL filter `d.document_id = ANY(%(document_ids)s)`. This scopes retrieval tightly to the selected document set.

---

## Files affected

- `app/api/main.py` — 3 new routes + document_ids filter in RetrieveRequest
- `app/retrieval/engine.py` — pass document_ids filter through to each channel
- `app/retrieval/keyword.py`, `metadata.py`, `semantic.py`, `graph.py` — add document_ids WHERE clause
- New module: `app/tabular/runner.py`
- Migration: `20260828_03_tabular_runs.sql`
- `static/app.js` — Tabular Review view

---

## PM Gate

**Status:** PENDING

- [ ] Feature doc written ✓
- [ ] IP_ORIGIN_RECORD entry required (Mike-inspired — tabular review concept)
- [ ] Independent schema ✓
- [ ] No new LLM dependency — reuses existing answer engine ✓
- [ ] document_ids filter is additive, no retrieval regression risk ✓
- [ ] Test plan: run extraction on 2 docs × 2 columns, assert cells populated and citations valid
