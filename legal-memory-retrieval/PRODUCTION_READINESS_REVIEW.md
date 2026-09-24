# LEXOS / FirmOS production-readiness review

**Review date:** 2026-09-24 (replaces the 2026-09-21 assessment)  
**Scope:** `legal-memory-retrieval` and the supporting product/operating material.  
**Decision:** **Do not deploy customer client files to production.** The retrieval core and the lawyer-facing SPA are now a credible single-firm prototype. Identity is API keys, not a firm IdP. There is no tenant key or row-level security on the core tables, and there is no AWS or Azure stack, backup drill, or commercial pack.

Evidence for this revision: `docs/production-plan/` (plans 01–06 done, 07 in progress), `docs/production-plan/AUDIT.md` (2026-09-24), `docs/CHANGELOG.md` (Bedrock AI layer 2026-09-23, SPA rebuild 2026-09-22), and a read of the current auth, Compose, container, CI, and document-download paths.

## What changed since 21 September

| 21 Sep finding | 24 Sep state |
|---|---|
| Compose YAML invalid (`redis` nested under `postgres`) | `postgres` and `redis` are sibling services. Optional `object-store` and `app` profiles. |
| No Dockerfile, no CI | Multi-stage `Dockerfile` (SPA build + Python 3.12, non-root). `.github/workflows/ci.yml` migrates, seeds, and runs the contract suite plus `tsc` and the frontend build. |
| Document download and several routers had no member dependency | Protected routers are mounted with `Depends(resolve_member)`. Chat sessions are owner-scoped. Read paths used by the SPA apply the matter ACL. |
| `AUTH_ENABLED` in `.env` was ignored; `api_keys` table missing; missing identity was full access when auth was on | Auth reads `settings.auth_enabled`. Migration creates `api_keys`. A DB failure on key lookup is 503. `ENV=production` refuses to boot with auth off, wildcard CORS, or default secrets. |
| CORS `*` with credentials | `CORS_ORIGINS` is an explicit list (default `http://localhost:5173`). Credentials are off when `*` is present. |
| SPA path traversal could return `.env` | `/ui` assets must resolve inside `static/`. |
| Static `app.js` inserted document HTML | The live UI is the Vite React SPA. Assistant markdown is rendered as text nodes. `static/_legacy/app.js` is not the mounted app. |
| Frontend personas and hard-coded firm copy | Firm name, deadlines, client notes, and the ethical-wall seed live in Postgres. The persona switcher appears only when auth is off. With auth on, the SPA signs in with an API key. |
| Chat UI incomplete (title, model, stop, citations) | Chat plan (sessions, stop, configured models, citation titles, suggestions) is marked done in `docs/production-plan/05_chat_experience.md`. |

## Executive assessment

Keep:

- Hybrid retrieval (lexical, vector, metadata, graph, fusion, cross-encoder), ACL in SQL before rank, citations, eval harnesses, matter scope.
- A React SPA a lawyer can use against the seeded database: Home, Ask, Chat, Matters, Documents (detail and history), Clients, People, Calendar, Arguments, Settings.
- A boot guard, connection pool, readiness probe, rate limit on answers and chat messages, and a container image that refuses development defaults when `ENV=production`.
- Bedrock as an opt-in answer/chat provider (`AWS_BEARER_TOKEN_BEDROCK`). Retrieval embeddings stay MiniLM 384-d unless `EMBEDDING_PROVIDER=bedrock` and the corpus is re-embedded.

Still blocking a design-partner firm:

- No OIDC/SAML. Production auth is a long-lived API key. The SPA stores that key in browser storage. Cookie sessions are explicitly deferred in plan 07.
- Core tables (`members`, `clients`, `matters`, `documents`) have no tenant key and no PostgreSQL row-level security. `tenant_id` appears on later tables (`firm_profile`, upload batches) and defaults to a single firm.
- No Terraform/Bicep/CloudFormation, no private network, no managed backups, no restore drill, no WAF, no pen test, no DPA.
- Uploads still read each file fully into the API process. Source sync is still the Phase-0 fake connector.
- CI gates a contract subset (`test_health`, `test_security`, `test_ui_contract`, `test_chat_assistant`), not the full `pytest` suite, container scan, or retrieval eval.

