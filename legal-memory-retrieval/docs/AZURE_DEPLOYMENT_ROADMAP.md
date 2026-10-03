# Azure deployment roadmap — legal-memory-retrieval

End-to-end plan to run the current platform on Azure. This is a deployment plan for the system as it exists in `legal-memory-retrieval/`. It does not change retrieval fusion, embedding dimension, or frozen experiment flags.

Companion: `docs/SYSTEM_ARCHITECTURE.md`.

---

## 1. Recommendation

Deploy on **Azure Container Apps**, in one region, on a private virtual network.

The runtime is one API image (FastAPI + the built SPA) plus a worker that uses the same image. Postgres, Redis, Gotenberg, and object storage sit beside it. That shape matches Container Apps. AKS is a later option if GPU rerank or a larger service mesh becomes necessary.

| Runtime today | Azure service |
|---------------|----------------|
| API `uvicorn app.api.main:app` (SPA at `/ui`) | Container App, external HTTPS ingress |
| Ingest worker `python -m app.workers.ingest` | Container App, no ingress, same image |
| Postgres 16 + pgvector + `pg_trgm` + HNSW | Azure Database for PostgreSQL Flexible Server |
| Redis 7 | Azure Cache for Redis (TLS) |
| Gotenberg (Office → PDF), localhost only | Container App, **internal** ingress only |
| Object store (`local` or S3/MinIO) | Azure Blob (after a small backend) — see gaps |
| LLM: Bedrock, else Groq / Gemini | Azure OpenAI (after a provider) — see gaps |
| Embeddings + cross-encoder, baked into the image | Stay in the API container (MiniLM 384-d) |
| OIDC (`login.microsoftonline.com` already anticipated) | Microsoft Entra ID |
| Secrets files via `SECRETS_DIR` | Key Vault secrets mounted as files |
| OTEL when `OTEL_EXPORTER_OTLP_ENDPOINT` is set | Application Insights |
| Malware scan `clamd` (production refuses `off`) | ClamAV container on the internal network |

```text
                         Internet
                            │
                    Azure Front Door + WAF
                    (TLS, SSE-friendly timeout)
                            │
              ┌─────────────▼──────────────┐
              │  Container Apps environment │
              │  (VNet-injected)            │
              │                             │
              │  api :8000  ── /ui SPA      │
              │  worker (no ingress)        │
              │  gotenberg (internal :3000) │
              │  clamd (internal :3310)     │
              └──────┬──────────┬───────────┘
                     │          │
     private endpoints          │ managed identity
                     │          │
     ┌───────────────▼──┐  ┌────▼─────────────┐
     │ PostgreSQL +     │  │ Key Vault        │
     │ pgvector         │  │ ACR              │
     │ Redis (TLS)      │  │ Blob Storage     │
     │ Azure OpenAI     │  │ Log Analytics    │
     └──────────────────┘  └──────────────────┘
```

---

## 2. What is being deployed

One process serves every product surface: Ask the Firm, Assistant (SSE), matters, documents, search, calendar, Word/drafting. Retrieval (BM25, MiniLM vectors, metadata, SQL graph seeds, RRF, local cross-encoder) runs **inside** that process. ACL is applied in SQL before ranking.

Production start (`ENV=production`) **refuses to boot** unless all of these are true (`app/config.py` `production_problems`):

- `AUTH_ENABLED=true`
- `CORS_ORIGINS` is an explicit list
- `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_REDIRECT_URI` set
- `ALLOW_API_KEY_BROWSER_LOGIN=false`
- `SESSION_COOKIE_SECURE=true`
- `INGEST_MODE=queue` (worker required)
- `INGEST_ALLOWED_ROOTS` set explicitly
- `DATABASE_URL` is not the `legal:legal` dev credential
- `SOURCES_TOKEN_ENCRYPTION_SECRET` is not the dev default
- `MALWARE_SCANNER` is not `off` (only `clamd` is implemented)
- S3 backend, if used, does not keep the `minioadmin` secret

