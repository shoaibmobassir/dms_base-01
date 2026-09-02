# Changelog

Metrics come from `python evals/retrieval_eval.py` on frozen `evals/dataset.jsonl` (n=445).

## 2026-09-03 — Engine v2 live wiring + e2e fixes

- **Live path:** `app.retrieval.engine.retrieve` delegates to `engine_v2` when `use_engine_v2=true` (default). `/api/retrieval` and `/api/answers` now run planner + parallel channels (incl. vector) with no lexical→vector sequencing.
- **Fixes:** exact_lookup fusion no longer uses `rerank_candidates=0`; Postgres `ILIKE … ESCAPE` corrected; BM25/metadata use cleaned `search_text`; matter channel free-text fallback; understand strips `have we previously advised on` / `what matters involve`.
- **E2E (live DB):** force majeure → bm25+vector hits; Narang → bm25/metadata/matter; `MTR-2020-00463` → 5 metadata hits; graph reasoning → seed+expansion; ask returns cited answer.
- **Tests:** `pytest tests/` → **204 passed**. Retrieval quality eval not re-run in this change (wiring/bugfix only).

## 2026-08-23 — Sprint 2: lexical baseline

- **Channels:** keyword (Postgres FTS) + metadata
- **Recall@10:** 0.4073
- **MRR:** 0.3593
- **nDCG@10:** 0.3492
- semantic / similar_matter / graph_reasoning / person_expertise / matter_retrieval: ~0
- negative, permission: ~1.0
- Files: schema, ingest, FTS, eval harness, `POST /retrieve`

## 2026-08-23 — Sprint 3: MiniLM + pgvector (infra shipped; overall gate not met)

Embedder: local `sentence-transformers/all-MiniLM-L6-v2` (384-d, L2-normalized). 41,788 chunks embedded. HNSW cosine index on `chunks.embedding`. ACL identical to FTS. `RETRIEVAL_CHANNELS` selects `keyword`, `metadata`, `vector`, `graph`. Default remains `keyword,metadata` so vector ANN does not pollute negatives.

### Vector-only

- **Recall@10:** 0.2638 (below lexical 0.4073 — **gate fail** on overall)
- **MRR:** 0.3096
- **nDCG@10:** 0.2272
- matter_retrieval Recall@10: 0.20 (was 0)
- person_expertise Recall@10: 0.11 (was 0)
- similar_matter Recall@10: 0.008 (was 0)
- semantic Recall@10: 0.0 (gold sets are entire theme clusters; Recall@10 is capped at 10/|gold|)
- negative Recall@10: 0.0 (ANN always returns neighbors — expected)
- permission Recall@10: 0.5 (DENIED half still holds; AUTHORIZED exact-id questions are weak for MiniLM)

### Hybrid preview (not default)

`keyword,metadata,vector` RRF: Recall@10 **0.3973** (slightly under lexical), MRR **0.4184** (above lexical 0.359). exact Recall@10 0.42 vs lexical 0.37. Negatives still collapse if vector is on.

### Files

- `app/embeddings/minilm.py`, `scripts/embed.py`, `app/retrieval/semantic.py`, `app/retrieval/engine.py`
- Durable memory: `.cursor/skills/legal-memory/`, `docs/NORTH_STAR.md`, `.cursor/rules/legal-memory.mdc`

## 2026-08-23 — Sprint 4: hybrid RRF + routing (gate passed)

Default channels: `keyword,metadata,vector`. Weighted RRF (metadata 1.5, keyword 1.2, vector 0.75). Skip vector on exact matter-id/code lookups. Drop ANN hits with cosine < 0.42; if FTS+metadata are empty, require cosine ≥ 0.50 so negatives abstain.

### Hybrid (now default)

