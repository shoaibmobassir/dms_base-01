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

### Feature: Multi-Model Orchestration & Encrypted Tenant Key Vault
Date: 2026-09-05
Mike observation (product level only): Legal platforms allow law firms to bring their own API keys (OpenAI, Anthropic Claude, Google Gemini, Ollama) and select specific models per reasoning task.
Requirement (technology-independent): Encrypt tenant/user API keys using AES-256-GCM, provide a unified LLM interface with fallback routing, support local Ollama inference, and allow task-level model assignment (chat, tabular, extraction, drafting).
Our design decisions:
  - `key_vault.py` with AES-256-GCM authenticated encryption using PBKDF2 key derivation
  - `model_router.py` unified async caller supporting Anthropic Claude 3.7, OpenAI GPT-4o, Google Gemini 2.0, and local Ollama
  - Per-tenant key resolution and token usage auditing
Mike source used as coding basis: NO
New dependencies introduced: cryptography (Apache-2.0)
IP notes: None

### Feature: High-Throughput Tabular Document Review Engine
Date: 2026-09-05
Mike observation (product level only): Legal teams conducting due diligence need to extract structured criteria (governing law, caps, indemnities, change of control) across batches of documents into a matrix with confidence scores, reasoning traces, citations, and spreadsheet export.
Requirement (technology-independent): Given a set of documents and a column schema with typed extraction prompts, execute scoped hybrid retrieval and LLM structured extraction per cell concurrently, record citations/confidence/reasoning trace, support human review overrides, and export formatted .xlsx/.csv workbooks.
Our design decisions:
  - `tabular_service.py` with async batch execution and concurrency control
  - SQL schema for `tabular_reviews`, `tabular_columns`, `tabular_rows`, and `tabular_cells`
  - Citation chip integration linking directly to retrieved chunk IDs
  - OpenPyXL-based styled `.xlsx` workbook exporter with dedicated evidence/citation sheet
Mike source used as coding basis: NO
New dependencies introduced: openpyxl (MIT)
IP notes: None

### Feature: Reusable Declarative Legal Playbooks & Workflow Engine
Date: 2026-09-05
Mike observation (product level only): Legal practices use standardized checklists and multi-step prompt workflows (e.g. C&D letter drafter, contract triage, MSA review, M&A due diligence).
Requirement (technology-independent): Execute multi-step declarative YAML DAG workflows with typed steps (`retrieve`, `ask`, `verify_citation`, `extract_entities`, `compose`), dynamic Jinja2 template parameter interpolation, precedent integration, and persistent execution history.
Our design decisions:
  - YAML catalog loader in `app/workflows/catalog/`
  - Independent step executor without arbitrary code execution
  - Structured output schemas with markdown and downloadable file generation
Mike source used as coding basis: NO
New dependencies introduced: jinja2 (BSD-3-Clause)
IP notes: None

### Feature: Word DOCX Native Track-Changes Redlining Engine
Date: 2026-09-05
Mike observation (product level only): Legal redlining requires native Microsoft Word tracked revisions (`<w:ins>`, `<w:del>`) rather than static text diffs, so exported files open in Microsoft Word ready for counterparty negotiation.
Requirement (technology-independent): Analyze contract clauses against firm standards, generate structured redline suggestions with risk severity ratings, and produce native Word OpenXML `.docx` files containing tracked changes with attribution and timestamps.
Our design decisions:
  - `docx_redline_generator.py` using `python-docx` + `lxml` to inject `<w:ins>` and `<w:del>` XML nodes
  - Clause deviation classifier rating risk (Low, Medium, High, Critical)
  - Side-by-side and inline visual diff renderer for in-browser review
Mike source used as coding basis: NO
New dependencies introduced: lxml (BSD-3-Clause)
IP notes: None

