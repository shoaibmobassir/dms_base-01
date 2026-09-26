# Enterprise Production Readiness Review

**Date:** 2026-09-24 (replaces the 2026-09-21 assessment)  
**Audience:** Product, engineering, and go-to-market for selling DMS knowledge base to enterprise law firms  
**Deployment targets:** AWS and Azure  
**Status:** Production readiness assessment (not an implementation plan)

**Related docs:**

| Doc | Role |
|-----|------|
| `legal-memory-retrieval/PRODUCTION_READINESS_REVIEW.md` | Engineering blockers, with file-level evidence |
| `legal-memory-retrieval/docs/production-plan/` | Plans 01–06 done; 07 hardening in progress (OIDC deferred) |
| `legal-memory-retrieval/docs/production-plan/AUDIT.md` | 2026-09-24 codebase audit the plans closed |
| `firmos_production_actionable_plan.md` | FirmOS domain and phase plan, with a 24 Sep status overlay |
| `legal-memory-retrieval/docs/ui-roadmap/00_ROADMAP.md` | Next UI (matter workspace, viewer, tools) — plan only |
| `docs/mike-vs-dms-feature-gap-audit.md` | Product capability gap vs Mike (20 Sep 2026; not re-scored here) |
| `docs/universal-document-sync-engine-plan.md` | Connector / sync substrate plan |
| `legal-memory-retrieval/docs/legal/IP_ORIGIN_RECORD.md` | Provenance for Mike-inspired features |
| `.cursor/rules/agpl-cleanroom.mdc` | Mandatory clean-room protocol |

---

## 0. Clean-room notice

Mike at `/Users/shoaibmobassir/Desktop/Experiments/Legal_Maal /mike` is **AGPLv3**. Capability gaps listed here are **product-research outcomes only**.

Identity, connectors, audit, and deployment packaging are ordinary enterprise requirements. Design and implement them independently. Do **not** port Mike schema, screens, APIs, tests, or connector code. Record any Mike-inspired feature in `IP_ORIGIN_RECORD.md` before coding.

This document is an engineering readiness assessment, **not legal advice**.

---

## 1. Executive verdict

**This is still not ready to sell as a full legal AI workspace, and it is still not ready to put a firm's client files on AWS or Azure.**

It is closer to a **private pilot of firm memory** than it was on 21 September: the lawyer UI is a real SPA, auth can be turned on with API keys, and the process will not boot in production with development secrets. The controls a firm’s security review will ask for — their IdP, a private network, backups, a tenant boundary, a connector, a DPA — are not in the repo.

| Dimension | Verdict |
|-----------|---------|
| Retrieval / firm memory | Strong enough to support a **private pilot** of the core loop |
| Product surface (library, tabular, workflows, Word, settings) | Pruned to what the API can back. Chat/ask/matters/documents are usable. Workspace features in the UI roadmap are unbuilt |
| Production security / identity / isolation | **Open** — API keys and matter ACL, no IdP, no tenant RLS |
| Multi-cloud deployability | Container and Compose exist. **No** AWS/Azure IaC, runbooks, or firm-grade network |
| Commercial readiness (DPA, SOC 2, subprocessors, exit) | **Absent** |