- **Recall@10:** 0.4343 (**beats lexical 0.4073 and vector-only 0.2638**)
- **Hit@10:** 0.7076
- **MRR:** 0.3853
- **nDCG@10:** 0.3666
- exact Recall@10: 0.3879
- negative: 1.0 (restored)
- permission: 1.0
- matter_retrieval: 0.20 (Hit@10 0.60)
- semantic / similar_matter Recall@10: still 0
- Files: `app/retrieval/route.py`, weighted fusion, engine routing, eval `hit@10`

## 2026-08-23 — Sprint 5: cross-encoder rerank (gate passed)

Local `cross-encoder/ms-marco-MiniLM-L-6-v2` on fused top 100. Blend CE (0.55) with min-max RRF (0.45). Skip rerank when the query contains an explicit `MTR-` id (preserves permission 1.0). Eval still requests k=20 so Recall@20 is comparable.

### Hybrid + rerank (now default)

- **Recall@10:** 0.4723 (**beats hybrid 0.4343**)
- **Recall@20:** 0.6140 (**beats hybrid 0.5898** — gold not dropped)
- **Hit@10:** 0.8059 (was 0.7076)
- **MRR:** 0.4882 (was 0.3853)
- **nDCG@10:** 0.4105 (was 0.3666)
- exact Recall@10: 0.4652 (was 0.3879)
- negative: 1.0
- permission: 1.0
- semantic / similar_matter / graph_reasoning Recall@10: still 0
- Files: `app/retrieval/reranker.py`, engine fuse→rerank, `tests/test_reranker.py`

## 2026-08-23 — Sprint 6: query understanding (gate passed)

Rule-based intent + entity parse (no LLM). Strip boilerplate so metadata ILIKE hits titles/clients. Route experience questions onto practice area. Skip vector on ids/codes. `/health` exposes `sprint` + feature flags. `POST /retrieve` returns `understanding`.

### Hybrid + rerank + understanding (now default)

- **Recall@10:** 0.5391 (**beats rerank 0.4723**)
- **Recall@20:** 0.6245 (**beats rerank 0.6140**)
- **Hit@10:** 0.7985 (was 0.8059)
- **MRR:** 0.6082 (was 0.4882)
- **nDCG@10:** 0.4972 (was 0.4105)
- exact Recall@10: 0.6682 (was 0.4652)
- matter_retrieval: 0.3008 (was 0.2545)
- person_expertise: 0.1714 (was 0.0095)
- negative: 1.0
- permission: 1.0
- cross_document Recall@10: 0.0187 (was 0.4732 — **regression**; matter-code queries skip vector. Sprint 7 candidate.)
- semantic / similar_matter / graph_reasoning Recall@10: still ~0
- Files: `app/query/understand.py`, `app/sprint.py`, engine routing, `tests/test_understand.py`, `tests/test_retrieval_edges.py`, `tests/test_health.py`

## 2026-08-24 — Sprint 7: SQL matter graph (gate passed on who/which-matter)

Postgres `relationships` + same-lead/different-client via `matter_members`. Default channels add `graph`. Long queries that only contain a matter *code* keep vector. `graph_reasoning` skips metadata so the seed matter does not bury related matters. API keys in `.env` only; answer LLM still off.

### Hybrid + rerank + understanding + graph (now default)

- **Recall@10:** 0.5539 (**beats Sprint 6 0.5391**)
- **Recall@20:** 0.6570 (**beats 0.6245**)
- **Hit@10:** 0.8329 (was 0.7985)
- **MRR:** 0.6263 (was 0.6082)
- **nDCG@10:** 0.5141 (was 0.4972)
- graph_reasoning Recall@10: 0.4223 (was 0.0); Hit@10 0.9333
- person_expertise: 0.1905 (was 0.1714)
- exact: 0.6682 (held)
- negative / permission: 1.0
- cross_document Recall@10: 0.0219 (**not restored** vs Sprint 5 0.47)
- Files: `app/retrieval/graph.py`, engine graph channel, `app/sprint.py`

## 2026-08-24 — Cross-document restore (pre–Sprint 8)