### Feature: Microsoft Word Taskpane Add-in Integration & Auth Handoff
Date: 2026-09-05
Mike observation (product level only): Lawyers work inside Microsoft Word and need a taskpane add-in to query firm knowledge, draft clauses, and insert redlines directly into the active document.
Requirement (technology-independent): Provide a secure browser-to-Word one-time ticket auth handoff, Office.js taskpane client, selection context analyzer, and 1-click text/track-changes insertion.
Our design decisions:
  - One-time cryptographically random tickets with 5-minute TTL stored in Redis/DB (`app/auth/handoff.py`)
  - Office.js React taskpane UI in `word-addin/`
  - Endpoints for `POST /api/word/analyze-selection` and `POST /api/word/draft-clause`
Mike source used as coding basis: NO
New dependencies introduced: None (Office.js)
IP notes: None

### Feature: Case Law Citation Parsing & CourtListener Judicial Opinion Verification
Date: 2026-09-05
Mike observation (product level only): Legal briefs require verifying case law citations against official reporters and checking whether cited opinions remain good law.
Requirement (technology-independent): Detect Bluebook/statutory citations in legal text, query CourtListener API v4 for opinion clusters, docket metadata, and precedential status, and cache opinion records locally.
Our design decisions:
  - Regex citation tokenizer in `app/caselaw/citation_parser.py`
  - Async CourtListener client with Redis-backed cluster cache
  - Flagging overruled, distinguished, or non-precedential authorities
Mike source used as coding basis: NO
New dependencies introduced: None
IP notes: None

### Feature: Tamper-Evident Signed Legal Export Manifests
Date: 2026-09-05
Mike observation (product level only): Regulatory filings and court submissions require cryptographic proof that exported documents, review findings, and audit logs have not been altered.
Requirement (technology-independent): Package matter/project/review outputs into a structured ZIP archive containing a `manifest.json` with SHA-256 hashes of every file and an HMAC-SHA256 / Ed25519 digital signature.
Our design decisions:
  - `manifest_signer.py` computing streaming SHA-256 hashes
  - Digital signature verification endpoint `POST /api/audit/verify-manifest`
  - Immutable audit trail recording every export event
Mike source used as coding basis: NO
New dependencies introduced: None
IP notes: None

### Feature: Firm search vs drafting assistant (two products)
Date: 2026-09-12
Mike observation (product level only): Legal AI products separate finding prior work in the firm's files from a conversational assistant that drafts, reviews, and cites documents.
Requirement (technology-independent): Provide two independently usable capabilities. The DMS retriever answers "have we seen this before" with ACL-filtered ranked documents and citations. The drafting assistant is a multi-turn agent that can search the corpus on demand, read documents, and generate Word/Excel drafts with verified quotes.
Our design decisions:
  - DMS / Ask Firm remains `POST /api/answers` + `POST /api/retrieval` over the hybrid engine
  - Drafting assistant remains `/api/chat/*` with tool calling; it does not replace retrieval
  - New `search_firm_records` tool calls our existing `retrieve()` rather than a second index
  - Ask UI presets aligned to the Harbour Chambers PCIJ/UNSC/India filings corpus
Mike source used as coding basis: NO
New dependencies introduced: None
IP notes: Product requirements abstracted from Mike/Legora/Harvey feature lists only. No Mike source was read for this change.

### Feature: On-demand firm-record search in the chat agent
Date: 2026-09-12
Mike observation (product level only): A drafting assistant must be able to look up firm documents during a conversation, not only from a list attached before the first message.
Requirement (technology-independent): Given a natural-language query in chat, search ACL-filtered firm records, add matching documents to the chat-local document index, and let the model read/cite them.
Our design decisions:
  - Tool name `search_firm_records` with `{query, k}`
  - Implementation reuses `app.retrieval.engine.retrieve`
  - Chat-local slugs (`doc-N`) assigned independently
Mike source used as coding basis: NO
New dependencies introduced: None
IP notes: None