The immediate goal remains a **single-firm design-partner pilot** after the remaining P0s below. Multi-tenant SaaS is a later programme. First customers should get a dedicated stack, not a shared database.

## What exists today

| Capability | Current state | Production assessment |
|---|---|---|
| Retrieval and answers | Engine v2, fusion `p55_repair_ce_protect`, hard matter scope, citations, abstention, cache, eval artefacts. Bedrock can answer; MiniLM still embeds. | Solid R&D base. Benchmarks are on the Harbour/PCIJ corpus, not a customer acceptance set. |
| Core legal model | Members, clients, matters, permissions, documents, chunks, versions, upload batches, court deadlines, client notes, firm profile. | Usable for one firm. Not a tenant model. |
| Ingestion | Folder batches, object-store abstraction (local or S3-compatible), per-file failure isolation on batch run. | Not safe for untrusted bulk upload: whole file buffered in the API, no malware scan, no direct-to-bucket upload. |
| User experience | React SPA served at `/ui`, wired to the API. Chat has sessions, streaming, stop, and citations. | Enough for an internal demo. Document viewer, Word, tabular, and workflows are not the product surface. API-key login is not firm SSO. |
| Auth and ethical walls | API keys, matter ACL, chat ownership, production boot guard. Seeded restricted matters exist for tests. | Dev mode still trusts `X-Member-Id` and treats a missing member as anonymous admin. No SSO, SCIM, session revocation, or RLS. |
| Observability | Prometheus/OTel hooks, request IDs, `/api/system/ready` (DB + Redis). | No SLOs, paging, dashboards, log-redaction policy, or incident runbook. |
| Delivery | Valid Compose, Dockerfile, GitHub Actions contract CI. | No image signing, SBOM, IaC, environment promotion, or rollback. |

## Launch blockers (P0)

### P0-01 — No deployable cloud platform

- **Was:** Compose did not parse; no image; no CI.
- **Now:** Compose parses. `docker compose --profile app up --build` is the documented app shape. CI exists for the contract suite and the frontend build.
- **Still required:** Immutable images in a registry, signed publication, IaC for one primary region, migrations as a one-shot job, backups, a restore drill, and rollback. CI must grow to the full test suite, dependency/SAST/container scans, and a retrieval non-regression gate before a release is called green.
- **Impact:** A laptop Compose file is not a firm deployment.

### P0-02 — One download path still skips the matter ACL

- **Was:** `GET /documents/{id}/download` had no member dependency and no ACL. Several routers were unauthenticated.
- **Now:** Routers other than `/api/system` require `resolve_member`. `document_text` and the normal download path call `_check_doc_access`. Chat, knowledge, clients, people, home, and teams reads used by the SPA are ACL-scoped. Reviews, tabular, workflows, drafting, Word, caselaw, and audit are behind the same dependency.
- **Residual:** `document_download` returns a file from `{object_store_root}/generated` when the filename starts with the requested id, **before** `_check_doc_access`. A caller who can hit the API can retrieve those generated files without a matter check.
- **Required outcome:** ACL (and tenant, once it exists) before any bytes leave the process, including generated artefacts. Negative tests for that branch. Keep the unprotected-route inventory as a CI failure.

### P0-03 — No enterprise tenant isolation

- **Evidence:** `members`, `clients`, `matters`, and `documents` in `app/db/schema.sql` have no tenant key. `firm_profile.tenant_id` and `upload_batches.tenant_id` do not isolate the corpus. No `ENABLE ROW LEVEL SECURITY` in the schema or migrations.
- **Impact:** One database is one firm. A filter bug, cache key, or operator query has no second wall.
- **Required outcome for a shared platform:** tenant on every business, search, audit, queue, cache, and object key; RLS with a transaction-local tenant. **Required outcome for the first pilot:** a dedicated account, database, bucket, and key per firm, so the missing column is not the only control. Do not start multi-firm SaaS on this schema.

### P0-04 — Production auth is an API key, and dev auth is still header trust

