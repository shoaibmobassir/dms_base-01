# Document Intelligence + Version Control — Implementation Plan

**Product principle:** The PDF is not the document. A `DocumentVersion` is the canonical object; PDF/DOCX/HTML are representations.

**Related code (already started):**
- Schema: `app/db/schema.sql`, `app/db/migrations/20260905_doc_intelligence_version_control.sql`
- Blocks / anchors / diffs: `app/documents/canonical.py`, `anchor.py`, `diff.py`
- Review engine: `app/review/engine.py`, `app/review/planner.py`, `app/api/routers/reviews.py`
- Simulator (in-memory proof): `doc-search/architecture_sim/`

**Hard constraints (LEXOS gates):**
- ACL in SQL before ranking
- No Kafka / Neo4j / agents until measured need
- Embeddings stay MiniLM 384-d behind `app/embeddings`
- Do not claim retrieval gains without `evals/retrieval_eval.py`

---

## Status legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Done (code + tests; migrate DB if marked) |
| 🔧 | Partial — finish this sprint slice |
| ⬜ | Not started |
| 🔒 | Blocked on earlier phase |

---

## Phase 0 — Foundations (ship first)

| ID | Task | Deliverable | Status |
|----|------|-------------|--------|
| P0.1 | Immutable `document_versions` table + API | `create_version`, list, get, lexical body diff | ✅ |
| P0.2 | Nested `project_folders` + `folder_id` on documents | Folder tree APIs | ✅ |
| P0.3 | Apply doc-intel migration to live Postgres | Tables: blocks, diffs, review_jobs, findings, anchors, annotations | ✅ |
| P0.4 | Version columns: `parent_version_id`, `storage_uri`, `change_summary` | ALTER + writer updates | ✅ |
| P0.5 | Auto-parse canonical blocks on every new version | `create_version` → `parse_canonical_blocks` → `save_canonical_blocks` | ✅ |
| P0.6 | Unit tests for parser, anchors, diffs, review (no LLM) | `tests/test_document_intelligence.py`, `test_anchor_resolver.py`, `test_semantic_diff.py`, `test_review_engine.py` | ✅ |
| P0.7 | Architecture simulator e2e (synthetic corpus) | `doc-search/architecture_sim` + pytest | ✅ |

**Exit criteria:** Migration applied; creating a version writes blocks; unit tests green.

---

## Phase 1 — Canonical structure & durable anchors

| ID | Task | Deliverable | Status |
|----|------|-------------|--------|
| P1.1 | Block types: heading, paragraph, clause, table, footnote, signature, list | Parser coverage | ✅ |
| P1.2 | Content anchors (block + offsets + quote + text_hash) | `evidence_anchors` model | ✅ |
| P1.3 | 3-tier anchor resolver (exact → fuzzy → semantic) | `app/documents/anchor.py` | ✅ |
| P1.4 | API: `GET /documents/{id}/versions/{vid}/blocks` | Router endpoint | ✅ |
| P1.5 | API: `POST /documents/{id}/versions/{vid}/resolve-anchor` | Resolve for viewer | ✅ |
| P1.6 | Never store PDF bbox as canonical; optional render cache only | Doc + schema note | ⬜ |

**Exit criteria:** Viewer can jump finding → block via API without PDF coordinates.

---

## Phase 2 — Version timeline & dual diffs

| ID | Task | Deliverable | Status |
|----|------|-------------|--------|
| P2.1 | Lexical redline (word/line) | `compute_word_redline` / `diff.py` | ✅ |
| P2.2 | Semantic/legal diff (caps, CoC, governing law, …) | `diff_document_versions` + `version_diffs` | ✅ |
| P2.3 | Persist diffs; `GET .../versions/{a}/diff/{b}` | API | ✅ |
| P2.4 | Version timeline payload (author, status, label, change_summary) | Enrich list API | ✅ |
| P2.5 | “Why did this version change?” summary from semantic diff | API field `change_intelligence` | ⬜ |

**Exit criteria:** SPA timeline shows vN→vN+1 lexical + material legal changes.

---

## Phase 3 — Findings, annotations, bidirectional highlight

| ID | Task | Deliverable | Status |
|----|------|-------------|--------|
| P3.1 | `Finding` + `evidence_anchors` persistence | Tables + review engine write path | ✅ |
| P3.2 | `annotations` (AI highlight ↔ finding_id) | Schema + write on verify | 🔧 |
| P3.3 | Finding status PATCH (open/reviewed/accepted/dismissed) | `/api/reviews/...` | ✅ |
| P3.4 | Bidirectional API: finding→anchors, block→findings | Endpoints | ⬜ |
| P3.5 | Lawyer highlight / comment / issue types | Annotation create API | ⬜ |

**Exit criteria:** Click finding returns anchors; click block returns linked findings.

---

## Phase 4 — Review Engine (Map → Reduce → Verify)

