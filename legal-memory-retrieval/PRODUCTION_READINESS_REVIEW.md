# LEXOS / FirmOS production-readiness review

**Review date:** 2026-09-21  
**Scope:** `legal-memory-retrieval` and its supporting product/operating material.  
**Decision:** **Do not deploy to production.** The product is a promising single-firm prototype with well-developed retrieval experiments, but it does not yet meet the minimum security, tenancy, reliability, delivery, or operational requirements for enterprise legal customers.

## Executive assessment

The repository demonstrates real product progress:

- Retrieval is comparatively mature: hybrid retrieval, ACL-aware candidate queries, provenance, caching, tracing, evaluation harnesses, matter/document/version concepts, and citations are present.
- The team has measured quality on internal synthetic/curated Harbour corpora and has documented known model-quality limitations instead of hiding them.
- Focused automated coverage is healthy: `119 passed` in the health, upload, source-sync, and chat test suites on 2026-09-21.

Those positives do **not** make this sellable as an enterprise DMS/SaaS. The current product trusts client-supplied member identity in development, has multiple routes with no authentication or object authorization, lacks tenant enforcement in the primary data model, and has no deployable, reproducible cloud platform. The supplied Compose file itself cannot be parsed.

The immediate goal should be a controlled design-partner pilot for one firm only after the P0 work is completed. General enterprise availability should follow a separate multi-tenant/platform programme.

## What exists today

| Capability | Current state | Production assessment |
|---|---|---|
| Retrieval and answer generation | Parallel lexical/vector/metadata/graph retrieval, reranking, citations, abstention, cache and evaluation artefacts. | Solid R&D base; benchmarks are not representative enterprise acceptance evidence. |
| Core legal model | Members, clients, matters, permissions, documents, chunks; newer document versions, upload batches, source connections and review concepts. | Incomplete tenancy and lifecycle model; primary entities are single-firm. |
| Ingestion | Folder batches, object-store abstraction, parsing and sync prototype. | Not safe or durable for production bulk ingestion. |
| User experience | Static SPA, Word task pane, document browsing, projects, reviews and chat. | Demo quality; unsafe rendering and demo persona switching prevent enterprise use. |
| Auth and ethical walls | API-key lookup and SQL ACL predicates exist. | Not consistently applied; no enterprise SSO/SCIM, roles, tenant claims, service authorization or audit assurance. |
| Observability | Prometheus/OTel hooks and request IDs exist. | No complete operational baseline, SLOs, alerting, dashboards, log-redaction policy, or incident runbooks. |
| Delivery | Local env and Docker Compose reference only. | No valid Compose file, container image, CI/CD, IaC, environment promotion, SBOM, scanning, or release process. |

## Launch blockers (P0)

### P0-01 — The supplied deployment baseline is invalid

- **Evidence:** [`docker-compose.yml`](docker-compose.yml:19) indents `redis` under `postgres`; `docker compose config` fails with “mapping key `image` already defined”. There is no Dockerfile, CI workflow, Terraform/Bicep/CloudFormation, Helm chart, or deployment manifest in the repository.
- **Impact:** There is no repeatable way to build, scan, deploy, roll back, or recover the service.
- **Required outcome:** Correct the Compose file for developer use; then create immutable application/worker images, signed image publication, IaC for every environment, migrations executed once as a controlled job, progressive delivery, rollback, backups and restore drills. A green CI pipeline must include unit/integration/e2e, dependency/SAST/container/IaC scans, and quality-evaluation gates.

### P0-02 — Direct document disclosure through unauthenticated/unauthorized routes

- **Evidence:** [`app/api/routers/documents_router.py`](app/api/routers/documents_router.py:493) exposes `GET /{document_id}/download` with no `Depends(resolve_member)` and no access check. [`app/api/routers/documents_router.py`](app/api/routers/documents_router.py:529) accepts a member but selects document text and chunks without checking the document/matter ACL. Several other sensitive routers expose state-changing or data routes without any auth dependency: workflows, drafting, Word, case law, reviews and tabular review routes (for example [`app/api/routers/word_router.py`](app/api/routers/word_router.py:49)).
- **Impact:** A party that can reach the API can enumerate/guess document IDs and obtain source files or extracted legal text, or invoke privileged workflows. This is a confidential-client-data breach.
- **Required outcome:** Introduce a single authenticated principal (`tenant_id`, user ID, roles, matter permissions, request ID) and attach it at protected router boundaries. Every resource lookup must scope by tenant and enforce matter/document/project authorization before returning data or performing a write. Add negative authorization tests for every route and make the unprotected-route inventory a CI failure.

### P0-03 — No enterprise tenant isolation