### Feature: Chat request correlation and bounded context
Date: 2026-09-12
Mike observation (product level only): None. Generic operations requirement for debugging multi-turn assistants and keeping prompts inside a token budget.
Requirement (technology-independent): Every API response carries a correlation id that appears in assistant logs. A long chat must not resend the entire transcript, and must not send the current user turn twice.
Our design decisions:
  - `X-Request-ID` accepted only as a short token, otherwise a UUID, stored on a ContextVar and echoed by ASGI middleware that does not buffer SSE
  - LLM history keeps the last 10 user/assistant pairs and drops the just-persisted copy of the current user message
  - No conversation summarization model
Mike source used as coding basis: NO
New dependencies introduced: None
IP notes: Not derived from Mike retry, memory, or analytics implementations.

### Feature: Scoped argument supporting-document lookup
Date: 2026-09-14
Mike observation (product level only): None for this slice. Lawyers need the documents that back a matter's stored argument, not a search of the whole firm.
Requirement (technology-independent): After the system has resolved which matter a question is about, it may use the firm's stored list of documents that support that matter's argument, and must still hide documents the member cannot see.
Our design decisions:
  - Channel name `argument_scope`, used only when the metric label is `argument_support` and hard matter scope already resolved matter ids
  - Lookup is `arguments.supporting_documents` for those matter ids, joined to one chunk head per document, with the existing permission predicate in SQL
  - Fusion weight 2.5 is applied on that path only; frozen `p55_repair_ce_protect` weights are not edited
  - No full-text search of issue/position text, no second embedding column, no new dependency
Mike source used as coding basis: NO
New dependencies introduced: None
IP notes: Not an Argument Bank folder, library route, or Mike citation panel. Issue/position bank search is out of scope.

### Feature: Party-span shortlist with optional LLM pick
Date: 2026-09-14
Mike observation (product level only): None. A lawyer may describe a matter by the parties instead of the title.
Requirement (technology-independent): If the question does not contain a stored title, the system may still bind a matter when two or more party names in the question all appear on one stored matter, and must not invent a matter that was not already shortlisted. When several matters match, a model may choose one of those ids or none.
Our design decisions:
  - Runs only after ILIKE and title-containment return nothing, and never on document-title questions
  - Shortlist is SQL AND of party spans against facts, title, opposing party, and client, with the existing permission predicate
  - A single match is accepted without a model. Two or more matches call the model only when `MATTER_LLM_RESOLVE=on`. The model cannot return an id outside the shortlist. Confidence below 0.70 abstains
  - No new embedding column, no fusion-weight change, no new dependency
Mike source used as coding basis: NO
New dependencies introduced: None
IP notes: Not a copy of a vendor matter-resolver service. The model sees only the shortlist, not the firm.

### Feature: Universal document sync / source connectors (Phase 0)
Date: 2026-09-19
Mike observation (product level only): Enterprise legal products often let firms connect cloud document stores (Drive, SharePoint, OneDrive) so files stay synchronized into search/AI without manual re-upload. Observed only as a product capability category — not as UI or implementation detail from Mike source.
Requirement (technology-independent): A firm member can connect an external document provider, after which the system discovers files, downloads only new/changed items using a stored sync cursor, stores originals in object storage, indexes text for retrieval, and removes or tombstones deleted remote files. Access must still honor firm matter permissions; source ACLs are stored for later intersection. Providers plug into one connector interface so the sync engine does not hard-code a vendor.
Our design decisions:
  - Additive tables: `source_connections`, `source_sync_state`, `source_files`, `source_file_permissions`, `identity_links`
  - Python `DocumentConnector` protocol + `FakeConnector` first; real Drive/Graph adapters later
  - Redis list queues with inline drain for tests; no Kafka in Phase 0
  - Reuse existing object store + extractors + document/version write path
  - v1: one connection bound to one matter; matter-trust ACL (source ACL stored, not yet intersected in SQL)
  - Feature flag `SOURCES_SYNC_ENABLED`
Mike source used as coding basis: NO
New dependencies introduced: None (reuses cryptography, redis already in tree)
IP notes: Independent architecture from requirements in docs/universal-document-sync-engine-plan.md. Not derived from Mike connector code, schemas, or UI.

