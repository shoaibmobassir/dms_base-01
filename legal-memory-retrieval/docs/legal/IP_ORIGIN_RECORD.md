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

### Feature: FirmOS product frontend (Vite + Tailwind shell)
Date: 2026-09-22
Mike observation (product level only): Legal firm-memory products need a multi-page workspace shell (matters, documents, ask, knowledge, settings) with permission-aware retrieval and citation-linked answers. Observed only as a product capability category — not from Mike source.
Requirement (technology-independent): Lawyers navigate Apex Chambers firm memory via a wine/paper institutional UI: sidebar IA, command palette, Ask with grounded citations, chat, projects, and directory pages, all calling our ACL-filtered APIs with a simulated member persona header.
Our design decisions:
  - Vite 8 + React 19 + TypeScript SPA under `legal-memory-retrieval/frontend`, served at `/ui`
  - Visual/IA baseline from independent FirmOS prototype at `app/code_pre` (Tailwind + Radix/shadcn subset); not Mike
  - Live `apiFetch` + `X-Member-Id` for API-backed routes; Preview-labeled pages where backends do not exist yet
  - Brand: Apex Chambers / FirmOS; no Emergent/PostHog tooling in production build
Mike source used as coding basis: NO
New dependencies introduced: See frontend section in DEPENDENCY_AUDIT.md (React, Vite, Tailwind, Radix, cmdk, sonner, tanstack-query — all MIT/Apache)
IP notes: code_pre is our own UX scaffold (no Mike references in application source). Ported patterns and independently typed TS components; not AGPL Mike UI.

### Feature: Amazon Bedrock AI layer (Ask / chat / experimental embeddings)
Date: 2026-09-23
Mike observation (product level only): Legal memory products need a configurable LLM for grounded answers and chat; firms often prefer cloud models under their cloud account for residency/audit.
Requirement (technology-independent): Given an AWS Bedrock bearer token, the DMS can generate Ask-the-Firm answers and chat completions via selectable foundation models, and optionally embed text via Bedrock embedding models for experiments — without changing the frozen MiniLM-384 production retrieval corpus by default.
Our design decisions:
  - Bearer-token httpx client (`app/llm/bedrock_client.py`) — no boto3/openai SDK added
  - Mantle Chat Completions for chat models; Runtime InvokeModel for Cohere/Titan embeddings
  - `ANSWER_PROVIDER=bedrock` / auto-prefer when `AWS_BEARER_TOKEN_BEDROCK` is set
  - Production `EMBEDDING_PROVIDER=minilm` remains default; Bedrock embedder is opt-in behind factory
  - Smoke probe: `scripts/bedrock_smoke.py`
Mike source used as coding basis: NO
New dependencies introduced: None (reuses httpx)
IP notes: Independent AWS Bedrock integration from AWS public docs; not derived from Mike.

### Feature: Chat workspace experience (stop, citations, models, suggestions)
Date: 2026-09-24
Mike observation (product level only): A legal assistant conversation lets the lawyer stop a
streaming answer, see intermediate work (searching/reading), open cited documents by title,
pick a firm-configured model, get an auto-titled thread, browse past chats by day, and start
from matter-aware suggested questions.
Requirement (technology-independent): R1–R10 in `docs/production-plan/05_chat_experience.md`.
Our design decisions:
  - Independent FastAPI SSE chat (`/api/chat`) with session ownership + ACL on retrieval
  - React ChatPage: AbortController stop, model select from `GET /models`, day-grouped rail,
    citation inspector, suggestions from in-scope Open matters
  - Visual language aligned with our `app/code_pre` scaffold (serif/wine), not Mike UI
Mike source used as coding basis: NO
New dependencies introduced: None beyond existing frontend stack
IP notes: Requirements abstracted from product observation only; no Mike source read for this change.