- **Evidence:** [`app/db/schema.sql`](app/db/schema.sql:15), [`app/db/schema.sql`](app/db/schema.sql:27), [`app/db/schema.sql`](app/db/schema.sql:39), and [`app/db/schema.sql`](app/db/schema.sql:76) define the core members, clients, matters, and documents tables without a tenant key. `upload_batches` adds `tenant_id` only later ([`schema.sql`](app/db/schema.sql:405)), while source connections use a separate `organization_id`. There are no database row-level-security policies in the schema.
- **Impact:** The application cannot prove a firm’s data is isolated from another firm’s data. An application bug, operator query, future route, cache-key omission, or background job can cross client boundaries.
- **Required outcome:** Make tenant a first-class, immutable, required key on every business, search, audit, queue, cache and storage record; use composite foreign keys/unique indexes; set the tenant from verified identity only; enforce PostgreSQL RLS with a transaction-local tenant context; test cross-tenant denial end-to-end. Do not treat a storage prefix or query predicate alone as isolation.

### P0-04 — Insecure defaults and no production configuration gate

- **Evidence:** [`app/config.py`](app/config.py:7) contains usable local database credentials; lines 26–32 default the tenant, local store, MinIO endpoint and MinIO credentials; lines 56–59 embed a default source-token encryption secret and run source processing inline. [`app/auth/deps.py`](app/auth/deps.py:10) defaults auth off and treats an absent identity as “admin/anonymous” on line 42. [`app/auth/key_vault.py`](app/auth/key_vault.py:19) has a fallback master secret.
- **Impact:** A missed environment variable can silently produce an unauthenticated service, shared/default cryptographic key, or development data path. This is unacceptable for confidential legal data.
- **Required outcome:** Define `ENV=production`; fail startup unless all secret references, allowed origins/hosts, auth provider, encryption keys, external stores, worker backend, retention policies and telemetry sink are configured. Secrets must be secret-manager references, never defaults; rotate them and use per-tenant/customer-managed keys where contracted.

### P0-05 — Browser XSS and overly permissive CORS

- **Evidence:** [`app/api/main.py`](app/api/main.py:92) sets `allow_origins=["*"]` with `allow_credentials=True`. [`static/app.js`](static/app.js:764) inserts `doc.highlighted_body` into `innerHTML`; [`static/app.js`](static/app.js:823) builds highlighted document content with unescaped interpolation. [`static/word-taskpane.html`](static/word-taskpane.html:297) inserts document title/snippet API values into `innerHTML`. [`static/index.html`](static/index.html:1) has no CSP.
- **Impact:** A malicious imported document or stored title/snippet can execute in a lawyer’s session. Wildcard credentialed CORS is unsafe/misconfigured and must not be relied upon as access control.
- **Required outcome:** Use text nodes/DOM construction for document content or an audited sanitizer with a very narrow allowed markup policy; remove inline event handlers; enforce a nonce/hash CSP and standard response security headers at the edge; explicitly allow only production UI origins and only required methods/headers. Test with hostile document names and body content.

### P0-06 — Upload, sync and egress controls are not production-safe

- **Evidence:** [`app/api/routers/uploads.py`](app/api/routers/uploads.py:21) reads every uploaded file fully into memory (line 40), with no size, file-count, MIME/content validation, malware scanning, batch authorization, or async handoff. [`app/api/routers/sources.py`](app/api/routers/sources.py:53) lists, creates, syncs, reads and deletes source connections without checking the caller’s tenant/matter role or ownership. The documented Phase 0 source connector is intentionally fake and runs inline by default ([`app/sources/sync_engine.py`](app/sources/sync_engine.py:164)).
- **Impact:** Memory exhaustion, malware/ransomware ingress, matter-level IDOR, sync-trigger abuse and unreliable bulk processing.
- **Required outcome:** Direct-to-object-storage multipart upload with content-length/file-count limits, allowlisted MIME plus signature inspection, antivirus/CDR quarantine, immutable original objects, checksums, idempotency and a durable queue/DLQ. Source connectors must use OAuth with least scopes, verified callbacks, encrypted tokens under managed keys, source ACL mapping, per-tenant rate/concurrency budgets and worker-only execution.

## High-priority work before an enterprise pilot (P1)