### Feature: LEXOS React frontend (Stitch-designed)
Date: 2026-09-21
Mike observation (product level only): Legal DMS products need a workspace shell with matters, documents, ask/chat, and ACL-aware navigation. Observed only as a general product category — Mike UI/source was not used as a template.
Requirement (technology-independent): Lawyers need a browser UI to browse ACL-scoped matters/documents, ask firm-memory questions with citations, and run a multi-turn chat assistant against the same APIs.
Our design decisions:
  - New Vite + React + TypeScript app under `legal-memory-retrieval/frontend/`
  - Visual system from Google Stitch (project LEXOS Legal Memory DMS / Chambers Ink) — independent of Mike
  - FastAPI continues to serve the production build at `/ui`; legacy SPA archived at `static/_legacy/`
  - Routes and API client designed for our existing `/api/*` contracts
Mike source used as coding basis: NO
New dependencies introduced: react, react-dom, react-router-dom, vite, typescript (MIT)
IP notes: No Mike HTML/CSS/JS copied. Stitch HTML is design reference only; runtime UI is original React.

### Feature: FirmOS UI restyle — Precentis palette + Apple-minimal shell
Date: 2026-09-21
Mike observation (product level only): Legal workspaces typically use a persistent left nav, list views, and a calm reading canvas. Observed only as a general UX pattern category.
Requirement (technology-independent): The product UI should feel institutional and minimal — warm paper surfaces, a restrained accent for actions, typography-led hierarchy, and low chrome density.
Our design decisions:
  - Color/type inspired by Precentis marketing tokens (wine / ink / paper, Manrope + DM Serif Display) remapped into our own CSS variables
  - Apple-like product minimalism: hairline rules, quiet sidebar active state, statement search field
  - No Precentis or Mike markup/components copied; independent React shell and CSS
Mike source used as coding basis: NO
New dependencies introduced: None (Google Fonts CDN only)
IP notes: Palette inspiration from Precentis `styles.css` tokens only; implementation is original.

### Feature: FirmOS workspace shell — LegalWorkspace product patterns
Date: 2026-09-21
Mike observation (product level only): Barristers/law-firm software commonly separates “workspace” navigation (overview, ask, matters) from “manage” directories (people, clients), with sticky context headers and calm directory tables.
Requirement (technology-independent): Present a single product workspace with grouped nav, firm context, overview metrics, an Ask composer, and consistent directory list pages — minimal chrome, wine accent for selection, ink for primary actions.
Our design decisions:
  - Independent `AppShell` with Workspace / Manage groups, 256px sidebar, sticky header crumbs
  - Overview + Ask + directory pages using our own `page-intro` / `directory-tools` language
  - Precentis LegalWorkspace observed for product IA only; no markup, CSS class names, or component bodies copied
Mike source used as coding basis: NO
New dependencies introduced: None
IP notes: Clean-room from product requirements. Mike remains research-only (AGPLv3).

### Feature: FirmOS React parity with prior LEXOS SPA workflows
Date: 2026-09-21
Mike observation (product level only): Legal DMS products need project workstreams, matter deep-dives, knowledge libraries, and citation viewers. Observed only as product capability categories.
Requirement (technology-independent): Restore working firm workflows (projects with folders/milestones, matter tabs, ask provenance, knowledge lists, client detail, activity/tasks, architecture docs) in the FirmOS React UI against existing FastAPI routes.
Our design decisions:
  - Independent React pages/components calling our `/api/projects`, `/api/matters/*`, `/api/knowledge/*`, `/api/retrieval/debug`, `/api/system/*` contracts
  - Behavioural reference: our prior `static/_legacy/` SPA (not Mike); no Mike source used
  - Honest labels for metadata ingest; no fake notification/approval chrome
Mike source used as coding basis: NO
New dependencies introduced: None
IP notes: Migration from our own legacy UI requirements into React. Mike remains research-only (AGPLv3).