Long “position … MATTER-CODE” questions are `cross_document`. Keyword/vector stay on the raw question; metadata ranks chunks inside the matter by `ts_rank_cd` instead of dumping the first 50. Rerank is not skipped.

### Hybrid + rerank + understanding + graph (still default)

- **Recall@10:** 0.5889 (**beats Sprint 7 0.5539**)
- **Recall@20:** 0.6922 (**beats 0.6570**)
- **Hit@10:** 0.9189 (was 0.8329)
- **MRR:** 0.6930 (was 0.6263)
- **nDCG@10:** 0.5561 (was 0.5141)
- cross_document Recall@10: 0.4826 (was 0.0219; Sprint 5 was 0.47)
- exact: 0.6561 (was 0.6682)
- graph_reasoning: 0.4223 (held)
- negative / permission: 1.0

## 2026-08-24 — Sprint 8: answers + citations + abstention

`POST /ask` retrieves first, then answers. Citations must be retrieved `DOC-` ids; hallucinated ids are dropped and the call abstains. Empty retrieval abstains (`no_evidence`) without calling an LLM. Named `MTR-`/`DOC-` lookups abstain if that entity is not in the ACL-filtered hits. Groq (then Gemini) when keys exist; extractive snippets otherwise. Retrieval eval is unchanged.

- Answer eval (extractive): abstention accuracy **1.0** on negatives + DENIED (n=38); citation grounding **1.0** on 40 exact questions (cited ⊆ retrieved).
- Files: `app/answers/*`, `POST /ask`, `evals/answer_eval.py`, `tests/test_answers.py`

### Next gate (Sprint 9)

Redis cache + latency. Do not add Kafka/Neo4j/agents.

## 2026-08-28 — Section routes: one API prefix per sidebar view

Replaced catch-all `/api/browse` and `/api/institutional` with dedicated section routers aligned to the LEXOS sidebar. Each document is served at `/api/documents/{document_id}` with sub-routes for versions, diff, and chunks.

- **home** `/api/home` — dashboard stats
- **matters** `/api/matters` — list, detail, arguments, related, timeline, graph
- **documents** `/api/documents` — list, `{id}`, ingest, versions, diff, chunks
- **clients** `/api/clients` — list, detail, matters
- **people** `/api/people` — directory
- **projects** `/api/projects` — workstreams (unchanged prefix)
- **teams** `/api/teams`, **knowledge** `/api/knowledge`, **activity** `/api/activity`, **tasks** `/api/tasks`
- **search** `/api/search` — command palette
- **answers** `/api/answers`, **retrieval** `/api/retrieval`, **system** `/api/system`
- Files: `app/api/routers/{matters,documents_router,clients,people,...}.py`, `static/app.js`, `tests/test_api_services.py`

## 2026-08-28 — API gateway: service-oriented routes

Monolithic flat routes removed. Six bounded services mounted under `/api/{service}` matching the LEXOS frontend. No retrieval ranking changes — eval rerun not required.

- **system** `/api/system` — health, metrics, info
- **retrieval** `/api/retrieval` — hybrid search with ACL
- **answers** `/api/answers` — grounded Q&A with citations
- **browse** `/api/browse` — members, clients, matters, documents, search, ingest, versions, diff, timeline, graph *(superseded by section routes above)*
- **projects** `/api/projects` — workstreams and milestones
- **institutional** `/api/institutional` — stats, knowledge, activity, tasks, teams *(superseded)*
- Files: `app/api/main.py` (gateway), `app/api/routers/*`, `app/api/documents.py`, `app/api/hits.py`, `tests/test_api_services.py`

## 2026-08-30 — Sprint 9: DMS Answer Quality + Parallel Retrieval

### Phase 1: Production Ingest Pipeline

Built `app/ingest/` — reusable, resumable, idempotent PDF ingest pipeline.