1. **Identity and administration:** SAML/OIDC SSO for each firm, SCIM provisioning/deprovisioning, MFA/conditional access delegated to the IdP, roles plus matter ethical walls, break-glass with approval, API/service identities, session/revocation strategy and a customer admin console.
2. **Legal-data security:** TLS everywhere; private service endpoints; encryption at rest with managed keys, optional tenant CMK/BYOK; signed short-lived downloads; classification/DLP; malware scanning; legal holds, retention/deletion, immutable audit exports, and regional data-residency selection.
3. **Auditability:** Append-only, tamper-evident audit events for login, search, view/download, prompt, answer, export, permission and admin events. Store actor, tenant, correlation ID, source/evidence and before/after state. Retain and export per contract.
4. **AI governance:** Vendor/data-processing assessment; no training/retention guarantee appropriate to the selected model provider; model/embedding/version registry; prompt-injection and data-exfiltration controls; per-tenant model allowlists; human-review UX for drafted output; citation/evidence policy; red-team and adversarial legal-corpus tests.
5. **Quality gates:** Replace demo/synthetic-only claims with blinded, representative firm evaluations; define acceptance thresholds by use case (retrieval, citation precision, grounded answer, abstention, permission denial and latency); version corpora and gold sets; gate releases on non-regression.
6. **Reliability:** Durable job orchestration, retries that do not block workers, idempotency, DLQs, backpressure, quotas, bulkhead/circuit breakers, database/object-store restore tests, regional DR plan, RPO/RTO, SLOs and on-call runbooks.
7. **Product UX/accessibility:** Remove the demo persona selector as an identity mechanism; complete responsive/keyboard/screen-reader and error/empty-state testing; provide clear ingestion status, evidence lineage, permission-denied explanations, destructive-action confirmation and safe bulk-operation recovery.
8. **Supply chain and governance:** Lockfiles with exact resolved versions, SBOM, dependency/license/CVE policy, code review and signed release provenance. Current `>=` dependencies are not reproducible. Establish DPA, security addendum, subprocessor list, acceptable-use policy, privacy notice, support and incident-notification commitments.

## Target architecture: provider-neutral first

```text
Firm user / Word add-in
  -> CDN + WAF + DDoS + TLS -> Web/API (stateless, multi-AZ)
  -> IdP (OIDC/SAML, SCIM) -> tenant + role + ethical-wall claims
  -> policy gateway / application authorization -> PostgreSQL (RLS)
                                             -> object storage (private, CMK)
                                             -> Redis (non-authoritative cache)
                                             -> durable queues -> isolated workers
                                                               -> parser/OCR/AV/DLP
                                                               -> embeddings/indexes
  -> approved LLM gateway (tenant policy, redaction, audit, budgets)

All paths -> immutable audit store + logs/metrics/traces/SIEM
Control plane -> tenant registry, entitlement, region/stamp routing, billing, admin
```

Start with a **hybrid tenancy model**:

- Pooled application/worker platform with strict tenant context, RLS, KMS/Key Vault encryption, per-tenant object prefixes/containers, queues, rate limits and cache namespace.
- Dedicated database/storage/compute deployment stamp for regulated or large firms. This is an enterprise pricing tier, not a forked codebase.
- Route a tenant to its home region/stamp from a global control plane. Never infer tenant from a host name or client-provided header.

