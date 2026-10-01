# Codebase audit — 2026-09-24

Scope: `legal-memory-retrieval/` (FastAPI backend + `frontend/` React SPA served at `/ui`).
Reference inputs: `app/code_pre` (visual/layout reference only — itself mock-driven),
`mike/` (AGPL — product research only, see clean-room rule in `../../../CLAUDE.md`).

Baseline at audit time: backend `pytest tests/` → **492 passed, 1 failed**; frontend `tsc --noEmit` clean.

**Status update 2026-09-24 (evening):** Plans 01–06 executed. Frontend pruned to API-backed pages only;
demo data lives in Postgres (`seed_demo.py`); security + UI contract tests green; production plan 07
mostly done (sync pool, CI, rate limits, config guard). Remaining: cookie/OIDC login (deferred).

Severity: **P0** = exploitable / data exposure, **P1** = broken feature or wrong data shown,
**P2** = maintainability / production-readiness gap.

---

## P0 — Security

| # | Finding | Evidence | Plan |
|---|---|---|---|
| S1 | **Path traversal in SPA handler leaks secrets.** `GET /ui/..%2f.env` returns the backend `.env` (DB URL, Bedrock bearer token). `os.path.join(static, rest)` is never confined to `static/`. | `app/api/main.py` `spa_ui`; reproduced with TestClient → HTTP 200 + `.env` body | 01 |
| S2 | **`AUTH_ENABLED` in `.env` is ignored.** `app/auth/deps.py` reads `os.getenv`, but pydantic-settings loads `.env` without exporting to the environment. Setting it in `.env` silently leaves auth off. | `app/auth/deps.py:10` | 01 |
| S3 | **Production auth cannot work.** `resolve_member` reads table `api_keys`, which does not exist; the error is swallowed → every request 401 when auth is on. No script creates it. | `\dt api_keys` → not found | 01 |
| S4 | **Missing identity = full access.** `ACL_CLAUSE` treats `member_id IS NULL` as admin. In dev mode, omitting `X-Member-Id` returns every matter, including restricted ones. | `app/api/acl.py` | 01 |
| S5 | **Chat has no authorization.** `/api/chat/*` never calls `resolve_member`. Anyone can list/read/rename/delete any session by id; `member_id` comes from the request body. A session created with no `member_id` retrieves with admin scope → ethical-wall bypass. | `app/api/routers/chat_router.py` | 01 |
| S6 | **ACL gaps on read endpoints.** `knowledge/arguments`, `clients/{id}`, `people/{id}` (matter list), `home/stats`, `teams` ignore permissions — restricted matters leak through titles/arguments. Also `reviews`, `tabular`, `workflows`, `drafting`, `word`, `caselaw`, `audit` routers have no member dependency. | route/dependency count per router | 01 (read paths), 07 (rest) |
| S7 | CORS `allow_origins=["*"]` with `allow_credentials=True`. | `app/api/main.py` | 01 |
| S8 | Hard-coded default secret `sources_token_encryption_secret`, MinIO `minioadmin` defaults; nothing refuses to boot with them in production. | `app/config.py` | 07 |

## P1 — Broken or fake behaviour