- `app/db/schema.sql` — Additive extensions: `source_uri`, `content_sha256`, `mime_type`, `ingest_job_id`, `ingested_at` on `documents`; new `ingest_jobs` + `ingest_items` tables
- `app/ingest/models.py` — `DocumentRecord`, `IngestItem`, `IngestJob`, `MatterManifest`
- `app/ingest/extractors/pdf.py` — pypdf-based text extraction
- `app/ingest/normalize.py` — filename → document_type inference + manifest matching
- `app/ingest/writer.py` — INSERT with `content_sha256` idempotency
- `app/ingest/pipeline.py` — Orchestrator: extract → normalize → chunk → write
- `app/ingest/jobs.py` — Job lifecycle: create, register, mark, complete, resume
- `app/ingest/cli.py` — `python -m app.ingest run --source ../docs --manifest ingest/manifests/real_filings.yaml`
- `ingest/manifests/real_filings.yaml` — 3 matter clusters × 7 PDFs

### Phase 2: DMS Gold Eval Dataset

- `evals/dms_portal_dataset.jsonl` — 20 Q&A pairs (factual 8, procedural 4, cross-doc 3, negative 3, metadata 2)
- `evals/dms_answer_eval.py` — Automated eval: retrieval_recall, answer_contains, abstention_accuracy, matter_match, grounding, DMS field presence

### Phase 3: DMS Portal Response Format

`/api/answers` now returns DMS-portal-style structured fields:
- `key_finding` — 1-2 sentence executive summary
- `structured_citations[]` — document_id + matter_id + tags
- `sources[]` — top hits with highlighted snippets
- `matchedMatters[]` — deduplicated by matter_id, ranked by score
- `tags[]` — Matter ID, Document Type, Client, Forum, Practice Area

Files: `app/answers/format.py` (NEW), `app/api/routers/answers.py`, `app/answers/llm.py` (richer prompt + 1200-char context)

### Phase 4: Parallel Retrieval

**Before**: `understand(2×) → keyword → metadata → vector → graph → fusion → rerank`
**After**: `understand(1×) → [keyword | metadata | graph] parallel → vector → fusion → rerank`

- `app/retrieval/engine.py` — `ThreadPoolExecutor` with per-channel DB connections
- `app/answers/generate.py` — Eliminated redundant `understand()` call
- Reports `parallel_wall_ms` in latency breakdown

### Phase 5: Tests

| File | Cases |
|------|-------|
| `tests/test_ingest_pipeline.py` | Doc type inference, manifest matching, title normalization, sha skip |
| `tests/test_parallel_retrieval.py` | Channel parsing, weight adjustments, parallel_wall_ms, cache hit |
| `tests/test_answer_format.py` | Tag building, structured citations, matchedMatters dedup, key_finding |
| `tests/test_ingest_jobs_api.py` | Create job, poll status |
| `tests/test_dms_eval.py` | Dataset schema validation |
| `tests/test_api_services.py` | DMS fields on `/api/answers` |

### Eval results (2026-08-30 run)

**Retrieval** (`evals/retrieval_eval.py`, n=445): Recall@10 **0.5895** (unchanged gate), MRR **0.6941**, nDCG@10 **0.5568**

**Answer regression** (`evals/answer_eval.py`): abstention accuracy **1.0** (n=38), citation grounding **1.0** (n=40)

**DMS portal** (`evals/dms_answer_eval.py`, n=20, real PDFs seeded):
- Real PDF ingest: **6/7 indexed** (116 new chunks embedded); 1 failed — `MSEDCL Note in APL. 163 of 2018.pdf` (scanned, 0 chars via pypdf)
- retrieval_recall **0.50**, answer_contains **0.375**, abstention_accuracy **0.55**, matter_match **0.3125**, grounding **1.0**
- DMS field presence: key_finding **0.40**, structured_citations **0.55**, tags **0.55**
- avg_latency_ms **1329**

