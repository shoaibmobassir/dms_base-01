# 04 — Backend gaps by feature

✅ exists and usable · 🔧 exists, needs extension/ACL/fix · 🆕 build.
All new endpoints take `member_id = Depends(resolve_member)` and apply `ACL_CLAUSE`
(production-plan rule 2). All new tables get a migration in `app/db/migrations/`.

## 1. Chat workspace (P1)

| Feature | Status | Work |
|---|---|---|
| Sessions CRUD, ownership, stop-safe persistence, title | ✅ | — |
| Matter-scoped session (`chat_sessions.matter_id`) | 🔧 | Accept `matter_id` on create; validate member can access matter; list filter `?matter_id=`; retrieval restricted to matter when set |
| Selected-documents context | 🆕 | `context: {document_ids[], include_authorities, web}` on each message; retrieval filtered to those ids (ACL re-checked per request); persisted on the user message |
| Stage SSE events | 🆕 | Emit `stage` events (scoping, retrieving+count, verifying) from `chat_router`/agent |
| Token streaming | 🆕 | Bedrock streaming in `_call_bedrock` (Mantle supports `stream: true`); forward deltas as they arrive |
| Citation anchors | 🔧 | Resolve each quote to `{version_id, block_id, char_start, char_end, page?, section?}` via `app/documents/anchor.py` before emitting `citation_data` |
| Unverified statements | 🔧 | `verify_citations` result exposed as `verified: bool` per citation + count of uncited factual sentences |
| Regenerate | 🆕 | `POST /sessions/{id}/messages/{msg_id}/regenerate`; `chat_messages.parent_message_id` + `variant_index` |
| Archive / move to matter | 🔧 | `PATCH` supports `status=archived` (exists as delete) — split archive vs delete (`status=deleted`); `matter_id` change with ACL |
| History search | 🆕 | `GET /sessions?q=` over title + first message |
| Suggestions per matter | 🔧 | `/suggestions?matter_id=` using the matter's real document titles |
| Response modes (research template) | 🆕 | `mode: "research"` → structured sections in the system prompt; sections emitted as typed events |
| Export conversation (DOCX) | 🆕 | Reuse `app/drafting/docx_redline_generator.py` style helpers; footnote citations |
| Model display names | 🆕 | `firm_settings.model_labels` jsonb |

## 2. Document viewer (P2, P6) — rendering pipeline and versioning tables are specified in `06_DOCUMENTS_RENDERING_VERSIONING.md` §2–§6

| Feature | Status | Work |
|---|---|---|
| Detail, chunks, highlight, text, versions, diff, blocks, resolve-anchor, annotations, findings | ✅/🔧 | Blocks only for new ingests → backfill blocks for corpus from chunks (one block per chunk as a floor) |
| Outline | 🆕 | `GET /documents/{id}/outline` from block headings / `section_path` |
| Originals in object store | 🆕 | Ingest writes originals; `source_uri` = object key; download streams via object store with ACL (download endpoint fixed in plan 01) |
| Page map | 🆕 | Blocks get `page_start`, `page_end`, `page_char_start/end`; `documents.pages` |
| DOCX → PDF at ingest | 🆕 | Worker step (LibreOffice headless, MPL-2.0 — audit) |
| Spreadsheet table mode | 🆕 | Extract sheets/cells to blocks with `sheet`,`cell` |
| Notes | 🆕 | Table `notes(note_id, member_id, matter_id, document_id?, version_id?, anchor jsonb?, session_id?, message_id?, text, created_at)`; CRUD; visibility = matter ACL |
| "Cited in N conversations" | 🆕 | Query over persisted citations (`chat_messages.citations` jsonb) — add GIN index |
| Test isolation | 🔧 | Tests currently insert rows into the dev DB (pytest temp `source_uri`s, CI fixture matters). Run DB tests in a transaction rolled back per test, or a separate test database |

## 3. Matter workspace & Documents (P3)

