# Feature: Document Library & Folders — Firm Precedent Vault

**Sprint:** 12  
**Priority:** P2  
**Mike observation (product level):** Legal platforms provide a library area separate from matter-specific folders, where a firm stores and organises reusable precedents, standard templates, and research memos that are not tied to a single client engagement.  
**Mike source used as coding basis:** NO  
**Date:** 2026-08-28

---

## Problem

Currently documents are only accessible through matter context (`matter_id`). The firm has a Knowledge Vault view in the UI but it reads from static `firm_core_data.js`. There is no concept of firm-wide precedent documents that can be browsed, tagged, and retrieved without knowing which matter they came from.

---

## User need

A junior lawyer needs to find the firm's standard non-compete clause. They don't know which matter originated it. They should be able to browse the Knowledge Vault, search by practice area and document type, and find the precedent directly — without going through a matter.

---

## Requirements

1. A `library_folders` concept: folders that can contain documents from multiple matters, or serve as a firm-level tag
2. `GET /library` — returns top-level folders: `Precedents`, `Standard Clauses`, `Research Memos`, `Templates`
3. `GET /library/{folder_id}/documents` — documents in a folder (paginated)
4. `POST /library/folders` — create a new folder
5. `POST /library/{folder_id}/documents` — add a `document_id` to a folder (by reference, not copy — the document record stays in its matter)
6. `GET /library/search` — full-text search across all library-tagged documents
7. ACL: a document added to a library folder must still pass ACL for the requesting `member_id` — if the source matter is restricted and the member is not in `allowed_members`, the document is not returned
8. UI: Library view with folder tree, document list, and a direct Ask input scoped to the folder ("Ask about documents in Precedents")

---

## Our independent design decisions

**Implementation:** Library folders are metadata overlay on top of existing documents — no document content is duplicated.

**Schema:**
```sql
CREATE TABLE library_folders (
    folder_id TEXT PRIMARY KEY,
    parent_folder_id TEXT REFERENCES library_folders(folder_id),
    name TEXT NOT NULL,
    description TEXT,
    created_by TEXT REFERENCES members(member_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE library_items (
    item_id TEXT PRIMARY KEY,
    folder_id TEXT NOT NULL REFERENCES library_folders(folder_id),
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    added_by TEXT REFERENCES members(member_id),
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (folder_id, document_id)
);

CREATE INDEX idx_lib_items_folder ON library_items (folder_id);
CREATE INDEX idx_lib_items_doc ON library_items (document_id);
```

**Seeded folders on first run:**
- `LF-001` — Precedents (all documents tagged as `precedent` document type)
- `LF-002` — Standard Clauses (documents containing "standard clause" in title)
- `LF-003` — Research Memos (document_type = 'Research Memo')
- `LF-004` — Argument Bank (all `arguments` table entries linked to their source documents)

**Library-scoped retrieval:** `POST /retrieve` gains an optional `library_folder_id` param. When set, retrieval is restricted to documents in that folder (joined through `library_items`). ACL still applies.

**Argument Bank fix:** The `arguments` table has zero retrieval recall. The Library feature is the vehicle to fix this: an `Argument Bank` folder aggregates arguments by practice area, and a new `argument_search` function queries the `arguments` table directly by `issue` and `position` text. This fixes the argument_retrieval eval type (currently 0.0).

---

## Files affected

- `app/api/main.py` — 5 new library routes
- `app/retrieval/engine.py` — library_folder_id filter
- New module: `app/retrieval/argument_search.py` — argument table search
- Migration: `20260828_05_library.sql`
- `static/app.js` — Library/Knowledge Vault view rewrite (replace static data)

---

## PM Gate

**Status:** PENDING

- [ ] Feature doc written ✓
- [ ] IP_ORIGIN_RECORD entry required (Mike-inspired — library concept)
- [ ] Schema independently designed ✓
- [ ] ACL respected through library lookup ✓
- [ ] Argument retrieval fix scoped here — eval target: argument_retrieval Recall@10 > 0.5
- [ ] Test plan: add document to folder, retrieve via library scope, assert only folder docs returned; assert ACL still blocks restricted docs