The image (`Dockerfile`) builds the Vite SPA into `/ui`, installs CPU torch from `requirements.lock`, and **bakes** `all-MiniLM-L6-v2` and `cross-encoder/ms-marco-MiniLM-L-6-v2` under `HF_HOME=/opt/models`. Startup runs `python scripts/migrate.py` then uvicorn with `--proxy-headers`. Readiness is `GET /api/system/ready` (Postgres, Redis, migrations, models warm). Liveness is `GET /api/system/health`.

The frozen corpus (`dummy-firm/data`) is **not** in the image. Loading it is a one-shot job.

---

## 3. Gaps that block a faithful Azure production deploy

These are the only code or config changes the roadmap depends on. Everything else is infrastructure.

| # | Gap | Why it matters | Change |
|---|-----|----------------|--------|
| G1 | Ask answers only Bedrock, Groq, Gemini, or extractive (`app/answers/generate.py`). Chat’s OpenAI client posts to `https://api.openai.com` (`app/llm/model_router.py`). Grounding verifier defaults to a Bedrock model id. | Firm text would leave Azure, or answers would fall through to extractive. | Add an Azure OpenAI chat path (base URL + `api-version` + deployment name) for Ask, Assistant, and the grounding verifier. Keep the verifier on a **different deployment** from the writer. |
| G2 | Object store is filesystem or boto3 S3. `boto3` is not in `requirements.txt`. | API and worker cannot share durable blobs. | Add an Azure Blob backend behind `ObjectStore`, or (pilot only) mount one Azure Files share at `OBJECT_STORE_ROOT` on **both** api and worker with `OBJECT_STORE_BACKEND=local`. |
| G3 | `MALWARE_SCANNER=off` prevents production boot. The only scanner is ClamAV over TCP. | Uploads cannot ship. | Run ClamAV on the internal network and set `CLAMD_HOST`. GPL: record the dependency decision before enabling. Microsoft Defender for Storage does not satisfy this gate; the app scans during ingest. |
| G4 | Every API replica runs `migrate.py` before serving. The script bootstraps `schema.sql` when `members` is missing, with no advisory lock. | Two replicas starting on an empty database can race. | Run migrations as a **one-shot job** before the API revision goes live. Add a Postgres advisory lock in `migrate.py` so a replica restart cannot double-apply. |
| G5 | Ask/chat rate limits are in-process (`app/resilience/rate_limit.py`). The file says a shared Redis limiter is required once there is more than one worker. | N replicas allow N times the configured limit. | Pilot: `WEB_CONCURRENCY=1` and `minReplicas=1`. Before scaling out, move the limiter to Redis. |
| G6 | Assistant turn budget is 180s plus a 60s wrap-up. Gotenberg timeout is 120s. | Default edge timeouts cut SSE streams. | Set Container Apps request timeout and Front Door origin timeout **above 240s**, and turn off response buffering on `/api/answers/stream` and `/api/chat/`. |
| G7 | `vector` and `pg_trgm` extensions, plus an HNSW index (`20260924h_schema_drift.sql`). | Flexible Server only loads allow-listed extensions, and the server’s pgvector build must support HNSW. | In Phase 0, confirm the target server version. If HNSW is missing, stop and pick a version that has it. Do not drop the index to “make deploy work.” |
| G8 | Readiness stays 503 until MiniLM and the cross-encoder have encoded a warm-up pair (about 10–17s, longer on a cold CPU). | A default 30s probe will recycle the container forever. | Startup probe ≥ 180s. Liveness hits `/health` only. Readiness hits `/ready`. |
| G9 | New packages (`azure-storage-blob`, and any Azure OpenAI SDK) need a license line in `docs/legal/DEPENDENCY_AUDIT.md` before they are added. Prefer `httpx` against the Azure OpenAI REST API so no new SDK is required for G1. | IP / license rule. | Audit before the dependency lands. |

**Do not change in this program**

- Embedding provider stays `minilm`, dimension **384**. Azure OpenAI embeddings are a different size and would require a schema migration and a full re-embed. That is a separate retrieval program, not a deploy task.
- Fusion policy, matter scope, and the C7 / CE-on-evidence / GraphRAG flags stay as frozen in `.cursor/skills/legal-memory/SKILL.md`.
- No Kafka, Neo4j, or a second retrieval service.