| # | Finding | Evidence | Plan |
|---|---|---|---|
| B1 | **Backend serves fabricated data as if real.** `/api/knowledge/precedents`, `/api/knowledge/clauses`, and `client_memory` on `/api/clients/{id}` are hard-coded literals (fictional partners "Aryan Maharaj", etc.). | `app/api/routers/knowledge.py`, `clients.py` | 02 |
| B2 | **Deadlines page is always empty.** `/api/tasks` reads `projects.deadline`, but `projects` has 0 rows. There is no deadlines data model. | DB row counts | 02 |
| B3 | `project_activity` has 98 rows pointing at projects that don't exist (orphans, no FK). | DB | 02 |
| B4 | **Ethical wall is untested end to end.** All 170 `permissions` rows are `restricted = false`. | DB | 02 |
| B5 | Frontend personas (`Aryan Maharaj`, `MEM-00049`, …) don't exist in the DB (members are `Helena Voss` … `MEM-00016`). Persona switch shows wrong names; `MEM-00049` is not a member. | `frontend/src/api/types.ts` `PERSONAS` | 03 |
| B6 | Firm identity is split: UI hard-codes "Apex Chambers", backend `home/stats` says "Apex Chambers", corpus/CLAUDE.md say "Harbour International Chambers"; `data/mock.ts` says "Mason & Partners". | `data/firm.ts`, `home.py` | 02, 03 |
| B7 | Topbar notifications are hard-coded fake items linking to Projects/Activity. | `data/firm.ts` | 03 |
| B8 | Chat auto-title never runs: the UI always creates sessions titled "New Conversation", and the backend only titles when `title` is empty. | `ChatPage.tsx`, `chat_router.py` | 05 |
| B9 | Chat model is a free-text input defaulting to `gemini-1.5-flash`, unrelated to the configured Bedrock provider. | `ChatPage.tsx` | 05 |
| B10 | Chat cannot be stopped, has no error state per message, citations render as "Source 1/2" with no title. | `ChatPage.tsx` | 05 |
| B11 | `docker-compose.yml`: `redis:` is indented under `postgres`, so it's a duplicate key, not a service. `docker compose up` doesn't start Redis from this file. | `docker-compose.yml` | 01 |
| B12 | 1 failing test: `test_sync_wrapper_score_raw_fallback` (expects raw score fallback 0.7, gets 0.85). | `tests/test_production_regressions.py:489` | 06 |

## P1 — Frontend with no backend behind it

| Page / element | State | Decision |
|---|---|---|
| Projects, Project detail, Create-project modal | User asked to remove | **Remove** |
| Activity | User asked to remove (re-labels document dates as "activity") | **Remove** |
| Audit page | Re-uses the activity feed; claims to be an audit log | **Remove** (real audit log → plan 07) |
| Strategy, Due Diligence, Knowledge Gaps, Knowledge Management | Static `EmptyState` only — "not exposed by the current API" | **Remove** |
| Experience, Staffing, Transitions | Re-filter the same matters/people list with marketing copy | **Remove** |
| Knowledge hub | Links to the removed pages | **Remove** |
| Precedents | Renders backend literals (B1) | **Remove** with the fake endpoints |
| Permissions page | Static explanatory copy | **Remove** |
| Similar Matters, Timelines (standalone) | Duplicate of Matter-detail tabs | **Remove**; keep as matter tabs |
| Matter tabs: Precedents, Drafts, Emails, Knowledge, Audit, Matter DNA | Empty states / no data source | **Remove tabs** |
| `data/mock.ts` (1,115 lines) | Imported by nothing | **Delete** |
| `AppContext` loads 5 × 200-row lists on every page and persona change | All pages filter client-side; lists silently cap at 200 | Replace with per-page react-query (plan 04) |

**Keep (wired to real endpoints):** Home, Ask, Chat, Matters (+detail: Overview, Documents, Timeline, People, Arguments, Related), Clients (+detail), Documents (+detail, history), People (+detail), Arguments, Deadlines (after 02), Teams, Data Sources, Settings.

## P2 — Production readiness

- No authentication UI; the SPA only sends `X-Member-Id` (dev header). (07)
- `connect()` opens a new psycopg connection per call; the async pool exists but sync routes don't use it. (07)
- `_load_keystore` reads the whole key table per request. (01)
- No startup validation of config (auth off, default secrets) for `ENV=production`. (07)
- No Dockerfile / container for API + built SPA; no CI workflow. (07)
- `datetime.utcnow()` deprecations across audit/drafting/workflows. (07)
- Frontend has no tests, no lint config. (06)
- `evals/` holds ~70 `last_*.json|md` run artefacts in git. (07)