- **Was:** Auth defaulted off, `.env` was ignored, missing identity was admin, key vault had a fallback secret, and production would boot that way.
- **Now:** `settings.production_problems()` blocks boot when `ENV=production` and auth is off, CORS is `*`, the source-token secret or MinIO secret is the default, ingest roots are empty, or `DATABASE_URL` contains `legal:legal@`. Key lookup no longer swallows database errors.
- **Still true in development:** `AUTH_ENABLED` defaults false. An absent `X-Member-Id` is anonymous admin and the ACL clause allows it. That is acceptable only on a machine with no client files.
- **Still true when auth is on:** the browser holds `X-Api-Key` (see `frontend/src/api/client.ts` and `AppContext`). There is no HttpOnly session, no CSRF story, no IdP, no MFA of our own, no key rotation UI.
- **Required outcome:** Firm OIDC (Entra or Okta). HttpOnly session cookie. Deny header trust whenever auth is on. Secrets from a manager, not from a file in the image.

### P0-05 — Word task pane still writes API text into HTML

- **Was:** The old SPA used `innerHTML` for highlighted document bodies, and CORS was wide open.
- **Now:** The React chat renderer does not inject HTML. CORS is an allow-list. The SPA handler cannot escape `static/`.
- **Residual:** `static/word-taskpane.html` assigns search results to `innerHTML`. `static/_legacy/app.js` still contains the old highlighter. Neither is the main app; both are inside the tree the container copies to `static/`.
- **Required outcome:** Stop shipping the legacy bundle in the image, or serve it only if a review says it is inert. Render Word-pane results as text nodes. Add a CSP at the edge before any lawyer session exists.

### P0-06 — Upload and sync are not safe for a firm library

- **Evidence:** `POST /api/uploads/batches` reads every file with `await uf.read()` and holds the bytes in the request. No size cap, MIME allow-list, or malware scan is on that route. `POST .../run` processes the batch in the API process. Source connectors remain the Phase-0 `FakeConnector`; real OAuth providers are not shipped. Sync routes now require a member, which closes the old “no auth” hole and does not make the connector real.
- **Impact:** Memory exhaustion and malware ingress on upload; a sold “SharePoint connector” would be false.
- **Required outcome:** Direct-to-object-storage upload, size and count limits, content checks, quarantine, checksums, and a worker queue. One real Microsoft Graph connector before any paid sync claim, with source ACL stored beside matter ACL.

## High-priority work before an enterprise pilot (P1)

1. **Identity.** OIDC for the design partner’s IdP. Retire API-key-in-local-storage as the lawyer login. Keep API keys for service callers. SCIM can wait until a second firm; deprovisioning still has to be written down for the first firm.
2. **Close the generated-file download hole** and add a regression test (P0-02 residual).
3. **Dedicated silo design,** even for one tenant: private Postgres, private Redis, private bucket, TLS, WAF, secrets manager, backup, one restore rehearsal, written RPO/RTO.
4. **Audit stream.** Append-only events for sign-in, retrieval, download, prompt, answer, export, and admin change. The manifest signer is not that stream.
5. **AI terms.** In-region Bedrock or the firm’s contracted endpoint, no-train / no-retention in the contract, a token budget, and the rate limit already in `app/resilience/rate_limit.py` turned up to that budget. Do not flip retrieval embeddings to Bedrock without a re-embed and an eval.
6. **Quality gate.** Keep the Harbour evals. Add a written acceptance bar for the pilot (citation precision, abstention, permission denial, latency). CI today does not run `evals/retrieval_eval.py`.
7. **Upload hardening** sufficient for the files the pilot will actually ingest (manual/batch), before any connector.
8. **Supply chain.** Lock what production installs, publish an SBOM, and record licenses in `docs/legal/DEPENDENCY_AUDIT.md` before adding packages.

## Target architecture

First production shape is a **dedicated firm silo**, not pooled multi-tenant SaaS.

```text
Firm user
  -> WAF + TLS -> API (stateless) + built SPA
  -> firm IdP (OIDC) -> member + matter ACL
  -> PostgreSQL (pgvector) in a private subnet
  -> private object storage for originals
  -> Redis for cache and locks only
  -> workers: ingest, embed, sync
  -> in-region model endpoint (no-train contract)

Operators -> break-glass, audited
```

Pooled RLS multi-tenancy is a later product. AWS documents that a partition key alone is not isolation; Azure treats tenancy as a spectrum. Until RLS exists and is tested, the isolation control is a separate account, database, bucket, and key per firm.