**What to sell first:** a dedicated **firm-memory deployment** (ACL-filtered retrieval + cited ask/chat over the firm's records), hosted as a **per-firm silo** on AWS or Azure.

**What not to promise in the first contract:** firm library, templates, durable tabular review, workflow catalog, production Word add-in, Microsoft 365 sync, MCP connectors, or self-serve signup/MFA as our product.

The 20 Sep 2026 Mike gap audit (41 absent, 29 partial, 2 narrower, 0 full parity) has **not** been re-counted. Since that audit the SPA dropped pages that only rendered empty states or hard-coded copy, and chat gained a real session/citation loop. That is a smaller, truer surface, not parity.

---

## 2. What the product is now

Mike, as researched, is a full legal AI workspace: auth, multi-user org, document library, project workspaces, assistant, workflows, tabular review, settings, research UX, Word add-in, and a packaged self-hosted stack.

DMS knowledge base is a **retrieval-first firm memory system** with a lawyer SPA on top:

- Hybrid ACL-filtered retrieval, evals, Ask and Chat (backend and UI)
- Matter, client, document, people, deadline, and argument browsing against Postgres
- Phase-0 sync substrate (fake connector)
- Bedrock as an optional answer provider; MiniLM remains the retrieval embedder

### 2.1 What moved since 21 September

| Area | Then | Now |
|------|------|-----|
| Lawyer UI | Static SPA behind the chat backend; demo personas | Vite React app at `/ui`: Home, Ask, Chat, Matters, Documents, Clients, People, Calendar, Arguments, Settings. Data from the API. Persona switch only while auth is off |
| Chat | Backend ahead of the UI | Sessions, streaming, stop, configured model list, citation titles, starter questions (production plan 05) |
| Auth | Header trust; `.env` flag ignored; no `api_keys` table | Flag is a real setting. API keys work. Production refuses auth-off and default secrets. Login is still an API key in browser storage. OIDC is deferred |
| Routes | Download and several routers had no member check | Product routers require a member. Matter ACL on the SPA’s read paths. One generated-file download branch still runs before the ACL check |
| Delivery | Compose file did not parse | Compose is valid. Dockerfile. CI for migrate, seed, contract tests, and the frontend build |
| Demo data | Hard-coded firm name, empty deadlines, no restricted matters in data | `firm_profile`, `court_deadlines`, `client_notes`, seeded ethical wall |
| Models | Router/KeyVault code only | Bedrock chat/completions path when a bearer token is set. Embeddings stay MiniLM unless explicitly switched and re-embedded |
| Fake product pages | Many routes with no backend | Removed (projects, activity-as-audit, precedents literals, staffing, and the rest of the prune list) |

### 2.2 Still not a shippable enterprise surface

| Area | What exists | Still missing for enterprise |
|------|-------------|------------------------------|
| Chat | Session rail, SSE, citations, stop, model list | Firm IdP login; the matter-scoped workspace in `docs/ui-roadmap/` (plan only) |
| Documents | List, detail, version history, download API | Industry-grade viewer, page rendition, citation highlight on the page the lawyer sees |
| Tabular / workflows | Server routes, now behind auth | Durable product UI, sharing, review chat. Do not demo them as the product |
| Word | Handoff API + `static/word-taskpane.html` | Full add-in. The task pane still assigns results with `innerHTML` |
| Sources | Phase-0 tables + FakeConnector | Real OAuth, incremental sync, Settings connector UX |
| Auth | API keys, production boot guard | SSO, MFA via the IdP, HttpOnly session, SCIM, org onboarding |
| Audit | Manifest signer pieces | Customer-exportable stream of sign-in, retrieval, download, export, admin |
| Tenancy | Single-firm schema; `tenant_id` on firm profile and upload batches | Tenant on every core row, or (for v1) a dedicated stack per firm |

**Rule:** a router, a seed row, or a fake provider is not a checkmark.

### 2.3 Strengths to keep in the pitch

- Eval-gated hybrid retrieval (BM25 + vector + metadata + graph + fusion + cross-encoder)
- Hard matter scope
- ACL before rank
- Retrieval observability / diagnose tooling
- A UI that no longer invents matters, people, or deadlines

---

## 3. What is already built

### 3.1 Retrieval core — DONE for a pilot

- Hybrid engine v2, fusion policy `p55_repair_ce_protect`, hard matter scope
- ACL filtered in SQL before ranking
- MiniLM 384-d behind `app/embeddings/factory.py` (Bedrock embedder is opt-in and requires a re-embed)
- Eval gates and CHANGELOG discipline
- Lab corpus on the order of ~42k embedded chunks (research scale, not a capacity proof)

### 3.2 Answers and chat — DONE for an internal pilot loop

- `POST /ask` with citations from retrieved ids
- Chat sessions owned by the caller, tools, SSE, citation verification
- SPA: session list, streaming, stop, citation panel, model chosen from configured providers
- Rate limit helper on answers and chat messages

### 3.3 Document / matter domain — PARTIAL PRODUCT

Schema and APIs exist for members, clients, matters, permissions, documents, chunks, versions, upload batches, court deadlines, client notes, firm profile, review-oriented tables, and Phase-0 source tables.

The SPA browses that data. It does not yet provide the matter workspace (chat, drafts, research, and notes as tabs) described in the UI roadmap.

Object storage is local disk or optional MinIO. It is not a firm-managed bucket with versioning and a customer-managed key.

### 3.4 Sync substrate — PHASE 0 ONLY

Tables, sync engine, permission rows, `FakeConnector`. No production OAuth, webhook, or connector screen.

### 3.5 Local stack (not production)

| Service | Notes |
|---------|--------|
| Postgres 16 + pgvector | `:55432`, dev user/password `legal` / `legal` |
| Redis 7 | `:6380` |
| MinIO | profile `object-store`, `minioadmin` / `minioadmin` |
| API + SPA | profile `app`, multi-stage image, non-root, `ENV=production`, refuses default secrets |

Auth off (the default) trusts `X-Member-Id`. Auth on requires `X-Api-Key` mapped through `api_keys`. `ENV=production` will not start with auth off.

CI (`.github/workflows/ci.yml`) covers the contract tests and the frontend build. It does not deploy anywhere.

---

## 4. What must exist to make this live

Three contracts. Do not collapse them into “build the rest of the workspace.”

### 4.1 Private pilot gates (design-partner firm, no invoice)

| # | Gate | Required | Current state | Status |
|---|------|----------|---------------|--------|
| 1 | Retrieval | ACL-filtered hybrid search over firm records | Engine v2, matter scope, evals | **Closed** |
| 2 | Identity | Firm users sign in via their IdP; no trusted header in prod | API keys work; production refuses auth-off; browser stores the key; no OIDC | **Open** |
| 3 | Isolation | One firm cannot see another firm's documents | Matter ACL inside one DB; no tenant / network silo | **Open** |
| 4 | Network | Private subnets, TLS, DB not public, WAF | Compose still publishes Postgres and Redis | **Open** |
| 5 | Data plane | Managed Postgres + pgvector Multi-AZ; S3 or Blob for bytes | Local volume; MinIO optional; container exists | **Open** |
| 6 | Recovery | Automated backups + rehearsed restore; written RPO/RTO | None | **Open** |
| 7 | Secrets | Credentials in a vault, rotated | Boot guard rejects known dev defaults when `ENV=production`. No vault integration | **Open** |
| 8 | Lawyer UI | Sign in, ask/chat, open a citation | SPA does this against the seeded DB with an API key or a dev persona. Viewer and IdP login are not done | **Partial** |
| 9 | Models | In-region endpoint, no-train contract, keys in a vault | Bedrock client exists; no contract, no region pin, embeddings still local MiniLM | **Open** |
| 10 | Operations | IaC, health, alerts, migrations, on-call | Readiness probe, Dockerfile, contract CI. No account stack, alerts, or release pipeline | **Open** |

**Pilot score: 1 closed, 1 partial, 8 open.** Gate 8 does not close the pilot by itself.

### 4.2 First paid firm gates (before invoice)

| Area | Required | Current state |
|------|----------|---------------|
| Connector | SharePoint or OneDrive incremental sync; source ACL beside matter ACL | Fake connector only |
| Admin | Map IdP groups to matters; disconnect source; last sync / errors | Members are corpus data. Settings is not an admin console |
| Audit | Immutable log of sign-in, retrieval, export, admin changes; customer export | Manifest signing pieces only |
| Capacity | Firm page count: ingest, embed, ask under a written latency budget | FirmOS target 100k pages; lab is tens of thousands of chunks on one process. No load-test result |
| Commercial | DPA, subprocessor list, region, support hours, RPO/RTO, pen test | Not in the repo |

Do **not** claim SOC 2 Type II. Offer a pen test, an architecture pack, and a SOC 2 timeline.

### 4.3 After the first firm is live

Library, templates, durable tabular review, workflow catalog, Word add-in, external research UX, self-serve signup, MCP. The UI roadmap is the backlog for the workspace. It does not make the system deployable.

### 4.4 Requirements that still apply

1. Account security via the firm IdP. MFA via Conditional Access, not a password we store.
2. First customers on a dedicated stack until RLS is real and tested.
3. Exit: bucket export of originals plus a database dump, and a destroy confirmation.
4. Chat UX for the pilot is largely in place; the matter workspace and the document viewer are the next product work, after the silo.
5. One real cloud-drive connector before a paid firm that will not upload by hand.
6. Operator runbooks: auth, storage, secrets, migrations, release, restore.
7. Browser tests on login, ask/chat, citation open, and a restricted-matter denial. CI currently typechecks and builds; it does not run Playwright against a live API.

---

## 5. How a firm should be hosted

### 5.1 Dedicated silo first

**First customers get their own stack.** A bug in one SQL filter must not be the only wall between two firms. Ethical walls stay inside the firm. Network and account isolation sit between firms.

Shared multi-tenant control plane can come later. Do not start with one shared Postgres for multiple firms.

### 5.2 Target topology

| Concern | AWS | Azure | Why this shape |
|---------|-----|-------|----------------|
| Edge | ALB + WAF + ACM | Application Gateway or Front Door + WAF | TLS terminates here |
| App | ECS Fargate: `api`, `ingest`, `embed`, `sync` | Container Apps or AKS, same four services | Embedding and sync stay off the request |
| Database | RDS or Aurora PostgreSQL 16, pgvector, Multi-AZ | PostgreSQL Flexible Server, zone redundant | Same schema; do not replace pgvector in v1 |
| Files | S3, versioning, KMS CMK | Blob, versioning, Key Vault CMK | Bytes stay out of Postgres |
| Cache | ElastiCache Redis | Azure Cache for Redis | Cache and locks only |
| Identity | OIDC to the firm’s Okta or Entra | Entra ID; Conditional Access for MFA | Do not build signup for v1 |
| Models | Bedrock in-region, or a contracted no-train endpoint | Azure OpenAI in the firm’s region | Contract must forbid training |
| Secrets | Secrets Manager | Key Vault | Rotation is an operator job |
| Audit store | S3 Object Lock | Immutable Blob | Separate from the app database |
| Network | Private subnets, VPC endpoints | Private Link | Postgres, Redis, and objects have no public address |

One Terraform (or equivalent) layout, an AWS module and an Azure module, the same images, firm-specific tfvars. The Dockerfile is the image input. Compose is the developer input.

### 5.3 Service split

| Service | Responsibility |
|---------|----------------|
| `api` | Authn/z, retrieval, ask, chat SSE, admin APIs. No heavy embed in-request |
| `ingest` | Upload/batch parse, normalize, write docs and versions |
| `embed` | Chunk embed workers (MiniLM 384-d unless a measured switch says otherwise) |
| `sync` | Connector delta, download, permission sync, when a real provider exists |

Redis for queues and locks. Postgres for job truth. Kafka and Neo4j stay out until a sprint gate says otherwise.

### 5.4 What Compose must not become

The file is valid and can build the app image. It is still a developer baseline: published database ports, known dev passwords, auth off unless a production env file says otherwise, optional object store, no WAF, no backups, no IdP.

---

## 6. Scaling

| | Today (lab) | First firm |
|--|-------------|------------|
| Topology | One API process; MiniLM on CPU; one Postgres; Redis; optional MinIO; container available | Dedicated silo; API replicas; worker pools |
| Auth | Off, or API key | Firm OIDC |
| Scale unit | Research corpus (~42k chunks) plus a small demo seed | Design against the FirmOS targets below, then measure |
| Proof | Eval suites; CI contract tests | Load test + restore drill |

Design targets (not yet measured):

- 1,000+ documents per matter
- ~100 pages per document on average
- 100,000+ pages in a review corpus
- Nested folders, immutable versions, findings anchored to source evidence
- Partial failure and retry, full auditability

| Load | What breaks first | What to do |
|------|-------------------|------------|
| Many lawyers asking at once | Single API process and in-process reranker | API replicas; cross-encoder as its own service with a candidate cap |
| A large library lands | Embedding on the request path; CPU MiniLM | Queue downloads; separate embed workers |
| Chunks grow past the lab | One HNSW index, one pool | Keep 384-d MiniLM; add a pooler; partition only after a measured index problem |
| Second firm | Shared database | New account, key, bucket, and database |
| Model cost | Unbounded chat | The rate limiter plus a contracted monthly cap |

**Scale by adding a firm stack.** Inside a firm, scale services and workers. Do not retune global fusion without a typed ablation. Do not change embedding dimension without a schema change and a re-embed.

---

## 7. How enterprise sales and firm handling work

### 7.1 Security questionnaire — honest answers

| They will ask | Answer you can give today | Answer after pilot gates |
|---------------|---------------------------|--------------------------|
| Where does data live? | A developer machine or a dev server | Their chosen AWS or Azure region, dedicated account |
| Who can sign in? | A dev member header, or an API key if auth is on | Their Entra or Okta groups; MFA via Conditional Access |
| Ethical walls | Matter ACL before ranking, in one database, with a seeded restricted set for tests | Same rule, and the stack contains only their firm |
| Do you train on our files? | No production model contract. Bedrock is optional code | Written no-train terms; subprocessor list |
| Can we leave? | No export product | Bucket export of originals + database dump; offboarding runbook |
| SOC 2 | No | Still no Type II for early design partners; pen test + architecture pack + a timeline |
| SharePoint | Not connected | Not in the pilot; required before a paid firm that will not upload by hand |
| Is the UI real? | Yes, against our corpus: ask, chat, matters, documents | Same loop on their corpus, after IdP login |

### 7.2 Handling model

1. Dedicated deployment; the firm chooses AWS or Azure.
2. Their IdP only; groups map to matter membership.
3. Originals in their bucket; index and metadata in their Postgres.
4. Matter ACL before retrieval; operator access is break-glass and audited.
5. In-region model; contractual no-train; keys in a vault.
6. Written support hours and an on-call owner for the silo.
7. Exit: export objects and the database; destroy confirmation; delete keys.
8. Migrations and model upgrades are release jobs with rollback.

### 7.3 Commercial pack (not in-repo)

DPA, subprocessor list, architecture diagram (AWS and Azure), controls matrix, pen test or a scheduled date, RPO/RTO evidence, residency statement, support SLA, AI disclaimer (retrieval is not legal advice), offboarding checklist.

### 7.4 Packaging

| Package | Includes | Excludes until built |
|---------|----------|----------------------|
| **Firm Memory Pilot** | Dedicated stack, OIDC, retrieval, ask/chat UI, manual/batch ingest, eval baseline, support hours | SharePoint, Word, tabular, workflows, library |
| **Firm Memory Production** | Pilot + one Graph connector, admin sync health, audit export, load-tested capacity, pen test, DPA | Full workspace parity |
| **Workspace (later)** | Library, tabular, workflows, Word, research UX, per the UI roadmap | — |

Sell a column only when its gates are closed. Gate 8 being partial means the pilot package still needs IdP login and a citation the lawyer can open on their own documents, on the dedicated stack.

---

## 8. Order of work

1. **Close the remaining app holes that would leak a file:** generated-file download before ACL; legacy HTML injection in the Word pane; uploads buffered in the API.
2. **Dedicated AWS or Azure stack** — private network, managed Postgres with pgvector, object storage, Redis, secrets, backups, four services.
3. **OIDC** to Entra and Okta; retire API-key browser login for lawyers; map groups to matter membership.
4. **Prove the lawyer loop on that stack:** login, ask/chat, open citation, download the source they are allowed to see, fail closed on a restricted matter.
5. **Embeddings and ingest off the API process;** alerts on failure, queue depth, and backup age.
6. **For the paid firm, one real connector** (Microsoft Graph if they live in Microsoft 365).
7. **Then** the UI roadmap: matter workspace, document viewer, tools.

For every Mike-inspired item: a clean requirement and an `IP_ORIGIN_RECORD` entry before implementation.

---

## 9. Suggested definition of “live”

### 9.1 Private pilot

- [ ] Firm data only in a dedicated AWS or Azure account
- [ ] OIDC login; `AUTH_ENABLED=true`; header trust disabled; API keys not the lawyer session
- [ ] TLS, WAF, private DB/Redis/object storage
- [ ] Backups on; restore rehearsed once; RPO/RTO written
- [ ] Secrets only in Secrets Manager or Key Vault
- [ ] Lawyer can complete: login → ask/chat → open citation → view the allowed source
- [ ] Generated and original downloads both enforce matter ACL
- [ ] Model endpoint in-region with no-train terms
- [ ] Health checks, alerts, on-call owner
- [ ] Migration job documented
- [x] Retrieval engine and cited ask/chat exist (lab)
- [x] SPA for that loop exists (lab, API key or dev persona)
- [x] Production boot guard rejects auth-off and default secrets

### 9.2 First paid firm

All pilot items, plus:

- [ ] Microsoft Graph (or Drive) connector with incremental sync and disconnect
- [ ] Source ACL and matter ACL both enforced in retrieval SQL
- [ ] Admin can see connection health, last sync, and errors
- [ ] Immutable audit export
- [ ] Load test passed against the contracted page/QPS budget
- [ ] Pen test completed or scheduled, with findings triage
- [ ] Signed DPA, subprocessor list, support SLA
- [ ] Offboarding runbook tested once on a staging silo

### 9.3 Explicit non-goals for first live

- Mike product parity
- Self-serve multi-tenant SaaS
- SOC 2 Type II in hand
- Word add-in as a product
- Tabular review and workflows promoted without a durable schema and a UI
- Kafka or Neo4j

---

## 10. Risks if we ship too early

| Risk | Why it matters | Mitigation |
|------|----------------|------------|
| Header-trust or API-key-in-the-browser treated as SSO | A copied key or a dev deploy impersonates a lawyer | OIDC only on the silo; HttpOnly session; production boot guard stays |
| Generated-file download before ACL | Bytes leave without a matter check | Fix and regression-test before any client file is stored |
| Shared database for two firms | A filter bug is an existential leak | Per-firm silo for v1 |
| Fake connector described as SharePoint | Trust destruction | One real Graph path before a paid sync claim |
| Bedrock embeddings flipped without a re-embed | Silent retrieval collapse | Factory default stays MiniLM; eval before any dimension change |
| Claiming SOC 2 or a ready export | Procurement exposure | Sell documented controls only |
| Copying Mike for speed | AGPL / IP exposure | Clean-room protocol |

---

## 11. Summary

| Question | Answer |
|----------|--------|
| What is done? | Retrieval, cited ask/chat (API and SPA), single-firm matter/document model, demo seed, API-key auth, production boot guard, container, contract CI |
| What is missing for a pilot? | Firm IdP, dedicated network and data plane, backups, vault-backed secrets, the download ACL residual, workerised ingest, on-call |
| What is missing for a paid firm? | A real connector, admin, audit export, capacity proof, commercial pack |
| How do we scale? | New firm = new stack; inside a firm = API replicas and ingest/embed/sync workers |
| How is a firm handled? | Dedicated AWS or Azure deployment, their IdP, matter ACL, no-train models, exit via bucket and database export |
| What do we sell first? | Firm Memory Pilot, then Firm Memory Production. Workspace parity waits on the UI roadmap |

---

*End of review. Re-run when the pilot IdP and silo exist, and again when the first paid connector ships.*