| Feature | Status | Work |
|---|---|---|
| Matter detail, timeline, arguments, related, deadlines | ✅ | — |
| Stat strip counts | 🆕 | `GET /matters/{id}/summary` → docs, conversations (member's), authorities, deadlines, drafts |
| Cited matter summary | 🆕 | Generated once via answer engine with citations; cached in `matter_summaries` with `generated_at`; regenerate button |
| Activity (if Q2) | 🆕 | `audit_events(event_id, member_id, matter_id, action, object_type, object_id, created_at)` written by API on: upload, conversation created, analysis run, draft saved, version created. `GET /matters/{id}/activity` (ACL) |
| Create matter | 🆕 | `POST /matters` (admin/partner role check) creating matter, permissions row, team |
| Lead partner / last activity columns | 🔧 | Add to matters list query |
| Upload with progress | ✅/🔧 | Upload batches API exists; add per-file status polling and matter/folder target; ACL on target matter |
| Folders for matters | 🔧 | `project_folders` exists but is project-scoped — generalise to `folders(matter_id, parent_id)` or reuse with matter ownership |
| Document status & pages columns | 🆕 | `documents.status` values from pipeline; `pages` |
| Multi-document actions | 🆕 | Handled by chat context (§1) + tabular review (§4) |
| Pinned matters | 🆕 | `member_pins(member_id, matter_id)` |

## 4. Legal AI tools (P4)

| Feature | Status | Work |
|---|---|---|
| Workflow catalogue & runs | 🔧 | `/api/workflows` exists (3 YAML workflows). Add ACL: runs must only read documents the member can access; add `matter_id` to runs |
| Review engine & findings | 🔧 | `/api/reviews` exists; ACL per document; link findings to blocks (anchors) |
| Tabular review + XLSX export | 🔧 | `/api/tabular` exists; ACL; extraction presets (parties, dates, obligations, termination, payment, governing law, liabilities) as column templates |
| Drafts | 🆕 | `drafts(draft_id, matter_id, title, body, source_message_id, created_by, created_at)` + versions via existing document versioning when "promoted" to a document |
| Defined terms | 🆕 | Extract definitions blocks at ingest → `defined_terms(document_id, term, definition_block_id)` |

## 5. Compare (P5)

| Feature | Status | Work |
|---|---|---|
| Version diff (semantic) | ✅ | Render as redline |
| Any-two-documents diff | 🆕 | `POST /api/documents/compare {a, b}` using the same block aligner; ACL on both |
| Accept/reject → new version | 🔧 | Pending-change set applied to `versions/developing` |
| Tracked-changes DOCX export | ✅ | `/api/drafting/generate-docx-tracked` |

## 6. Research (P7)

| Feature | Status | Work |
|---|---|---|
| Citation extraction/verification | ✅ | `/api/caselaw/extract-citations`, `/verify` (US CourtListener) |
| Authorities from firm corpus (step a) | 🆕 | Batch-extract citations from all documents → `authorities(authority_id, kind, name, court, year, jurisdiction)` + `authority_mentions(authority_id, document_id, block_id)`; search endpoint with filters; ACL through the mentioning documents |
| External authorities (step b) | 🆕 | Connector chosen in Q3; results marked `external`; licensing reviewed |
| Web research (Q4) | 🆕 | Firm-level setting; queries only, never document text |

## 7. Directory pages (P8)

| Page | Work |
|---|---|
| Client detail | `GET /clients/{id}/profile`: preference counts across matters, recurring legal issues (top `legal_issues`), first/last matter, lead partners, matters by year — ACL-filtered |
| Person detail | `GET /people/{id}/profile`: matters by practice, documents authored, courts, matters by year — ACL-filtered counts |
| Arguments | Group by normalised issue; outcomes aggregated; authorities via `authority_mentions` |
| Settings | `firm_settings` (default scope, model labels, web research flag, voice flag); API key management endpoints (admin) |

## 8. Seed data (P0)

Extend `scripts/seed_demo.py` (deterministic, idempotent):

- Matter **Acme Technologies — Series B Financing** (client Acme Technologies Pvt Ltd,
  team, one restricted sibling matter for the wall demo).
- Documents with realistic, fictional full text: Share Purchase Agreement (incl.
  Article XII Termination with 12.1–12.6), Shareholders Agreement, Board Resolution,
  Employment Agreement, Disclosure Schedule, Cap Table (sheet). Two SPA versions (30-day
  vs 15-day cure) for compare.
- Authored as real files: DOCX via python-docx (existing dependency) and PDFs
  produced by the **production converter** (Gotenberg) from those DOCX, plus one scanned-
  style PDF to exercise OCR. No extra PDF library.
- Uploaded through the production ingest pipeline (`06_…` §2) — originals, renditions,
  text layer, blocks, embeddings — never inserted around it, so rendering, citations and
  retrieval quality are real.
- One example conversation is **not** pre-seeded as fake assistant text; instead the
  e2e test asks the §31 question live (with `E2E_LLM=1`). Seeding assistant answers would
  be fabricated output.

## 9. Sharing (Q6) and web research (Q4)

| Feature | Status | Work |
|---|---|---|
| Internal shares | 🆕 | `shares`, `share_recipients`; endpoints create/list/revoke; ACL re-check on open; snapshot stored; fork into own conversation |
| Web research | 🆕 | Provider adapter (admin key in firm settings); query-only; results cached per message; `provenance: "web"` citations |
| Audit | 🆕 | `audit_events` rows for share/open/revoke/export/web query |