| Concern | AWS | Azure |
|---|---|---|
| Edge | CloudFront or ALB + WAF | Front Door or Application Gateway + WAF |
| Compute | ECS Fargate: `api`, `ingest`, `embed`, `sync` | Container Apps, same four processes |
| Identity | Customer IdP via OIDC | Entra ID, Conditional Access for MFA |
| Database | RDS/Aurora PostgreSQL 16, pgvector, Multi-AZ | PostgreSQL Flexible Server, zone redundant |
| Objects | S3, versioning, KMS | Blob, versioning, Key Vault CMK |
| Secrets | Secrets Manager | Key Vault |
| Models | Bedrock in-region | Azure OpenAI in-region when the firm requires it |
| Delivery | GitHub Actions OIDC → registry → Terraform | Same pipeline, Azure module |

Do not promise active/active across AWS and Azure. Ship one container and two modules; run the first firm in one region.

## Scaling plan

| Stage | Target | Gate |
|---|---|---|
| 0 — Internal | Harbour corpus, demo seed, developer Compose | No client files. P0 residuals above stay lab-only. |
| 1 — Design partner | One firm, one region, multi-AZ data plane | IdP, private network, durable ingest for the agreed corpus, backup restore rehearsed, SLOs written. |
| 2 — Commercial | Further dedicated silos, or a pooled platform only after RLS | Per-firm quotas, DPA, admin, pen test. |
| 3 — Large corpus | 1,000+ documents/matter, ~100k pages | Load test evidence. Split embed and ingest workers. Do not add Kafka, Neo4j, or a second vector database on a hunch. |

Inside one firm, scale API replicas, ingest workers, and embed workers separately. A second firm gets a second stack.

## Release gates

Production (a firm’s documents, under a contract) is allowed only when:

1. P0-02 residual, P0-04 IdP, P0-05 legacy HTML, and P0-06 upload controls are re-tested, including a cross-matter denial test.
2. A clean environment comes up from IaC; rollback and restore meet a written RPO/RTO.
3. A pen test covers the API, the SPA, storage, and the cloud configuration; high and critical findings are closed or explicitly accepted.
4. Counsel has a compliance path (SOC 2 timeline, privacy, residency). Do not claim a report that does not exist.
5. On-call, severity definitions, and an incident note exist.
6. The pilot corpus clears the signed retrieval, grounding, permission, and latency bar.
7. MSA, DPA, subprocessors, support hours, and AI data-use terms are signed.

## Recommended sequencing

**Now:** fix the generated-file download bypass; remove or isolate `static/_legacy` and the Word pane HTML injection; keep `ENV=production` as the only shape that can see real files.

**Next:** OIDC session, dedicated-silo IaC for one cloud, backups and one restore, workerised ingest with a size limit, audit events for ask/download/login.

**Then:** one design partner, manual or batch ingest, Bedrock (or Azure OpenAI) under a no-train contract, eval plus a small load test.

**After the first firm is stable:** a real Graph connector, admin sync health, and only then library / tabular / workflow / Word product work. Record Mike-inspired features in `docs/legal/IP_ORIGIN_RECORD.md` before coding them. Mike stays product research under the AGPL clean-room rule.

## Verification record (this revision)

Checked in source, not re-run as a full suite in this pass:

- `docker-compose.yml` defines `postgres`, `redis`, profile `minio`, and profile `api`.
- `Dockerfile` builds the SPA and runs as a non-root user with `ENV=production`.
- `.github/workflows/ci.yml` runs migrate, `seed_ci_minimal`, `seed_demo`, the four contract test modules, `tsc --noEmit`, and `npm run build`.
- `app/api/main.py` confines `/ui` to `static/`, applies the CORS allow-list, and mounts product routers with `resolve_member`.
- `app/config.py` `production_problems()` matches the boot refusal described above.
- `document_download` still serves `generated/` matches before `_check_doc_access`.
- `uploads.py` still buffers full uploads.
- `schema.sql` core entities still have no tenant column and no RLS.

The 21 Sep note “119 passed” is historical. The 24 Sep audit recorded `pytest tests/` at **492 passed, 1 failed** before plans 01–06; plan 06’s done-when is a fully green `pytest tests/`. Re-run and publish that number in CI before calling the suite green. This review does not claim a new pass count.
