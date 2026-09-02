# IP Origin Record

This document records the provenance of significant features in the
`legal-memory-retrieval` system, particularly any feature where Mike
(AGPLv3) was consulted as product research.

Its purpose is to maintain a clear development history demonstrating that our
implementation was independently designed from requirements — not derived from
Mike's source code.

**This record is not a legal guarantee. Obtain qualified counsel review before
commercial launch of any product closely inspired by an AGPL project.**

---

## How to add an entry

When implementing a feature that was inspired (at the product level) by Mike,
copy the template below, fill it in, and append it to this file **before**
writing the implementation code.

```
### Feature: [name]
Date: YYYY-MM-DD
Mike observation (product level only): [what you saw at the UI/product level]
Requirement (technology-independent): [plain-English user story]
Our design decisions: [our schema/API/component choices — independently made]
Mike source used as coding basis: NO
New dependencies introduced: [package — license]
IP notes: [any uncertainty → escalated to: name/date]
```

---

## Entries

### Feature: Hybrid retrieval pipeline (BM25 + vector + metadata + graph)
Date: 2026-08-23
Mike observation (product level only): Legal AI products benefit from combining keyword and semantic search over matter documents.
Requirement (technology-independent): Given a natural-language query and a member identity, retrieve the most relevant document chunks from a corpus of 38,000+ legal documents, respecting per-matter access controls, using multiple complementary search strategies fused by relevance rank.
Our design decisions:
  - Four independent channels: Postgres FTS (BM25-equivalent), pgvector HNSW cosine ANN, ILIKE metadata search, SQL relationship graph traversal
  - Weighted Reciprocal Rank Fusion (k=60) with intent-adaptive weights
  - Cross-encoder rerank (ms-marco-MiniLM-L-6-v2) blended 55% CE / 45% RRF
  - ACL enforced as SQL WHERE clause per channel before any ranking
  - All names, schemas, and algorithms chosen independently
Mike source used as coding basis: NO
New dependencies introduced: sentence-transformers (Apache-2.0), pgvector (MIT), cross-encoder via sentence-transformers
IP notes: None

### Feature: Matter graph / relationship-aware retrieval
Date: 2026-08-23
Mike observation (product level only): Legal matters have relationships to other matters (same client, follow-up, related dispute). Surfacing related matters improves research quality.
Requirement (technology-independent): Given a seed matter ID, traverse the firm's matter relationship graph to find related matters across different clients where the same lead lawyer worked, then return ACL-filtered documents from those related matters.
Our design decisions:
  - `relationships` table with source_id, rel_type, target_id (TEXT, no FK constraint to allow cross-entity edges)
  - SQL graph traversal using CTEs, not a graph database
  - Lead role matching on `matter_members.role_on_matter IN ('Lead', 'Partner')`
  - Graph channel weight boosted to 2.5 for `graph_reasoning` intent
Mike source used as coding basis: NO
New dependencies introduced: None (pure SQL)
IP notes: None

### Feature: Permission-aware retrieval (ACL before ranking)
Date: 2026-08-23
Mike observation (product level only): Documents in a law firm have confidentiality classifications; some matters are restricted to specific team members.
Requirement (technology-independent): Every retrieval query must enforce matter-level access control before any document is ranked or returned. A member who lacks access to a restricted matter must never see that matter's documents in results, answers, or citations.
Our design decisions:
  - `permissions` table: matter_id, restricted (bool), allowed_members (text[])
  - ACL enforced as a SQL WHERE predicate on every channel independently
  - member_id=NULL treated as admin bypass (no results hidden)
  - Named matter/document lookup abstains if the entity is not in ACL-filtered results
Mike source used as coding basis: NO
New dependencies introduced: None
IP notes: None

### Feature: Answer engine with citations and abstention
Date: 2026-08-24
Mike observation (product level only): Legal AI assistants should answer questions with source citations and refuse to answer when evidence is insufficient.
Requirement (technology-independent): After retrieval, generate an answer that: (a) is grounded only in retrieved document excerpts, (b) cites specific document IDs, (c) abstains with a reason when no evidence supports an answer, (d) never invents document IDs not in the retrieved set.
Our design decisions:
  - Extractive fallback: returns top-3 document snippets without an LLM
  - LLM path: Groq (llama3-70b-8192) → Gemini (gemini-1.5-flash) → extractive fallback
  - JSON-mode, temperature=0
  - `filter_citations`: enforces cited ⊆ retrieved_doc_ids
  - `_blocked_matter_or_doc`: abstains if named entity absent from ACL-filtered hits
  - System prompt independently authored ("Ask the Firm for Apex Chambers")