---

## 4. Phased roadmap

Each phase has an exit check. Do not start the next phase’s production cutover until the check passes. Phases 1 and 2 can run in parallel after Phase 0.

### Phase 0 — Decisions (about 2–3 days)

Lock these before writing Bicep or application code:

1. **Region.** One region for Postgres, Blob, OpenAI, and Container Apps. Legal data should not fail over to a second region until residency is explicit.
2. **Identity.** Entra tenant, who is a member, and whether the first environment is a single firm (`TENANT_ID`, default `harbour`).
3. **LLM deployments.** Two Azure OpenAI deployments: a writer (Ask + Assistant) and a verifier (grounding). Record deployment names, not model marketing names, because Azure calls deployments by the name you choose.
4. **Object store.** Blob backend (preferred) or Azure Files for a short pilot.
5. **Corpus.** Dummy-firm seed versus an empty firm that fills only by upload.
6. **pgvector gate.** Create a throwaway Flexible Server, set `azure.extensions` to `VECTOR,PG_TRGM`, run `CREATE EXTENSION vector` and confirm `CREATE INDEX ... USING hnsw`.

**Exit:** a one-page decision record (region, names, Blob vs Files, corpus choice) and a passing HNSW smoke test.

### Phase 1 — Application changes (about 1 week)

Land G1–G4 and G8’s probe settings in repo form (Container Apps YAML or Bicep comes in Phase 3; the app must already boot against Azure endpoints from a laptop or a dev container).