| ID | Task | Deliverable | Status |
|----|------|-------------|--------|
| P4.1 | Feature catalog (indemnity, CoC, termination, …) | `app/review/planner.py` | ✅ |
| P4.2 | Parallel map workers + verify quote hashes | `FastReviewEngine` | ✅ |
| P4.3 | `POST /api/reviews/run` + get job/findings | Router live | ✅ |
| P4.4 | Hierarchical prune before map (doc summary → sections) | Hierarchical retrieve + block/section hints | ✅ |
| P4.5 | Cross-doc reduce report | Aggregated by category | ✅ |
| P4.6 | Partial failure: N−k success + error list | Job error_summary | 🔧 |
| P4.7 | Version-keyed review cache (Redis) | Cache keys include version_id + model_v | ⬜ |

**Exit criteria:** Review 50+ seeded docs in &lt;60s wall (CPU, rule-based); findings verified.

---

## Phase 5 — Hierarchical intelligence & retrieval alignment

| ID | Task | Deliverable | Status |
|----|------|-------------|--------|
| P5.1 | Section + document summaries at ingest/version time | Columns or `document_intelligence` table | ⬜ |
| P5.2 | Version-scoped chunks (do not overwrite prior version embeddings) | `chunks.version_id` + hierarchical parent/child | ✅ |
| P5.3 | Matter → Document → Chunk retrieval path in engine v2 | Planner flag + channel | ✅ |
| P5.4 | Context envelope (client/matter/folder/doc/section/page) | Context builder + API | ✅ |
| P5.4d | **Diagnosis only** — stage ranks, provenance CSV, drop-stage stats | `app/retrieval/diagnose.py` + `evals/retrieval_diagnose.py` | ✅ |
| P5.5 | **Fusion correction only** — hierarchy as candidate gen, rank-based fusion, budgets | Ablation matrix; no graph/reranker rewrite | ✅ (then exact repair) |
| P5.5e | **Exact retrieval repair** — title-ranked metadata path + taxonomy | Hit@10 .77→.996 on exact | ✅ |
| P5.6 | **Matter / Semantic / Similar** — matter as scope first (not GraphRAG) | P5.6-A + B0 survival | 🔄 |
| P5.6a | Matter routing ablation (score vs hard vs hier hybrid) | `evals/matter_routing_ablation.py` | ✅ hard promoted |
| P5.6b0 | Semantic candidate survival (R@20 attribution) | `evals/semantic_candidate_survival.py` | ✅ Outcome A |
| P5.6c0 | Vector matter → scoped docs (K=5..50) | `evals/semantic_doc_resolve_ablation.py` | ✅ negative (ceiling ≤.10) |
| P5.6c1 | Holder-matter resolver (lexical OR / hybrid RRF) | `evals/holder_matter_ablation.py` | ✅ lexical_struct best |
| P5.6c4 | Matter evidence profiles + theme routing | `evals/matter_profile_ablation.py` | ✅ theme Cov@100=.99; Cov@50=.60 |
| P5.6c5 | Theme-complete docs (C5.0–C5.3) | `evals/theme_scoped_doc_ablation.py` | ✅ ceiling=1.0; Doc R@20≈0 |
| P5.6c54 | Discriminative lexical A–D | `evals/disc_lexical_ablation.py` | ❌ D R@20=.007 |
| P5.6c55 | Contextual chunk embeds A1–A3 | `evals/contextual_chunk_ablation.py` | ❌ Case C R@100≈0 |
| P5.6c55d | Doc profile discovery D0–D3 | `evals/doc_profile_discovery.py` | ✅ type/role signal; typed ceil explained |
| P5.6c55d45 | Role-family oracle D4/D5 | `evals/role_family_oracle_ablation.py` | ✅ family ceil=1.0; R@20=.043 Hit@20=.57 |
| P5.6c55d6 | Purpose profile D6 | `evals/purpose_profile_ablation.py` | ❌ no lift vs D5; → evidence-level |
| P5.6c7 | Evidence-first C7.0–C7.4 | `evals/evidence_retrieval_ablation.py` | soft Ev R@20=.02; hard-role Hit@20=.71 |
| P5.6c74b5 | Phrase/prox/soft role + CE evidence | same ablation + `evidence_rerank.py` | soft=.033; **CE FAIL**; next C7.6 agg |
| P5.6d | Hybrid doc retrieval + CE (after candidates) | Doc R@20 ≥~.85 then CE | ⬜ |
| P5.7 | Hierarchical KG routing MVP (Postgres metadata first; not Neo4j) | Graph as router, not similarity matrix | ⬜ |
| P5.8 | Reranker optimization | Candidate count / CE features | ⬜ |
| P5.9 | Million-doc scale metrics (CRR + R@20≥~95%) | Eval gates + CHANGELOG | ⬜ |

**P5.5 FINAL baseline (freeze reference):** R@10 **.739** · Hit@10 **.926** · MRR **.805** · Exact Hit@10 **.996**  
**P5.6-A promoted:** `MATTER_SCOPE=hard` → R@10 **.764** · Hit@10 **.948** · MRR **.859** (exact held)

**P5.6 promotion:** ΔR@10/Hit/MRR each ≥ +1pp **and** exact Hit@10 ≥ .99. Matter = WHERE to search, not final relevance.

**P5.3 eval lesson (n=445):** R@5 **+0.100** but Hit@10 **−0.152** and MRR **−0.094**. Hierarchy finds candidates; fusion/ranking puts the wrong ones first. Do **not** celebrate +0.0025 R@10.

