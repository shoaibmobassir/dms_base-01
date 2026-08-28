# Current State Audit — LEXOS Sprint 8

**Date:** 2026-08-28  
**Auditor:** PM Agent (pre-implementation gate)

---

## 1. Backend API — what exists

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/` | GET | Working | Returns sprint, links |
| `/health` | GET | Working | Flags all features on |
| `/metrics` | GET | Working | Prometheus, retrieval counters |
| `/retrieve` | POST | Working | ACL-filtered, all 4 channels, rerank |
| `/ask` | POST | Working | Retrieval + answer + citation + abstention |
| `/ui` | Static serve | Working | Serves `static/` directory |
| `/docs` | GET | Working | FastAPI auto-docs |

### Missing endpoints (planned)
- `GET /matters` — no REST browse endpoint
- `GET /matters/{id}` — no matter detail
- `GET /clients` — no client list
- `GET /members` — no member list
- `GET /documents` — no document list
- `GET /history` — no conversation history
- `POST /workflows/run` — no workflow engine
- `POST /documents/{id}/review` — no clause review

---

## 2. UI — what exists in `static/`

| File | Size | Status |
|---|---|---|
| `index.html` | ~237 lines | Serving |
| `styles.css` | ~1,327 lines | Serving |
| `app.js` | ~1,845 lines | Serving |
| `firm_core_data.js` | ~82,753 lines | Serving — baked-in firm data snapshot |

### UI views rendered
- Home dashboard
- Ask Firm AI (calls POST /ask)
- Matters list + matter detail (data from `firm_core_data.js`)
- Projects list + project detail
- Clients list + client detail
- Documents list
- Teams / People
- Knowledge Vault (precedents, clauses, arguments)
- Live Activity
- Court Deadlines

### UI gaps
- Ask view shows result but no streaming — single response dump
- No citation click-through to actual document chunk text
- No per-query latency display
- No retrieval debug panel (which channels fired, scores)
- No conversation history / session persistence
- Project create modal exists but data is in-memory only (not saved to API)
- No workflow runner UI
- Dark/light theme toggle exists but emoji icons feel unprofessional
- Command palette (⌘K) works on static data only — not wired to live `/retrieve`
- `firm_core_data.js` is 82k lines — too heavy, should be loaded from API endpoints

---

## 3. Database — schema completeness

| Table | Loaded | Indexed | Notes |
|---|---|---|---|
| members | Yes | trgm on name | |
| clients | Yes | trgm on name | |
| matters | Yes | trgm, practice, theme | |
| matter_members | Yes | — | |
| permissions | Yes | restricted | ACL enforced everywhere |
| documents | Yes | matter_id, doc_type | |
| chunks | Yes | tsv, embedding | 41,788 chunks |
| relationships | Yes | source/target | |
| arguments | Yes | matter_id | Loaded but **not retrieved** (0.0 on argument_retrieval eval) |
| api_keys | Missing | — | Sprint 12 — auth not wired |

### Schema gaps
- No `conversations` table (chat history)
- No `workflow_runs` table
- No `review_sessions` table
- No `exports` table
- No `api_keys` table (in IP_ORIGIN_RECORD but not in schema.sql)

---

## 4. Eval coverage

| Type | n | Recall@10 | Flag |
|---|---|---|---|
| exact | 220 | 0.6545 | Good |
| permission | 60 | 1.0 | Perfect |
| negative | 8 | 1.0 | Perfect |
| cross_document | 40 | 0.4795 | Acceptable |
| matter_retrieval | 40 | 0.2964 | Weak |
| versioning | 40 | 0.2662 | Weak |
| graph_reasoning | 15 | 0.45 | Acceptable |
| semantic | 7 | 0.0143 | **Critical gap** |
| similar_matter | 6 | 0.0333 | **Critical gap** |
| person_expertise | 7 | 0.1619 | Weak |
| argument_retrieval | 1 | 0.0 | **Zero — not wired** |
| multi_hop | 1 | 0.0 | Known gap |

**Retrieval gaps to address before Sprint 11:**
1. `argument_retrieval` — `arguments` table exists, zero queries route to it
2. `semantic` — "have we ever handled X" type queries score near-zero
3. `similar_matter` — "similar to matter Y" barely works
4. `versioning` — version group retrieval at 0.27 despite `version_group` column

---

## 5. Tests

| File | Coverage |
|---|---|
| `tests/test_health.py` | Sprint, features flags |
| `tests/test_understand.py` | Intent parsing |
| `tests/test_reranker.py` | Cross-encoder blend |
| `tests/test_retrieval_edges.py` | Edge cases |
| `tests/test_answers.py` | Abstention, citation grounding |

**Missing tests:**
- No test for argument retrieval channel
- No test for Redis cache
- No test for API auth layer
- No integration test for full `/ask` flow with DB

---

## 6. Infrastructure

| Component | Status |
|---|---|
| Postgres :55432 | Running (Docker) |
| Redis :6380 | Running (Docker), health shows available |
| Prometheus metrics | Wired (`/metrics`) |
| OTel traces | Not yet (Sprint 10) |
| Langfuse | Not yet (Sprint 10) |
| CI eval | Not yet (Sprint 11) |
| API key auth | Not yet (Sprint 12) |

---

## 7. PM Verdict

**Blockers for Sprint 9 start:**
- [ ] `api_keys` table migration must be created before auth work begins
- [ ] `arguments` retrieval channel must be audited — zero recall is a dead feature
- [ ] `firm_core_data.js` must be replaced by live API endpoints before UI can grow

**No blockers for:**
- UI overhaul (Sprint 9)
- Ask Firm AI chat interface (Sprint 9)
- Retrieval debug panel (Sprint 9)