**Dependencies added:** `pypdf` (BSD-3-Clause), `PyYAML` (MIT) — recorded in `docs/legal/DEPENDENCY_AUDIT.md`

**New scripts:** `scripts/migrate_ingest_schema.py`, `scripts/seed_real_docs.py`, `evals/build_dms_eval.py`

## 2026-09-01 — Project Workspace UI (Folders + Version History + Activity)

Frontend wiring for the project improvement sprint. Mike consulted at product level only (AGPL clean-room).

### Project Detail Workspace

- **Overview tab** — scope, milestones (live toggle), team preview, recent documents from API
- **Documents tab** — nested folder tree sidebar, document table with folder move dropdown, version chip → history viewer with diff
- **Activity tab** — chronological audit trail from `project_activity`
- **Export** — one-click JSON manifest download with SHA-256 hashes
- **Inspector pane** — recent activity feed + Ask Project AI

### Bug Fix

- `POST /projects/{id}/documents/{doc_id}` cross-matter copy: fixed broken `cur.execute().fetchone()` chain

### Files Changed

- `static/app.js` — `ensureProjectDetail()`, tab rendering, folder CRUD, version history panel
- `static/styles.css` — folder tree, activity timeline, project workspace layout
- `app/api/routers/projects.py` — assign-document copy fix

## 2026-09-01 — Projects Improvement: Versioning + Folders + Activity

Inspired by Mike product research (AGPL clean-room — see `agpl-cleanroom.mdc`). All designs independently derived from requirements.

### Document Versioning

Immutable `document_versions` table with SHA-256 integrity. Each edit creates a new version row; `documents.current_version_id` points to the active one. Old versions never deleted — full audit trail.

- `app/documents/__init__.py` (NEW) — `create_version()`, `list_versions()`, `get_version()`, `diff_versions()`, `seed_initial_version()`, `content_sha256()`
- `app/api/routers/documents_router.py` — New endpoints: `POST /{id}/versions`, `GET /{id}/versions`, `GET /{id}/versions/{vid}`, `GET /{id}/versions/{vid}/diff`
- `app/db/schema.sql` — `document_versions` table, `current_version_id` + `folder_id` + `updated_at` columns on `documents`

### Project Folders

Nested folder tree with cycle detection (max depth 5). Documents assignable to folders.

- `app/db/schema.sql` — `project_folders` table with `parent_folder_id`
- `app/api/routers/projects.py` — Endpoints: `POST /{id}/folders`, `GET /{id}/directory`, `PATCH /{id}/folders/{fid}`, `DELETE /{id}/folders/{fid}`

### Document Assignment & Copy

- `POST /projects/{id}/documents/{doc_id}` — assign doc to project's matter, or cross-matter copy
- `PATCH /projects/{id}/documents/{doc_id}/folder` — move doc to a folder within the project

### Project Activity Timeline

`project_activity` table records all mutations: project creation, milestone toggles, folder CRUD, document additions/moves.

- `app/projects/__init__.py` (NEW) — `record_activity()` helper with cursor/conn/standalone modes
- `GET /projects/{id}/activity` — paginated timeline with actor names

### Enhanced Project Detail + Export

`GET /projects/{id}` now returns: `team[]`, `folders[]`, `recent_activity[]`, `document_count`

`GET /projects/{id}/export` — downloadable manifest with document list, version hashes, milestones, manifest SHA-256

### New Pydantic Schemas

`FolderCreate`, `FolderUpdate`, `DocumentFolderMove`, `VersionCreate` in `app/api/schemas.py`

### Tests (24/24)

| File | Cases |
|------|-------|
| `tests/test_document_versioning.py` | SHA-256, diff (changes, identical, missing), unicode |
| `tests/test_project_folders.py` | Cycle detection (direct + indirect), depth limit, payload builder, Pydantic schemas |
| `tests/test_project_activity.py` | Activity recording (cursor, conn, standalone), metadata serialization |