Mike source used as coding basis: NO
New dependencies introduced: httpx (BSD-3-Clause)
IP notes: None

### Feature: Redis retrieval cache + per-stage latency logging
Date: 2026-08-27
Mike observation (product level only): Production legal AI systems need sub-2-second response times and should cache repeated queries.
Requirement (technology-independent): Cache retrieval results keyed on (query, member_id, channel_list, corpus_version) with a configurable TTL. Log wall-clock latency for every pipeline stage (understand, keyword, metadata, vector, graph, fusion, rerank, llm) and return it in the API response.
Our design decisions:
  - SHA-256 key hash of JSON-serialised cache params
  - `redis.setex` with `cache_ttl_seconds` (default 300s)
  - Graceful degradation: if Redis is unavailable, cache is silently bypassed
  - `latency_ms` dict returned in every `/retrieve` and `/ask` response
Mike source used as coding basis: NO
New dependencies introduced: redis 8.x (MIT)
IP notes: None

### Feature: API key authentication layer
Date: 2026-08-27
Mike observation (product level only): Multi-user legal platforms require per-user authentication so ACL enforcement is trustworthy.
Requirement (technology-independent): Validate caller identity from an HTTP header (X-Api-Key) before trusting the claimed member_id. In dev mode (AUTH_ENABLED=false), trust X-Member-Id header directly. In production mode, validate against a hashed keystore in Postgres; reject mismatched identity claims with 401/403.
Our design decisions:
  - SHA-256 key hashing (no plaintext key storage)
  - `api_keys` table: member_id, key_hash, created_at — independently designed schema
  - FastAPI `Depends(resolve_member)` pattern
  - member_id removed from request body entirely (resolved from headers only)
  - `scripts/issue_keys.py` generates one key per corpus member
Mike source used as coding basis: NO
New dependencies introduced: python-jose (MIT), passlib (BSD-3-Clause)
IP notes: None

### Feature: Multi-Project & Workstream Management Architecture
Date: 2026-08-28
Mike observation (product level only): Legal matters in large firms decompose into multi-disciplinary project workstreams (e.g. Legal DD, Tax Review, SPA Drafting, Regulatory Clearance, Closing).
Requirement (technology-independent): Allow users to create, organize, staff, and track multiple discrete projects across the firm and within individual matters, attaching deliverables, documents, milestones, and practice teams.
Our design decisions:
  - Independent `projects` object structure linking project_id, matter_id, client_id, team, lead, milestones, deadline, and documents
  - Top-level `Projects` workspace with multi-status filtering (Planning, In Progress, Diligence, Review, Closing, Completed) and instant project creation modal
  - Multi-team matrix view allowing projects to span Corporate, Tax, Disputes, Regulatory, and Banking teams without a rigid hierarchy
  - Apple/Porsche-grade luxury minimalist UI styling with monochromatic precision, frosted glass header blurs, and tactile micro-interactions
Mike source used as coding basis: NO
New dependencies introduced: None
IP notes: None

### Feature: Project workspace — folders, versioning UI, activity timeline
Date: 2026-09-01
Mike observation (product level only): Legal project workspaces organize matter documents in nested folders, track immutable document versions with diff/history, and maintain an audit trail of folder and document changes.
Requirement (technology-independent): Users working on a project must browse a folder tree, assign and move documents, inspect version history with integrity hashes, compare revisions, and review a chronological activity feed — all ACL-scoped to the parent matter.
Our design decisions:
  - Three-tab project workspace in LEXOS SPA: Overview | Documents | Activity
  - Folder tree sidebar backed by `GET /projects/{id}/directory` with create/delete/move via existing REST endpoints
  - Document table with per-row folder selector and version chip opening immutable history from `GET /documents/{id}/versions` + unified diff
  - Activity timeline from `GET /projects/{id}/activity` with human-readable action labels
  - Export manifest download via `GET /projects/{id}/export`
  - Vanilla JS + CSS grid layout — no Mike components, names, or file structure copied
Mike source used as coding basis: NO
New dependencies introduced: None
IP notes: None