Tenant IDs must appear in every database predicate/index, message, object key, audit record, telemetry attribute (with PII controls), cache key and search/index partition. Isolation testing must be automated. AWS explicitly notes that partitioning itself does not ensure tenant isolation; Azure similarly treats isolation as a spectrum and recommends deliberate deployment-stamp trade-offs. [AWS data-partitioning guidance](https://docs.aws.amazon.com/whitepapers/latest/saas-architecture-fundamentals/data-partitioning.html) and [Azure tenancy models](https://learn.microsoft.com/en-us/azure/architecture/guide/multitenant/considerations/tenancy-models) support this approach.

## AWS and Azure reference mapping

| Concern | AWS reference implementation | Azure reference implementation |
|---|---|---|
| Edge | CloudFront + AWS WAF + ALB/API Gateway | Front Door + WAF + Application Gateway/API Management |
| Compute | ECS Fargate initially; EKS only if workload/tenant-stamp operations justify Kubernetes | Container Apps initially; AKS only where node/policy/isolation requirements justify it |
| Identity | External enterprise IdP via OIDC/SAML; Cognito only where it fits the customer model | Microsoft Entra ID multitenant enterprise apps / External ID as appropriate |
| Relational/search | RDS/Aurora PostgreSQL Multi-AZ with pgvector until measured search scale warrants a dedicated search tier | Azure Database for PostgreSQL Flexible Server HA with pgvector until equivalent measured need |
| Objects | S3 versioning, lifecycle, SSE-KMS, private access points, malware-scanning workflow | Blob Storage versioning/immutability, CMK, private endpoints, Defender for Storage workflow |
| Async | SQS + DLQ, EventBridge/Step Functions where orchestration is needed | Service Bus + DLQ, Event Grid/Durable Functions or Container Apps jobs |
| Secrets/keys | Secrets Manager + KMS; tenant CMK option | Key Vault/Managed HSM; tenant CMK option |
| Observability/security | CloudWatch/X-Ray/OTel -> SIEM, CloudTrail, GuardDuty, Security Hub | Azure Monitor/App Insights/OTel -> Sentinel, Activity Logs, Defender for Cloud |
| Delivery | GitHub Actions/OIDC -> ECR -> Terraform/CDK -> staged account/stamp | GitHub Actions/OIDC -> ACR -> Terraform/Bicep -> staged subscriptions/stamps |

Do not promise AWS-and-Azure active/active from day one. Build a portable container and Terraform module interface, choose **one primary cloud and one legal-data region** for the first production service, then validate a second-cloud recovery or customer-hosted deployment only when contractual demand funds it. Cross-cloud active/active multiplies identity, data-consistency, audit, key-management and incident complexity.

## Scaling plan

| Stage | Target | Architecture and operational gate |
|---|---|---|
| 0 — Internal | Current demo and synthetic corpus | No external customer data; fix P0s first. |
| 1 — Design-partner pilot | 1 firm, a few matters, controlled users | Single region but multi-AZ, production IdP, tenant model even for one tenant, private services, durable ingestion, monitored SLOs, weekly restore and security tests. |
| 2 — Commercial multi-tenant | 5–20 firms | Pooled platform with RLS, fair-use quotas, per-tenant metrics/cost attribution, managed on-call, DPA/security pack, regional routing, customer admin/SCIM. |
| 3 — Enterprise scale | 20+ firms and large corpus workloads | Deployment stamps, dedicated tier, worker autoscaling by queue depth, separate query/index capacity, capacity models, regional DR, annual exercises and formal compliance programme. |

Scale the **independent** planes separately: API replicas on request rate/latency; ingest/OCR workers on queue depth and document size; embedding workers on GPU/CPU budget; database based on connections/IO/replica lag; vector/search only after load evidence; object storage independently. The repository currently reports roughly 36k chunks and p95 cold retrieval in the seconds range—valuable prototype data, but not a capacity test for thousands of documents, concurrent reviews or hundreds of firms.

Every tier needs hard per-tenant quotas: users, storage, pages/month, concurrent ingestion, search QPS, model tokens, exports and API rate. Use admission control and budgets before the expensive LLM/OCR path; then surface transparent firm-admin usage reporting and commercial overage policy.

## Release gates and evidence required

Production is allowed only when all are true:

1. P0 findings remediated and independently re-tested, including authorization-bypass, cross-tenant, XSS, upload-abuse and source-connector abuse tests.
2. Reproducible infrastructure and release pipeline deploy a clean environment from scratch; rollback and restore exercises meet declared RPO/RTO.
3. A security assessment and penetration test cover application, API, tenant isolation, SSO/SCIM, storage, workers and cloud configuration; high/critical issues are closed.
4. A selected compliance target and evidence plan are approved (usually SOC 2 Type I/II roadmap, ISO 27001-aligned controls, privacy/data-residency assessment; jurisdiction-specific legal requirements confirmed by counsel).
5. SLOs, error budgets, alerts, escalation, support ownership and incident communication templates are live; 24/7 coverage matches contracted SLA.
6. Representative client-corpus evaluation clears signed quality, grounding, permission and latency acceptance thresholds; AI outputs carry correct evidence and limitations.
7. Contracts are ready: MSA, DPA, SLA, security addendum, acceptable-use terms, subprocessors, retention/deletion/legal-hold terms and AI/data-use terms.

## Recommended sequencing

**Weeks 0–2:** freeze external deployment; correct delivery baseline; enumerate all routes; introduce router-level authentication, document/matter authorization, strict CORS/hosts/security headers, and remove unsafe DOM rendering. Rotate/remove development credentials and default secrets.

**Weeks 3–6:** migrate the core schema to tenant-aware RLS; implement OIDC/SAML, roles/ethical walls, audit events, secure direct upload/quarantine/durable workers and production secrets/object storage. Establish CI, IaC, dev/stage/prod and observability.

**Weeks 7–10:** run threat modelling, load tests, restore/DR exercises and red-team/evaluation work with a design partner; build the enterprise onboarding/SCIM/admin and compliance evidence package.

**After those gates:** onboard one design partner in a limited region/stamp, operate it under defined SLOs, learn from measured load and procurement evidence, then choose pooled versus dedicated tenancy per customer contract.

## Verification record

- `docker compose config`: **failed** due to the YAML error above.
- Focused regression run: **119 passed, 1 warning in 5.69s** (`test_health`, `test_firmos_upload_batch`, `test_source_sync`, `test_chat_assistant`).
- A broader `pytest -q` run progressed beyond 29% but did not complete within the available 30-second execution window; it must run in CI with a published full result, coverage and test-time budget before release.

