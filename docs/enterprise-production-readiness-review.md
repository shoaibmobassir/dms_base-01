# Enterprise Production Readiness Review

**Date:** 2026-09-21  
**Audience:** Product, engineering, and go-to-market for selling DMS knowledge base to enterprise law firms  
**Deployment targets:** AWS and Azure  
**Status:** Production readiness assessment (not an implementation plan)

**Related docs:**

| Doc | Role |
|-----|------|
| `docs/mike-vs-dms-feature-gap-audit.md` | Product capability gap vs Mike (clean-room research) |
| `docs/universal-document-sync-engine-plan.md` | Connector / sync substrate plan |
| `firmos_production_actionable_plan.md` | Broader FirmOS domain and phase plan |
| `legal-memory-retrieval/docs/assistant_chatbot_deep_gap_analysis.md` | Chat UI deep gaps |
| `legal-memory-retrieval/docs/legal/IP_ORIGIN_RECORD.md` | Provenance for Mike-inspired features |
| `.cursor/rules/agpl-cleanroom.mdc` | Mandatory clean-room protocol |

**Interactive version:** Cursor canvas  
`/Users/shoaibmobassir/.cursor/projects/Users-shoaibmobassir-Desktop-Experiments-Legal-Maal-DMS-knowledge-base/canvases/enterprise-production-readiness.canvas.tsx`

---

## 0. Clean-room notice

Mike at `/Users/shoaibmobassir/Desktop/Experiments/Legal_Maal /mike` is **AGPLv3**. Capability gaps listed here are **product-research outcomes only**.

Identity, connectors, audit, and deployment packaging are ordinary enterprise requirements. Design and implement them independently. Do **not** port Mike schema, screens, APIs, tests, or connector code. Record any Mike-inspired feature in `IP_ORIGIN_RECORD.md` before coding.

This document is an engineering readiness assessment, **not legal advice**.

---

## 1. Executive verdict

**This is not ready to sell as a full legal AI workspace, and it is not ready to put a firm's client files on AWS or Azure.**

| Dimension | Verdict |
|-----------|---------|
| Retrieval / firm memory | Strong enough to support a **private pilot** of the core loop |
| Product surface (library, tabular, workflows, Word, settings) | Far behind a shippable enterprise product |
| Production security / identity / isolation | **Open** — cannot pass a law-firm security review today |
| Multi-cloud deployability | App exists; **no** AWS/Azure IaC, runbooks, or firm-grade stack |
| Commercial readiness (DPA, SOC 2, subprocessors, exit) | **Absent** |