**Immediate gate (until P5.5 green):**

```text
Recall@10 >= baseline (0.5895)
AND Hit@10 >= baseline (0.9238)
AND MRR     >= baseline (0.6941)
```

**Engineering progression (not a single weight-tuning pass):**

```text
P5.3 → P5.4d diagnose → P5.5 fusion + exact repair ✅
→ P5.6 matter/semantic/similar (scope routing; no GraphRAG yet)
→ P5.7 hierarchical KG routing → P5.8 reranker → P5.9 scale/CRR
```

**Rule:** Hierarchy decides *where* to search; evidence ranking decides *what* is relevant. Do not let matter/graph hierarchy overwhelm chunk evidence.

**Exit criteria (Phase 5):** Multi-metric gate passes; hierarchical path measurable in diagnose CSV + debug UI; no R@10-only claims.

---

## Phase 6 — Async bulk ingest (1000s of files/folders)

| ID | Task | Deliverable | Status |
|----|------|-------------|--------|
| P6.1 | Upload batch → object store URI → `ingest_jobs` / `ingest_items` | Existing jobs API | ✅ |
| P6.2 | Preserve folder_path through ingest | Materialized path on document | ✅ |
| P6.3 | Progress counters (pages, chunks, embeddings, errors) | Job status payload | 🔧 |
| P6.4 | Worker: parse → structure → blocks → chunks → embed → summary | Celery later; ThreadPool OK first | 🔧 |
| P6.5 | Local/MinIO storage adapter behind interface | `storage_uri` filled | ✅ |
| P6.6 | Graceful per-file failure + retry | Item status | ✅ |

**Exit criteria:** Upload 100+ files returns immediately; poll shows READY/ERROR per file.

---

## Phase 7 — Viewer / Review Mode UI

| ID | Task | Deliverable | Status |
|----|------|-------------|--------|
| P7.1 | Document tabs: Document / Review / Versions / Citations | LEXOS SPA | ⬜ |
| P7.2 | Finding list → scroll to evidence | Uses anchor API | ⬜ |
| P7.3 | Highlight → finding panel | Reverse lookup | ⬜ |
| P7.4 | Lazy load annotations for long docs | Pagination | ⬜ |
| P7.5 | PDF.js render using anchors as truth | Coordinates derived at render time | ⬜ |

**Exit criteria:** End-to-end demo: review job → click finding → text highlight.

---

## Phase 8 — Hardening & scale

| ID | Task | Deliverable | Status |
|----|------|-------------|--------|
| P8.1 | OTel spans for review map/reduce/verify | Trace IDs in job | ⬜ |
| P8.2 | ACL on review/findings (matter permissions) | SQL filter | ⬜ |
| P8.3 | IP origin record for Legora-inspired UX | `docs/legal/IP_ORIGIN_RECORD.md` | ⬜ |
| P8.4 | Load test 500–1000 docs (sim + optional DB) | Metrics doc | ⬜ |
| P8.5 | Only then: Celery/Temporal, OpenSearch, graph DB | Behind interfaces | 🔒 |

---

## Recommended build order (this week)

```text
Week slice A (Phase 0 close-out)
  P0.3 apply migration
  P0.4 parent_version_id + storage_uri + change_summary
  P0.5 verify blocks written on create_version
  Smoke: pytest tests/test_document_*.py tests/test_review_engine.py tests/test_anchor*.py

Week slice B (Phase 1–2 APIs)
  P1.4 blocks endpoint
  P1.5 resolve-anchor endpoint
  P2.3–P2.4 diff + timeline enrichment

Week slice C (Phase 3–4 polish)
  P3.2 annotations on verify
  P3.4 bidirectional lookup
  P4.4 hierarchical prune + P4.7 cache

Week slice D (Phase 6 ingest)
  P6.2–P6.3 folder path + progress
  Do not start Phase 7 UI until A–C stable
```

---

## Mental model (canonical object)

```text
Document
  ├── Metadata + Permissions
  └── Version (immutable) ── raw artifact (storage_uri)
        ├── Blocks (canonical structure)
        ├── Chunks + embeddings (per version)
        ├── Summaries / entities
        ├── Findings ← Evidence anchors
        ├── Annotations
        └── Diffs vs parent version
```

---

## How to run / verify (current)

```bash
# Apply migration
cd legal-memory-retrieval
python scripts/migrate_doc_intelligence.py

# Unit + engine tests
pytest tests/test_document_intelligence.py tests/test_anchor_resolver.py \
       tests/test_semantic_diff.py tests/test_document_versioning.py \
       tests/test_review_engine.py -q

# Architecture simulator (no Postgres)
cd ../doc-search
pytest tests/test_architecture_sim_e2e.py -q
python scripts/run_architecture_sim.py --docs 50 --pages 20
```

---

## Out of scope until gates pass

- Kafka, Neo4j, Kubernetes, GPU clusters
- Copying or porting Mike (AGPL) source
- Replacing MiniLM dimension without re-embed plan
- Claiming “Legora parity” without measured review latency + citation integrity