### Feature: Chat experience rebuild (production plan 05)
Date: 2026-09-24
Mike observation (product level only): A legal assistant chat lets the user stop an answer, see what the assistant is doing, open cited passages, choose a configured model, get auto-titled and renameable conversation history, retry failures, and copy answers. Observed by using the product surface and counting user-facing capabilities; no Mike source was read for implementation, copied, or ported.
Requirement (technology-independent): R1–R10 in `docs/production-plan/05_chat_experience.md`.
Our design decisions:
  - Server: `/api/chat/models` restricted to the active provider; `/api/chat/suggestions` from the caller's in-scope open matters; stream persists partial text on disconnect; citations enriched with real document ids; ownership enforced per session
  - Client: single optional-segment route, AbortController stop, own minimal Markdown renderer (no HTML injection), citations open our Inspector
Mike source used as coding basis: NO
New dependencies introduced: None at runtime (@playwright/test dev-only, Apache-2.0)
IP notes: Visual language from our own `app/code_pre`; behaviour designed from the written requirements.

### Feature: Document rendering, versioning and tracked-changes review (UI roadmap 06)
Date: 2026-09-24
Mike observation (product level only): Mike (a) shows DOCX and PDF documents in-app, (b) highlights cited quotes inside rendered documents, (c) shows a version indicator and lets users upload a new version, (d) delivers AI suggested edits as tracked changes with accept/reject (individually and all), (e) offers redline output. Observed from its README feature list, user-facing vocabulary and third-party dependency names (e.g. pdf.js, a DOCX preview library, LibreOffice conversion). No Mike source files, schemas or prose were read for implementation or copied.
Requirement (technology-independent): R1–R12 in `docs/ui-roadmap/06_DOCUMENTS_RENDERING_VERSIONING.md`.
Our design decisions:
  - Canonical PDF rendition per version; retrieval/citation text extracted from the rendition so highlights never drift
  - Gotenberg/LibreOffice + OCRmyPDF in network-isolated containers; pdf.js viewer behind our own `DocumentRenderer` adapter
  - Versioning on our existing `document_versions` lineage; edit proposals as our own tables
Mike source used as coding basis: NO
New dependencies introduced: planned only (see 06 §3), each to be license-audited before adoption
IP notes: Independent pipeline design; same open-source third-party libraries chosen on their own merits.

### Feature: Chat work modes and cited-passage viewer
Date: 2026-09-24
Inspiration: Mike product observation — a legal assistant conversation can reason out loud, research authorities, review a document for risk, attach citations, and open the cited passage highlighted beside the answer.
Requirement: A lawyer chooses Reason, Research, Review, or Cite before sending. The answer follows that job. Clicking a citation opens the source document with the quoted words marked, and the original file can be opened beside that passage.
Our design: Optional `mode` on our existing chat message request. Mode text is our own addition to `build_system_prompt`. The viewer is `CitationDocumentPanel`, which loads `/api/documents/{id}/text` and marks the verified quote. Original bytes stay in our download endpoint.
Mike NOT used as: source code basis
Dependencies: none
IP notes: Product-level workflow only. No Mike files, styles, or components were copied.

### Feature: Chat workspace completion — step timeline, clarifying form, edit review, paged viewer
Date: 2026-09-25
Inspiration: Mike product observation — the assistant shows its working steps, asks clarifying questions in a form, proposes document edits the user can accept or reject, and opens cited sources beside the chat with the passage highlighted.
Requirement: See `docs/plan/chat-workspace-cleanroom-plan.md` §1 (R1–R9) and §2 (viewer).
Our design: Our own `DocumentViewer` (pdf.js canvas + text layer, fit-width/fit-page, pages rendered near the viewport, page box, zoom, draggable split) with a quote locator that searches the cited page, its neighbours, then all pages; OCR word boxes (`GET /api/documents/{id}/pages/{n}/words`) for highlights on scanned pages; `GET /api/documents/{id}/render` (PDF as is, office files via optional converter, else text view); `[Page N]`-marked document text so citations carry real pages, corrected from the verified quote position; `tool_started`/`tool_finished` events for a step timeline; `propose_edits` tool with accept/reject endpoints and tracked-changes Word export; attachments kept in scope and named to the model; clarifying-question form.
Mike NOT used as: source code basis. Mike was reviewed for features and behaviour only; implementation must start in a session that has not opened Mike source.
Dependencies: pdfjs-dist (Apache-2.0); LibreOffice headless (MPL-2.0, separate process — pending owner approval).
IP notes: No Mike code, names, prompts, event names, or layouts carried into the plan.