1. Azure OpenAI chat completion, streaming, and JSON mode, selected by environment (`AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` or managed identity, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION`). Wire it into Ask (`ANSWER_PROVIDER`), the chat model router, and `GROUNDING_VERIFIER_MODEL`.
2. Blob `ObjectStore` (`put`, `put_file`, `get`, `exists`, `delete`) **or** document the Azure Files mount and keep `local`.
3. Production env template `.env.production.example` that satisfies `production_problems()` with placeholders, never real secrets.
4. `migrate.py` takes `pg_advisory_lock` around apply. Document that the container command for Azure is **uvicorn only**; migrations run as a job.
5. Confirm `DATABASE_URL` with `sslmode=require` works through `app/db/connection.py`, and `REDIS_URL=rediss://...` works through `redis.from_url` (it does, if the URL is right).
6. Re-run answer checks on a handful of frozen questions after the provider switch. Retrieval eval is a separate gate and should be unchanged if embeddings and fusion are unchanged.

**Exit:** `ENV=production` boots locally against Azure dev Postgres, Redis, and OpenAI; `/api/system/ready` returns 200; one Ask and one Assistant turn complete with citations; an upload is scanned and indexed by the worker.

### Phase 2 — Azure foundation (about 1 week, parallel with Phase 1)

Infrastructure as code (Bicep, in a new `deploy/azure/` directory when implementation starts). Suggested resource names:

| Resource | Name pattern | Notes |
|----------|----------------|-------|
| Resource group | `rg-precentis-<env>-<region>` | `dev`, then `prod` |
| Virtual network | `vnet-precentis-<env>` | Subnet for Container Apps infrastructure, subnet for private endpoints |
| ACR | `acrprecentis<env>` | Admin user disabled; pull via managed identity |
| Key Vault | `kv-precentis-<env>` | RBAC, purge protection on prod |
| Log Analytics + App Insights | `log-precentis-<env>` | OTLP / Azure Monitor |
| PostgreSQL Flexible Server | `psql-precentis-<env>` | PostgreSQL 16, private endpoint, 7–35 day PITR on prod |
| Redis | `redis-precentis-<env>` | TLS 1.2, private endpoint, no public network on prod |
| Storage | `stprecentis<env>` | Container `firmos`, versioning + soft delete, private endpoint |
| Azure OpenAI | `oai-precentis-<env>` | Private endpoint, two deployments |
| Front Door + WAF | `afd-precentis-<env>` | Managed certificate later |
| User-assigned identity | `id-precentis-<env>` | ACR pull, Key Vault secrets, Blob data, optional OpenAI |

Network: Postgres, Redis, Blob, Key Vault, and OpenAI have **no public endpoint** in prod. Operators reach the database through a bastion or a dev Container App with the Azure portal’s private access, not a laptop-open firewall rule left in place.

**Exit:** `dev` resource group exists, private DNS resolves, a jump container can `psql` and `redis-cli --tls`.

### Phase 3 — Images and Container Apps (about 3–4 days)

1. GitHub Actions (or Azure DevOps): test → `docker build` from `legal-memory-retrieval/` → push to ACR tagged with the git SHA.
2. Container Apps environment on the VNet.
3. **Migration job** (manual or pipeline step): same image, command `python scripts/migrate.py`, identity + `DATABASE_URL`, runs to completion before traffic shifts.
4. **API app**
   - Command: `uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers`
   - CPU / memory: start at **2 vCPU, 8 GiB**. Torch plus two models plus a warm embedder needs that headroom. Raise if the replica OOMs during warm-up.
   - `minReplicas=1` (cold start reloads models). `maxReplicas=2` in dev, higher in prod only after G5.
   - Probes: startup and readiness `GET /api/system/ready` (startup failure threshold covering ≥ 180s). Liveness `GET /api/system/health`.
   - Secrets: Key Vault references mounted at `/run/secrets/precentis` so `SECRETS_DIR` matches the app.
   - Ingress: external, target port 8000, timeout ≥ 300s, request body large enough for `MAX_UPLOAD_FILE_MB` (100) and the batch cap.
5. **Worker app:** same image and secrets, command `python -m app.workers.ingest`, ingress disabled, 2 vCPU / 4 GiB, exactly 1 replica until a queue-depth scaler exists. The worker already uses `FOR UPDATE SKIP LOCKED`, so extra replicas are safe later.
6. **Gotenberg app:** image `gotenberg/gotenberg:8`, internal ingress only, `GOTENBERG_URL=http://gotenberg:3000` on the API. Same command flags as compose (`--api-timeout=120s`).
7. **ClamAV app:** internal port 3310, `MALWARE_SCANNER=clamd`, `CLAMD_HOST` = the internal name.

**Exit:** a new revision reaches `/api/system/ready` 200. Gotenberg and ClamAV have no public address.

### Phase 4 — Data (about 1–2 days, plus embed time)

1. Migration job green on the empty server (`vector`, `pg_trgm`, HNSW present).
2. If seeding the dummy firm: a one-shot job with the corpus mounted read-only, `CORPUS_DIR` pointed at it, running the existing ingest and embed scripts. Embed is CPU-bound (historically ~20 minutes for ~42k chunks on a workstation). Size that job like the API (2 vCPU, 8 GiB) and expect longer on a small SKU.
3. If starting empty: skip the corpus job. First documents enter through upload → worker.
4. Create the first admin / members the way the app already does (Entra login creates or maps the member — confirm the mapping in `app/auth` during Phase 1 and document it here if it is invite-only).
5. Issue service API keys with `python scripts/issue_keys.py` from a job, for non-browser callers. Browser login stays OIDC.

**Exit:** a known matter is searchable by a member who is allowed to see it, and a member who is not allowed gets no chunks. That is the ACL check. Run `evals/retrieval_eval.py` against this database only when the loaded corpus is the frozen eval corpus; record the numbers in `docs/CHANGELOG.md` if anything in retrieval changed (it should not have).

### Phase 5 — Identity and edge (about 2–3 days)

1. Entra app registration, authorization code + PKCE (the app already uses that flow).
   - Redirect URI: `https://<host>/api/auth/callback`
   - `OIDC_ISSUER=https://login.microsoftonline.com/<tenant>/v2.0`
   - `OIDC_SCOPES=openid email profile`
2. Front Door origin = the Container App. Managed certificate on the firm hostname.
3. WAF policy in prevention mode after a detection-mode week, so uploads and SSE are not false-positived on day one.
4. `CORS_ORIGINS=https://<host>` (the SPA is same-origin under `/ui`; the explicit origin is still required by the production gate, and by any Office add-in host).
5. Cookie: `SESSION_COOKIE_SECURE=true`. Uvicorn `--proxy-headers` already trusts `X-Forwarded-Proto` from the ingress.
6. `ALLOW_API_KEY_BROWSER_LOGIN=false`.

**Exit:** a lawyer signs in with Entra, Ask streams to completion, a chat turn longer than 60s is not cut off, and `/docs` is absent (production already disables OpenAPI).

### Phase 6 — Operate (about 2–3 days)

Alerts, all paging only after one clean week of thresholds:

| Signal | Why |
|--------|-----|
| `/api/system/ready` not 200 | Models, Redis, Postgres, or migrations |
| API restarts / OOM | Undersized replica |
| Postgres CPU, connections, storage | Pool is `db_pool_max_size` (20) **per process** |
| Redis memory and evictions | Retrieval cache plus sessions |
| Ingest batches stuck `running` longer than `INGEST_STALE_MINUTES` (30) | Worker dead; the app reclaims stale batches, but someone should look |
| Azure OpenAI 429s and content-filter blocks | Legal text trips default filters; tune filters on the legal use case and watch abstentions |
| Front Door 5xx and origin timeout | SSE cuts |

Backups: Postgres PITR, Blob versioning and soft delete, Key Vault purge protection. A restore drill (new server from backup, point a dev revision at it) belongs in this phase, not after the first incident.

Dashboards: Application Insights via `OTEL_EXPORTER_OTLP_ENDPOINT`. Keep `/api/system/metrics` off the public Front Door route (Prometheus is useful from inside the environment).

**Exit:** a written restore drill and an on-call view that shows ready, ingest lag, and OpenAI errors.

### Phase 7 — Production cutover

1. Repeat Phases 2–6 in `prod` with HA where it matters: Flexible Server zone-redundant or a named backup window, Redis Standard (replication), Container Apps min replicas 2 **only after** the Redis rate limiter (G5) and a connection budget (`replicas × pool max` under Postgres `max_connections`).
2. Front Door cutover by hostname.
3. Rollback is “send 100% traffic to the previous Container App revision.” Images are immutable SHA tags, so this does not require a rebuild.

**Exit:** production `/ready` is 200, a scripted sign-in + Ask + upload + Assistant smoke passes, and the previous revision is still available for an hour.

---

## 5. Environment contract (production)

Set these on the API and the worker unless noted. Secrets are files under `SECRETS_DIR=/run/secrets/precentis`, not image ENV.

| Variable | Value |
|----------|--------|
| `ENV` | `production` |
| `AUTH_ENABLED` | `true` |
| `DATABASE_URL` | `postgresql://<user>:<pwd>@<host>:5432/legal_memory?sslmode=require` |
| `REDIS_URL` | `rediss://:<key>@<host>:6380/0` |
| `INGEST_MODE` | `queue` |
| `INGEST_ALLOWED_ROOTS` | a narrow path, e.g. `/app/data/ingest-inbox` (created empty if bulk server ingest is unused) |
| `MALWARE_SCANNER` | `clamd` |
| `CLAMD_HOST` / `CLAMD_PORT` | internal ClamAV |
| `GOTENBERG_URL` | `http://<gotenberg-internal>:3000` (API only) |
| `OBJECT_STORE_BACKEND` | `azure` or `local` |
| `OBJECT_STORE_BUCKET` | `firmos` (container name) |
| `OIDC_*` | Entra values above |
| `ALLOW_API_KEY_BROWSER_LOGIN` | `false` |
| `SESSION_COOKIE_SECURE` | `true` |
| `CORS_ORIGINS` | `https://<public-host>` |
| `SOURCES_TOKEN_ENCRYPTION_SECRET` | random 32+ bytes |
| `EMBEDDING_PROVIDER` | `minilm` |
| `EMBEDDING_DIM` | `384` |
| `WEB_CONCURRENCY` | `1` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Application Insights OTLP endpoint |
| Azure OpenAI vars | from Phase 1, once they exist |
| `ANSWER_PROVIDER` | the new azure value, once it exists |
| `DEFAULT_LLM_PROVIDER` | same |

`AWS_BEARER_TOKEN_BEDROCK`, `GROQ_API_KEY`, and `GEMINI_API_KEY` stay unset in the Azure production environment so traffic cannot fall through to another cloud by accident.

---

## 6. Sizing (pilot, one region)

Order-of-magnitude for a pilot, excluding model tokens. Confirm in the Azure pricing calculator before committing.

| Piece | Pilot shape | Why |
|-------|-------------|-----|
| API | 2 vCPU, 8 GiB, 1 replica | Models resident in the process |
| Worker | 2 vCPU, 4 GiB, 1 replica | Parse + MiniLM embed on upload |
| Gotenberg | 1 vCPU, 2 GiB | LibreOffice spikes on large Office files |
| ClamAV | 1 vCPU, 2 GiB | Signature DB |
| PostgreSQL | General Purpose, 2 vCores, 128 GB | HNSW + FTS want memory; burstable is a dev-only option |
| Redis | Standard C1 | Replication for prod; Basic is acceptable in dev |
| Blob | Hot, versioning on | Originals and renditions |
| Front Door + WAF | Standard | Edge TLS and SSE |
| Azure OpenAI | Pay per token | Dominant variable cost once lawyers use Assistant |

A single-replica pilot is expected to land in the low thousands of USD per month before token spend. Horizontal scale is a Phase 7 decision because of connection count and the in-process rate limiter.

---

## 7. Security notes specific to this app

- `AUTH_ENABLED=false` trusts `X-Member-Id`. The production gate already blocks that. Do not set `DEV_AUTH_ANY_HOST` in any cloud environment.
- Restricted passages must stay out of the candidate set. A deploy that points the app at a database without the permission SQL is a product failure, not only an ops failure. The Phase 4 ACL smoke test is mandatory.
- Gotenberg has no authentication. Internal ingress only, same as the compose comment that binds it to `127.0.0.1`.
- Session idle is 60 minutes, absolute lifetime 12 hours. That is already the app default; Front Door caching must not cache `/api/*` or `/ui` authenticated responses.
- Uploads stream with `MAX_UPLOAD_FILE_MB=100` and batch cap 1 GB / 500 files. Ingress and WAF body limits have to match, or large filings fail at the edge.
- Content filters on Azure OpenAI will block some genuine legal material (crime, violence, sexual abuse in case records). Test a slice of the corpus in Phase 1 and adjust the filter profile before cutover. Abstention is preferable to a dropped connection, and the Ask path already abstains when evidence is missing.

---

## 8. Delivery sequence

```text
Phase 0 decisions + HNSW smoke
        │
        ├──────────────┐
        ▼              ▼
Phase 1 app gaps   Phase 2 Bicep (dev)
        │              │
        └──────┬───────┘
               ▼
        Phase 3 images + Container Apps (dev)
               ▼
        Phase 4 migrate + corpus or empty firm
               ▼
        Phase 5 Entra + Front Door
               ▼
        Phase 6 alerts + restore drill
               ▼
        Phase 7 repeat in prod, scale only after Redis rate limit
```

Rough calendar if one engineer owns the app gaps and one owns Azure: **about three weeks to a dev environment that a lawyer can sign into, and a fourth week for production** after the dev smoke tests pass. The long pole is Phase 1 (Azure OpenAI + Blob + migration lock) and the pgvector version check in Phase 0.

---

## 9. Implementation order when this plan is approved

1. Phase 0 decision record and HNSW smoke test.
2. Azure OpenAI provider and Blob store (or the Files decision), with license audit.
3. Migration advisory lock and a production env example.
4. `deploy/azure/` Bicep for the dev resource group.
5. Pipeline: build the existing `Dockerfile`, push to ACR, run the migration job, deploy the four Container Apps.
6. Entra app and Front Door.
7. Smoke: sign-in, Ask stream, Assistant stream, upload → worker → retrieval, ACL denial, restore drill.

No retrieval-weight changes in that list. If a smoke test shows wrong documents, treat it as a retrieval bug and measure it with `evals/retrieval_eval.py` before changing fusion.