**What to sell first:** a dedicated **firm-memory deployment** (ACL-filtered retrieval + cited ask/chat over the firm's records), hosted as a **per-firm silo** on AWS or Azure.

**What not to promise in the first contract:** firm library, templates, durable tabular review, workflow catalog, production Word add-in, MCP connectors, or self-serve signup/MFA as our product.

**Bottom line:** Of ten private-pilot gates, **one is closed** (retrieval). Of 72 Mike-comparison capability rows in the 20 Sep 2026 gap audit: **41 absent, 29 partial, 2 present but narrower**, **0 full parity**.

---

## 2. What the gap audit actually says

Mike is a **full legal AI workspace**: auth, multi-user org, document library, project workspaces, assistant, workflows, tabular review, settings (BYOK/models/connectors/MFA), CourtListener research UX, Word add-in, and a packaged self-hosted stack.

DMS knowledge_base is strongest as a **retrieval-first firm memory system**: hybrid ACL-filtered retrieval, evals, Ask/Chat backends, matter/project/document APIs, Phase-0 sync substrate.

Many Mike-like *names* appear in DMS (tabular, workflows, caselaw, Word, BYOK, sources). Most are **not** a complete product loop (UI + durable persistence + real providers + auth).

### 2.1 Capability counts (Mike → DMS audit, 20 Sep 2026)

| Status | Count | Meaning |
|--------|------:|---------|
| Absent | 41 | No meaningful equivalent |
| Partial | 29 | Backend/library/plan exists; not a shippable product surface |
| Present (narrower) | 2 | Exists with smaller scope / weaker UX (matters/clients/people/teams browsing; tasks) |
| Full product parity | 0 | — |

### 2.2 Gap by product area

| Area | Absent | Partial | Present (narrower) |
|------|-------:|--------:|-------------------:|
| Platform / identity / tenancy | 8 | 4 | 0 |
| Document library & files | 4 | 3 | 0 |
| Projects / matters / clients | 1 | 3 | 2 |
| Assistant / chat | 2 | 5 | 0 |
| Workflows / playbooks | 6 | 1 | 0 |
| Tabular / matrix review | 5 | 3 | 0 |
| Case law / research | 3 | 1 | 0 |
| Connectors / sync / MCP | 3 | 3 | 0 |
| Word add-in | 5 | 2 | 0 |
| Trust / audit / exports | 1 | 2 | 0 |
| Ops / quality / packaging | 3 | 2 | 0 |

**Rule for reading Partial:** a router, schema table, or fake provider is debt, not a checkmark. In-memory stores, UI-less APIs, FakeConnector, and demo-seeded data do not count as delivered.

### 2.3 “Exists in DMS but not done” (easy to over-count)

| Area | What DMS has today | Still missing for enterprise |
|------|--------------------|------------------------------|
| Chat agent | Sessions, tools, SSE, citation verify | Full chat UI, project assistant, artifact cards |
| Tabular | Service + API + xlsx exporter | Durable schema, matrix UI, sharing, review chat |
| Workflows | 3 YAML playbooks + engine + API | Catalog UI, sync packs, shares, durable runs |
| BYOK / models | KeyVault + model_router | Settings UI, per-user persisted keys/preferences |
| Caselaw | Parser + CourtListener client | Bulk indexes, settings tokens, research UX |
| Word | Handoff API + static taskpane + tracked DOCX generator | Full add-in, in-Word accept/reject, workflows |
| Sources | Phase-0 tables + FakeConnector + sync engine | Real providers, OAuth UX, ACL intersection |
| Projects | Folders, versions, activity, export hooks | Nested assistant/tabular, sharing |
| Auth | API keys + optional `AUTH_ENABLED` | Signup, MFA, sessions, org onboarding, SSO |
| Audit/export | Manifest signer pieces | Full project export UX + security audit stream |

### 2.4 DMS strengths that are *not* Mike gaps (context)

These do **not** close the product or production gaps, but they are real differentiators for a firm-memory pitch:

- Eval-gated hybrid retrieval (BM25 + vector + metadata + graph + fusion + CE)
- Hard matter scope / matter resolver / paraphrase & Harbour benchmarks
- ACL-before-rank as a first principle
- Retrieval observability / diagnose tooling
- Companion plans (`paraphrase-resolution-experiments.md`, sync plan)

---

## 3. What is already built (keep and productize)

These are the assets that justify a **private firm-memory pilot**, not a workspace clone.

### 3.1 Retrieval core — DONE for pilot

- Hybrid engine v2 with fusion policy (`p55_repair_ce_protect` default) and hard matter scope
- ACL filtered in SQL before ranking
- Local MiniLM 384-d embeddings behind an interface
- Eval gates, diagnose tooling, CHANGELOG discipline
- Lab corpus on the order of ~42k embedded chunks (research scale, not capacity proof)

### 3.2 Answers and chat backend — MOSTLY DONE; UI BEHIND

- `POST /ask` with citations from retrieved ids
- Chat sessions, tools, SSE agent, citation verification
- Frontend chat UX incomplete (session switcher, citation tray, artifact cards — see assistant gap note)

### 3.3 Document / matter domain — PARTIAL PRODUCT

Schema and APIs exist for:

- `members`, `clients`, `matters`, `matter_members`, `permissions`
- `documents`, `chunks`, `relationships`, `arguments`
- `projects`, `project_folders`, `project_activity`
- `document_versions`, `document_blocks`, `version_diffs`
- Ingest: `ingest_jobs`, `ingest_items`, `upload_batches`, `upload_batch_files`
- Review-oriented: `review_jobs`, `findings`, `evidence_anchors`, `annotations`, `document_intelligence`
- Chat: `chat_sessions`, `chat_messages`
- Sync Phase 0: `source_connections`, `source_sync_state`, `source_files`, `source_file_permissions`, `identity_links`

Storage is optional local MinIO (`docker compose --profile object-store`), not a firm-managed bucket.

### 3.4 Sync substrate — PHASE 0 ONLY

- Tables + sync engine + permissions storage + `FakeConnector`
- Plan for Drive / Graph exists in `docs/universal-document-sync-engine-plan.md`
- **No** production OAuth providers, webhook wake, or Settings connectors UX

### 3.5 Local stack today (not production)

From `legal-memory-retrieval/docker-compose.yml`:

| Service | Port / notes |
|---------|----------------|
| Postgres 16 + pgvector | `:55432`, user/password `legal` / `legal` |
| Redis 7 | `:6380` |
| MinIO | optional profile, `:9000` / console `:9001`, `minioadmin` / `minioadmin` |

Auth: `AUTH_ENABLED=false` (default) trusts `X-Member-Id`. When enabled, API keys map to members. No browser sessions, OAuth, MFA, or org onboarding.

API surface includes routers for retrieval, answers, chat, documents, uploads, projects, matters, clients, people, teams, tasks, knowledge, workflows, tabular, caselaw, word, sources, audit, reviews, drafting, search, home, activity, system — many of which are **Partial** product surfaces as scored above.

---

## 4. What must exist to make this live

Treat delivery as **three contracts**, not one “build everything Mike has” backlog.

### 4.1 Private pilot gates (design-partner firm, no invoice)

| # | Gate | Required | Current state | Status |
|---|------|----------|---------------|--------|
| 1 | Retrieval | ACL-filtered hybrid search over firm records | Engine v2, matter scope, evals | **Closed** |
| 2 | Identity | Firm users sign in via their IdP; no trusted header in prod | `AUTH_ENABLED` defaults off; trusts `X-Member-Id`; API keys only when on; no SSO | **Open** |
| 3 | Isolation | One firm cannot see another firm's documents | Matter ACL inside one DB; no tenant / network silo | **Open** |
| 4 | Network | Private subnets, TLS, DB not public, WAF | Compose publishes Postgres/Redis with known passwords | **Open** |
| 5 | Data plane | Managed Postgres + pgvector Multi-AZ; S3 or Blob for bytes | Single local volume; MinIO optional | **Open** |
| 6 | Recovery | Automated backups + rehearsed restore; written RPO/RTO | No backup policy or restore runbook | **Open** |
| 7 | Secrets | Credentials in vault, rotated, not in compose/git | Compose uses `legal`/`legal`, `minioadmin`/`minioadmin` | **Open** |
| 8 | Lawyer UI | Session list, streaming answer, open a citation | Chat backend ahead of SPA | **Open** |
| 9 | Models | In-region endpoint, no-train contract, keys in vault | Router/KeyVault code; no production contract or region pin | **Open** |
| 10 | Operations | IaC for AWS and Azure, health, alerts, migrations, on-call | App metrics/traces exist; no account-level stack or release pipeline | **Open** |

**Pilot score: 1 / 10 closed.**

### 4.2 First paid firm gates (before invoice)

| Area | Required | Current state |
|------|----------|---------------|
| Connector | SharePoint or OneDrive incremental sync; source ACL kept beside matter ACL | Fake connector only; UI cloud-drive buttons are not real OAuth |
| Admin | Map IdP groups to matters; disconnect source; last sync / errors | Members are corpus data, not an admin product |
| Audit | Immutable log of sign-in, retrieval, export, admin changes; customer export | Manifest signing pieces only |
| Capacity | Prove firm's page count: ingest, embed, ask under a written latency budget | FirmOS target 100k pages; measured lab is tens of thousands of chunks on one process |
| Commercial | DPA, subprocessor list, region, support hours, RPO/RTO, pen test | None of the procurement pack exists in-repo |

Do **not** claim SOC 2 Type II. Offer pen test, architecture pack, and a SOC 2 timeline.

### 4.3 After the first firm is live (do not block pilot on these)

| Area | Required | Current state |
|------|----------|---------------|
| Workspace | Library, templates, durable tabular review, workflow catalog, sharing | Tabular/workflow runs in-memory; no product UI |
| Word | Sideloadable task pane: auth handoff, chat, tracked changes | Manifest + static task pane |
| Research | Citation verify in UI; optional bulk indexes; customer research tokens | CourtListener client; no settings/bulk |
| Platform product | Self-serve signup, in-app MFA, MCP connectors, SOC 2 Type II | Absent — first firms should use their IdP for MFA |

**Building workspace features first does not make the system deployable.**

### 4.4 Technology-independent requirements (from gap audit §4) still applying to production

Prioritize for go-live (subset):

1. **Account / session security via firm IdP** — not long-lived secrets in localStorage as the only model; MFA via Conditional Access / IdP policy.
2. **Tenant / org membership** — firm data scoped; first customers via dedicated stack.
3. **Privacy / exit** — export and delete paths per policy (bucket + DB dump for siloed deploy).
4. **Chat UX completeness** — sessions, SSE, citations, sources tray.
5. **Real cloud drive connectors** — OAuth, incremental sync, permission intersection.
6. **Deployment runbooks** — Auth, storage, secrets, migrations, release jobs for operators.
7. **Browser e2e** — critical paths covered (auth, project, chat at minimum for pilot).

Defer until after first paid firm: library/templates product, workflow studio, tabular matrix UI, Word product, MCP, bulk caselaw indexes (unless the contract requires them).

---

## 5. How a firm should be hosted (AWS and Azure)

### 5.1 Commercial topology: dedicated silo, not shared multi-tenant SaaS

**First customers get their own stack.**

Reasons:

- A bug in one SQL filter must not be the only wall between two firms' client files.
- Firms buy region, key ownership, and VPC / subscription isolation.
- Ethical walls (matter ACL) remain necessary **inside** the firm; network + account isolation is the **between-firm** control.

Shared multi-tenant control plane can come later. Do not start with one shared Postgres for multiple firms.

### 5.2 Target topology (same app images, two cloud modules)

| Concern | AWS | Azure | Why this shape |
|---------|-----|-------|----------------|
| Edge | ALB + WAF + ACM | Application Gateway or Front Door + WAF | TLS terminates here; API is not public on `:8000` |
| App | ECS Fargate: `api`, `ingest`, `embed`, `sync` | Container Apps or AKS, same four services | API stays stateless; embedding and sync never run inside the request |
| Database | RDS or Aurora PostgreSQL 16, pgvector, Multi-AZ, RDS Proxy | PostgreSQL Flexible Server, zone redundant, PgBouncer | Same schema; do not replace pgvector with a second DB in v1 |
| Files | S3, versioning, KMS CMK | Blob, versioning, Key Vault CMK | Bytes stay out of Postgres; MinIO does not ship |
| Cache | ElastiCache Redis | Azure Cache for Redis | Cache and locks only; job truth stays in Postgres |
| Identity | OIDC to firm Okta or Entra (not Cognito-as-the-product) | Entra ID; Conditional Access for MFA | Firms already have an IdP; do not build signup/password reset for v1 |
| Models | Bedrock in-region, or contracted no-train endpoint | Azure OpenAI in the firm's region | Azure-native firms will require Azure OpenAI; contract must forbid training |
| Secrets | Secrets Manager | Key Vault | DB, model, and connector tokens; rotation is an operator job |
| Audit store | S3 Object Lock | Immutable Blob | Separate from app DB so a DB admin cannot rewrite history |
| Network | Private subnets, VPC endpoints | Private Link; no public data plane | Postgres, Redis, and object storage have no public address |

**IaC recommendation:** one Terraform (or equivalent) layout with an AWS module and an Azure module; same container images; firm-specific tfvars for region, CIDR, IdP issuer, model endpoint.

### 5.3 Service split (four processes minimum)

| Service | Responsibility |
|---------|----------------|
| `api` | Authn/z, retrieval, ask, chat SSE, admin APIs — no heavy embed in-request |
| `ingest` | Upload/batch parse → normalize → write docs/versions |
| `embed` | Chunk embed workers (MiniLM 384-d); scale independently |
| `sync` | Connector delta/download/permission sync (when real providers ship) |

Redis for queues/locks; Postgres for durable job state (reuse `ingest_jobs` / sync state pattern). Kafka/Neo4j remain out of scope until sprint gates say otherwise.

### 5.4 What Compose must not become

Do not treat the current compose file as a production blueprint:

- Public Postgres/Redis ports
- Known default passwords
- Auth off by default
- Optional object store
- No WAF, no private network, no backups, no IdP

---

## 6. Scaling

### 6.1 Today vs first firm

| | Today (lab) | First firm |
|--|-------------|------------|
| Topology | One API process; MiniLM on CPU in-process; one Postgres; Redis; optional MinIO | Dedicated silo; API replicas; worker pools |
| Auth | Off / header trust | Firm OIDC |
| Scale unit | Research corpus (~42k chunks) | Design against FirmOS targets below |
| Proof | Eval suites | Load test + restore drill |

### 6.2 Design targets (FirmOS plan — not yet measured in production)

- 1,000+ documents per matter/workspace
- ~100 pages per document on average
- 100,000+ pages in a review corpus
- PDFs, DOCX, XLSX and common legal/business files
- Nested folders and matter/client hierarchy
- Multiple immutable document versions
- AI findings anchored to exact source evidence
- Parallel processing with partial failure and retry
- Full auditability

**There is no production load-test result yet.** Treat these as the capacity contract to design and then prove.

### 6.3 What breaks first, and what to do

| Load | What breaks first | What to do |
|------|-------------------|------------|
| Many lawyers asking at once | Single uvicorn process and in-process reranker | Two or more API replicas; cross-encoder as its own service with a candidate cap |
| A large SharePoint library lands | Embedding on the request path; CPU MiniLM | Queue downloads; separate embed workers; batch; GPU only if CPU misses the ingest SLA |
| Chunks grow past the lab corpus | One HNSW index and one connection pool | Keep 384-d MiniLM; add a pooler; partition by matter only after a measured index problem |
| Second and third firm | Shared database and shared Redis | Do not share; new account/subscription, new key, new bucket, new database |
| Model cost spike | Unbounded chat tools | Per-deployment token budget, queue, and a hard monthly cap in the contract |

### 6.4 Scaling principle

**Scale by adding a firm stack, not by sharing one database.**  
Inside a firm, scale **services and workers**, not process count on a laptop.

Do not retune global fusion policy without typed ablations. Do not change embedding dimension without schema + re-embed. Matter scope stays hard; ACL stays in SQL before rank.

---

## 7. How enterprise sales and firm handling work

Procurement will not buy “better retrieval than Mike.” They buy a place **client documents can sit** under controls they already understand.

### 7.1 Security questionnaire — honest answers

| They will ask | Answer you can give today | Answer after pilot gates |
|---------------|---------------------------|--------------------------|
| Where does data live? | A laptop or a dev server | Their chosen AWS or Azure region, dedicated account |
| Who can sign in? | Whoever sends a member header | Their Entra or Okta groups; MFA via Conditional Access |
| Ethical walls | Matter ACL before ranking, in one database | Same rule, plus the whole stack is only their firm |
| Do you train on our files? | No production model contract | Written no-train terms (Azure OpenAI / Bedrock); subprocessor list |
| Can we leave? | No export product | Bucket export of originals + database dump; offboarding runbook |
| SOC 2 | No | Still no Type II for early design partners; pen test + architecture pack + SOC 2 timeline — do not claim the report |
| SharePoint | Not connected | Not in the pilot; required before a paid firm that will not upload by hand |

### 7.2 Handling model for the first sold product

1. **Deal type:** dedicated deployment (AWS or Azure, firm chooses).
2. **Identity:** firm IdP only; map groups → matter membership (and later admin roles).
3. **Data:** originals in their bucket; index and metadata in their Postgres; no cross-firm resources.
4. **Access:** matter ACL before retrieval; operators access via break-glass, audited.
5. **Models:** in-region; contractual no-train / no-retention; keys in their vault or yours under DPA.
6. **Support:** written hours, severity definitions, escalation; on-call for the silo.
7. **Exit:** documented export of objects + DB; destroy confirmation; key deletion.
8. **Change control:** migrations and model upgrades are release jobs with rollback.

### 7.3 Commercial pack to produce (not in-repo today)

- Data Processing Agreement (DPA)
- Subprocessor list (cloud, model, email if any, support tools)
- Architecture & data-flow diagram (AWS and Azure variants)
- Security whitepaper / controls matrix (aligned to SOC 2 / ISO themes even before certification)
- Pen test report (or scheduled date)
- RPO / RTO and backup/restore evidence
- Region and residency statement
- Support SLA
- Acceptable use and AI disclaimer (retrieval/citations are not legal advice)
- Offboarding / exit checklist

### 7.4 Product packaging recommendation

| Package | Includes | Excludes (until built) |
|---------|----------|------------------------|
| **Firm Memory Pilot** | Dedicated stack, OIDC, retrieval, ask/chat UI, manual/batch ingest, eval baseline, support hours | SharePoint, Word, tabular, workflows, library |
| **Firm Memory Production** | Pilot + Graph connector, admin sync health, audit export, load-tested capacity, pen test, DPA | Full workspace parity |
| **Workspace (later)** | Library, tabular, workflows, Word, research UX | — |

Price and sell the middle column only when paid gates are closed.

---

## 8. Order of work

Close the **pilot** column before any firm data leaves a lab. Close the **paid** column before an invoice. Library, tabular, workflows, Word, and MCP wait.

1. **Dedicated AWS and Azure stacks** — private network, managed Postgres with pgvector, object storage, Redis, secrets, backups, four services (`api`, `ingest`, `embed`, `sync`).
2. **Turn dev auth off in that stack** — OIDC to Entra and Okta; map groups to existing matter membership.
3. **Finish the chat surface a lawyer needs** — sessions, streaming, citation open (backend is already ahead).
4. **Move embeddings and ingest off the API** — alert on failure, queue depth, and backup age.
5. **For the paid firm, ship one real connector** — Microsoft Graph first if they live in Microsoft 365; keep source ACL beside matter ACL.
6. **Only then:** durable reviews and workflows, library, Word add-in.

For every Mike-inspired item: write a clean requirement + `IP_ORIGIN_RECORD` entry **before** implementation. Prefer “best for Harbour / FirmOS users,” not visual or structural cloning.

---

## 9. Suggested definition of “live”

### 9.1 Private pilot “live”

- [ ] Firm data only in dedicated AWS or Azure account
- [ ] OIDC login works; `AUTH_ENABLED=true`; header trust disabled
- [ ] TLS, WAF, private DB/Redis/object storage
- [ ] Backups enabled; restore rehearsed once; RPO/RTO written
- [ ] Secrets only in Secrets Manager / Key Vault
- [ ] Lawyer can complete: login → ask/chat → open citation → download/view source
- [ ] Model endpoint in-region with no-train terms
- [ ] Health checks + alerts + on-call owner
- [ ] Migration job documented

### 9.2 First paid firm “live”

All pilot items, plus:

- [ ] Microsoft Graph (or Drive) connector with incremental sync and disconnect
- [ ] Source + matter ACL intersection enforced in retrieval SQL
- [ ] Admin can see connection health / last sync / errors
- [ ] Immutable audit export for access and admin events
- [ ] Load test passed against contracted page/QPS budget
- [ ] Pen test completed or scheduled with findings triage
- [ ] Signed DPA + subprocessor list + support SLA
- [ ] Offboarding runbook tested once on a staging silo

### 9.3 Explicit non-goals for first live

- Mike product parity
- Self-serve multi-tenant SaaS
- SOC 2 Type II certificate in hand
- Word add-in production
- In-memory tabular/workflows promoted without durable schema + UI
- Kafka / Neo4j (unless a later gate wins)

---

## 10. Risks if we ship too early

| Risk | Why it matters | Mitigation |
|------|----------------|------------|
| Header-trust auth in “prod” | Any client can impersonate a member | OIDC only; deny `X-Member-Id` when auth on |
| Shared DB multi-tenancy | Cross-firm leak = existential | Per-firm silo for v1 |
| Fake connectors sold as real | Trust destruction | One real Graph path before paid SharePoint claims |
| In-memory tabular/workflows | Data loss on restart | Do not enable in production until Postgres-backed |
| Unbounded LLM cost | Margin and ToS risk | Hard monthly cap + queue |
| Claiming SOC 2 / GDPR export that don't exist | Procurement and regulatory exposure | Sell only documented controls |
| Copying Mike for speed | AGPL / IP exposure | Clean-room protocol; stop and escalate if asked to port |

---

## 11. Summary

| Question | Answer |
|----------|--------|
| What is done? | Retrieval science + cited ask/chat backend + matter/document schema + Phase-0 sync substrate |
| What is missing for production? | Identity, silo networking, managed data plane, backups, secrets, lawyer UI completion, ops/IaC, model contract |
| What is missing for paid enterprise? | Real connectors, admin, audit export, capacity proof, commercial pack |
| How do we scale? | New firm = new stack; inside firm = API replicas + ingest/embed/sync workers; prove FirmOS page targets with load tests |
| How is a firm handled? | Dedicated AWS or Azure deployment, firm IdP, matter ACL, no-train models, exit via bucket+DB export |
| AWS vs Azure? | Same four services and schema; different managed services (table in §5.2); Azure OpenAI + Entra for Microsoft-first firms |
| What do we sell first? | Firm Memory Pilot → Firm Memory Production — not workspace parity |

---

*End of review. Re-run after pilot gates close and after the first paid connector ships.*
