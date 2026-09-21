# Universal Document Sync Engine — Implementation Plan

**Status:** Draft plan (no implementation yet)  
**Date:** 2026-09-19  
**Goal:** Build a reusable **connector framework + incremental sync engine** that feeds the existing FirmOS / legal-memory document platform (object storage → parse → chunk → embed → ACL-filtered retrieval).

---

## 1. Problem statement

Today the system can:

- Ingest a **frozen corpus** (`scripts/ingest.py`)
- Accept **manual / batch uploads** (`app/ingest/upload_batch.py`) into object storage + `ingest_jobs`
- Index into **PostgreSQL + pgvector** and enforce **matter-level ACL before ranking**

What it cannot do yet:

- Connect to **Google Drive / SharePoint / OneDrive** (UI buttons are simulated)
- Discover files remotely and keep them **incrementally synchronized**
- Preserve **source-system permissions** (Drive/Graph ACLs) alongside firm matter ACLs
- Treat providers as pluggable adapters behind one sync engine

This plan builds that capability as a **Universal Data Connector / Document Sync Service**, not as one-off “Drive integration” glue.

---

## 2. Non-goals (v1)

| Non-goal | Why |
|----------|-----|
| Kafka / Neo4j | Legal-memory sprint gate still prefers Redis-first queues; revisit after sync MVP |
| Full Glean/Copilot product surface | Out of scope; this plan is the ingestion/sync substrate |
| Live bidirectional write-back | Sync is **source → FirmOS** only in v1 |
| Copying or porting Mike (AGPL) connector code | Clean-room only; requirements → independent design; record in `IP_ORIGIN_RECORD.md` |
| Replacing matter ACL with source ACL | Both must coexist; retrieval still filters in SQL before ranking |
| Supporting every provider on day one | Ship **one** provider end-to-end, then add adapters |

---

## 3. Design principles

1. **Incremental, not periodic full download** — store a per-connection cursor (`pageToken` / `deltaLink`); fetch only changes.
2. **Webhook wakes, delta is truth** — notifications trigger sync; the change API is authoritative; periodic reconcile covers missed webhooks.
3. **Generic connector interface** — sync engine never branches on provider names.
4. **Files stay out of Postgres** — metadata in Postgres; bytes in object storage; embeddings in pgvector (already the FirmOS pattern).
5. **ACL before retrieve** — never index into a searchable universe that leaks across users; filter in SQL.
6. **Reuse existing ingest pipeline** — connector download → object store → existing `ingest_jobs` / extractors / chunk+embed path.
7. **Event-driven workers** — OAuth completes fast; heavy work is queued (Redis first, not Kafka).
8. **Idempotent by content hash + provider file id** — re-sync of unchanged files must no-op.

---

## 4. Target architecture

```text
                    Search / Ask / Chat (existing)
                              │
                      Document Platform
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
  Connection Manager    Sync Engine           Permission Engine
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                      Provider Adapters
                              │
           ┌──────────────────┼──────────────────┐
           │                  │                  │
     Google Drive      Microsoft Graph      (later: Dropbox…)
                              │
                       ┌──────┴──────┐
                       │             │
                   OneDrive      SharePoint
```

### Pipeline (per change)

```text
OAuth / connection create
        ↓
Queue: initial_sync | incremental_sync
        ↓
Adapter: listFiles / getChanges(cursor)
        ↓
Classify: created | modified | deleted | permission_changed
        ↓
Queue: download (only if content needed)
        ↓
Object storage (existing keys)
        ↓
Queue: document_processing (reuse extractors)
        ↓
Chunk + embed (existing)
        ↓
Upsert documents/chunks + sync_files + ACL rows
        ↓
Persist cursor / sync_state
```

### Relation to existing code

| Existing piece | Role in sync engine |
|----------------|---------------------|
| `app/storage/object_store.py` | Store downloaded originals |
| `app/ingest/upload_batch.py` / `pipeline.py` | Parse → normalize → write docs |
| `app/ingest/jobs.py` + `ingest_jobs` / `ingest_items` | Per-file job tracking |
| `app/embeddings/` + chunk writer | Indexing |
| `permissions` + retrieval SQL ACL | Firm-side access control |
| Redis (`docker-compose`) | Job queues + locks (no Kafka in v1) |

---

## 5. Data model

Additive schema (migrations only — do not DROP core tables). Names are ours; not derived from any third-party product schema.

### 5.1 `source_connections`

One connected account / tenant binding per provider.

```text
connection_id          TEXT PK
organization_id        TEXT NOT NULL          -- firm / tenant
created_by_member_id   TEXT                   -- who completed OAuth
provider               TEXT NOT NULL          -- google_drive | microsoft_graph
provider_account_id    TEXT                   -- stable remote account/tenant id
display_name           TEXT
scopes                 TEXT[] 
encrypted_access_token BYTEA / TEXT           -- app-level encryption at rest
encrypted_refresh_token BYTEA / TEXT
token_expires_at       TIMESTAMPTZ
status                 TEXT                   -- active | needs_reauth | paused | disconnected
config                 JSONB                  -- selected drives, site ids, include paths, mime filters
created_at / updated_at
```

**Microsoft note:** One `microsoft_graph` connection can sync both OneDrive and SharePoint sites; `config` holds selected `site_ids` / drive ids rather than inventing separate provider enums unless product UX requires it.

### 5.2 `source_sync_state`

Cursor + health per connection (and optionally per drive/site).

```text
connection_id          TEXT PK/FK
scope_key              TEXT NOT NULL DEFAULT 'default'
                       -- e.g. drive:root, site:{id}, library:{id}
cursor                 TEXT                   -- Drive pageToken or Graph deltaLink
cursor_kind            TEXT                   -- page_token | delta_link
last_sync_at           TIMESTAMPTZ
last_success_at        TIMESTAMPTZ
sync_status            TEXT                   -- idle | running | error | backoff
error_code / error_message
consecutive_failures   INT
UNIQUE (connection_id, scope_key)
```

### 5.3 `source_files`

Remote file inventory (metadata only).

```text
source_file_id         TEXT PK                -- internal id
connection_id          TEXT FK
provider               TEXT NOT NULL
provider_file_id       TEXT NOT NULL          -- remote id
name                   TEXT
mime_type              TEXT
size_bytes             BIGINT
parent_provider_file_id TEXT
path                   TEXT                   -- normalized path for UX / folder mirror
web_url                TEXT
created_at_remote      TIMESTAMPTZ
modified_at_remote     TIMESTAMPTZ
etag                   TEXT
content_hash           TEXT                   -- provider hash or our sha256 after download
is_folder              BOOLEAN
deleted_at             TIMESTAMPTZ            -- soft-delete when remote delete seen
document_id            TEXT                   -- FK to documents when indexed
matter_id              TEXT                   -- mapped matter (required for ACL universe)
status                 TEXT                   -- discovered | downloading | indexed | failed | ignored
UNIQUE (connection_id, provider_file_id)
```

### 5.4 `source_file_permissions`

Normalized remote ACL for retrieval filtering.

```text
source_file_id         TEXT FK
principal_type         TEXT                   -- user | group | anyone | domain
principal_id           TEXT                   -- provider user/group id (and later mapped member_id)
permission             TEXT                   -- read | write | owner
mapped_member_id       TEXT NULL              -- firm member when identity link exists
UNIQUE (source_file_id, principal_type, principal_id)
```

### 5.5 Identity mapping (minimal v1)

```text
identity_links
  member_id
  provider
  provider_user_id / email
  UNIQUE (provider, provider_user_id)
```

Without mapping, **fail closed**: either restrict sync to a matter whose `allowed_members` already covers the connecting user, or mark files `acl_unresolved` and exclude from search.

### 5.6 Link to existing document tables

Extend `documents` (additive):

```text
source_connection_id   TEXT
source_file_id         TEXT
provider               TEXT
provider_file_id       TEXT
```

Keep using `content_sha256`, `source_uri`, `mime_type`, `folder_path`, `document_versions.storage_uri`.

---

## 6. Connector interface (Python)

Language matches the existing FastAPI service. Pseudocode:

```python
class DocumentConnector(Protocol):
    async def authenticate(self) -> None: ...
    async def get_account(self) -> AccountInfo: ...
    async def list_files(self, cursor: str | None, scope: Scope) -> SyncPage: ...
    async def get_file(self, provider_file_id: str) -> FileMetadata: ...
    async def download_file(self, provider_file_id: str) -> AsyncIterator[bytes]: ...
    async def get_changes(self, cursor: str, scope: Scope) -> SyncPage: ...
    async def get_permissions(self, provider_file_id: str) -> list[Permission]: ...
    async def create_webhook(self, callback_url: str) -> WebhookHandle | None: ...
    async def disconnect(self) -> None: ...
```

`SyncPage` carries:

- `items: list[ChangeItem]` (`created` / `modified` / `deleted` / `permission_only`)
- `next_cursor: str | None`
- `done: bool`

Factory:

```text
get_connector(connection) → GoogleDriveConnector | MicrosoftGraphConnector
```

Sync engine:

```text
connector = factory.get(connection.provider)
page = await connector.get_changes(sync_state.cursor, scope)
for item in page.items:
    enqueue(process_change, item)
persist(page.next_cursor)
```

---

## 7. Permission model (hardest product constraint)

### 7.1 Two layers

| Layer | Meaning |
|-------|---------|
| **Firm matter ACL** (existing) | Who may see docs in this matter (`permissions.restricted` / `allowed_members`) |
| **Source ACL** (new) | Who may see this file in Drive/SharePoint |

Retrieval must satisfy **both** (intersection), still **in SQL before ranking**.

### 7.2 v1 pragmatic policy (recommended)

For the first shippable slice:

1. Connection is bound to a **matter** (or a small set of matters) at connect time.
2. Only members on that matter’s ACL can search synced docs.
3. Source ACL is **stored and audited**, but enforcement may start as:
   - **Strict mode (preferred for legal):** file visible only if mapped principal intersects current member **and** matter ACL allows.
   - **Matter-trust mode (dev/demo):** matter ACL alone; source ACL stored for later.

Default for production-shaped demos: **Strict mode** when identity mapping exists; otherwise do not index into the searchable corpus.

### 7.3 Service account vs user-delegated

| Mode | Risk | Use |
|------|------|-----|
| User OAuth (delegated) | Downloads only what that user can see | Safer for personal Drive / OneDrive |
| Admin / app-only (Graph application permissions) | Can download org-wide; ACL must be enforced locally | SharePoint libraries; requires strict ACL sync |

Plan: support **delegated** first; document app-only as Phase C with mandatory ACL tests.

---

## 8. Phased delivery

### Phase 0 — Foundations (1–2 weeks)

**Outcome:** Schema + queue skeleton + fake connector; no real OAuth.

**Status: implemented 2026-09-19** (feature flag `SOURCES_SYNC_ENABLED=false` by default).

- [x] Migration: `source_connections`, `source_sync_state`, `source_files`, `source_file_permissions`, `identity_links`, document link columns
- [x] Token encryption helper (AES-GCM via existing KeyVault pattern; key from env)
- [x] Redis queue workers: `sync`, `download`, `process` (inline drain default; Redis when `SOURCES_QUEUE_INLINE=false`)
- [x] `DocumentConnector` protocol + `FakeConnector` (fixtures with creates/updates/deletes)
- [x] Sync engine unit tests: cursor advance, delete tombstones, hash no-op, retry/backoff
- [x] Wire downloaded bytes into existing object store + extract / `create_version` path
- [x] Record feature origin in `legal-memory-retrieval/docs/legal/IP_ORIGIN_RECORD.md` (requirements-only inspiration)

**DoD:** Fake provider can sync N files into a matter; retrieval ACL tests still pass; unchanged file does not re-embed.

---

### Phase A — Google Drive (MVP provider) (2–3 weeks)

**Outcome:** Real OAuth + incremental sync for one Google account into one matter.

- [ ] OAuth 2.0 (authorization code + refresh); store encrypted tokens
- [ ] Initial discovery: Drive files.list (or changes.getStartPageToken + full walk)
- [ ] Persist `startPageToken` / `pageToken` in `source_sync_state`
- [ ] Incremental: `changes.list` with stored token
- [ ] Download supported MIME types (PDF, DOCX, Google Docs export → PDF/DOCX)
- [ ] Permission fetch (`permissions.list`) → `source_file_permissions`
- [ ] Optional: Drive push notifications → enqueue sync (still confirm via changes API)
- [ ] API: connect / disconnect / sync-now / connection status
- [ ] UI: replace simulated “Connect” with real status for Drive only
- [ ] Rate-limit handling (429 / exponential backoff), partial failure isolation

**DoD:** Add/modify/delete a file in Drive; within sync SLA only that file is fetched and index matches; deleted remote → soft-delete + chunk removal from search.

---

### Phase B — Microsoft Graph (OneDrive + SharePoint) (3–4 weeks)

**Outcome:** Same sync engine, new adapter; hierarchy-aware site/library selection.

- [ ] Entra ID OAuth (delegated) via Microsoft Graph
- [ ] OneDrive: drive delta query; store `deltaLink`
- [ ] SharePoint: list sites → select document libraries → per-drive delta
- [ ] Model folders/paths into `project_folders` / `folder_path` (reuse Phase 5 FirmOS ideas)
- [ ] Permissions via Graph (`permissions` / sharing); map to `source_file_permissions`
- [ ] Webhooks (Graph subscriptions) + delta reconcile
- [ ] UI: SharePoint site picker + OneDrive connect

**DoD:** Sync a SharePoint library and a OneDrive folder; hierarchy preserved; delta-only after initial sync; ACL intersection tested with two users.

---

### Phase C — Production hardening (ongoing)

- [ ] App-only Graph credentials (optional) with mandatory ACL eval suite
- [ ] Periodic full reconcile (cursor reset / inventory compare)
- [ ] Large file streaming, virus scan hook, max size policy
- [ ] Dead-letter queue + admin retry UI
- [ ] Metrics: sync lag, files/hour, API error rates, ACL unresolved count
- [ ] Multi-matter routing rules (path → matter mapping)
- [ ] Additional providers (Dropbox, Box, iManage) behind same interface
- [ ] Consider Temporal/Celery if Redis workers hit limits; Kafka only if volume demands it

---

## 9. API surface (sketch)

All under existing FastAPI app, auth consistent with `AUTH_ENABLED` / `X-Member-Id`.

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/sources/oauth/{provider}/start` | Begin OAuth; return redirect URL |
| `GET` | `/sources/oauth/{provider}/callback` | Exchange code; create connection |
| `GET` | `/sources/connections` | List connections + sync health |
| `PATCH` | `/sources/connections/{id}` | Pause, matter binding, path filters |
| `POST` | `/sources/connections/{id}/sync` | Enqueue incremental (or full) sync |
| `DELETE` | `/sources/connections/{id}` | Disconnect; revoke token; optional purge |
| `POST` | `/sources/webhooks/{provider}` | Provider push endpoint |
| `GET` | `/sources/connections/{id}/files` | Inventory / debug |

Processing continues to use existing ingest job polling where useful.

---

## 10. Job model (Redis-first)

```text
Queues
  source.sync          — advance cursor, enqueue file jobs
  source.download      — fetch bytes → object store
  source.process       — extract / chunk / embed (call existing ingest)
  source.permissions   — refresh ACL for a file or subtree
```

Job payloads carry `connection_id`, `provider_file_id`, `change_type`, `attempt`.

Rules:

- One active sync per `(connection_id, scope_key)` (Redis lock)
- Download/process: high concurrency with provider rate limits
- Idempotency key: `(connection_id, provider_file_id, etag|content_hash)`

---

## 11. Supported file types (v1)

Reuse existing extractors; expand only when needed.

| Type | Action |
|------|--------|
| PDF | Existing PDF extractor (+ OCR path if already present) |
| DOCX | Existing DOCX extractor |
| Google Docs / Sheets | Export via Drive API then extract |
| PPTX / XLSX | Phase C unless already supported |
| Images | OCR only if pipeline already has it; else `ignored` with reason |
| Shortcuts / Google Apps scripts | Skip |

---

## 12. Security checklist

- [ ] Encrypt tokens at rest; never log tokens
- [ ] Restrict OAuth redirect URIs; state/nonce CSRF protection
- [ ] Webhook signature / client-state validation
- [ ] Tenant isolation on all source_* queries
- [ ] SQL ACL filter before ranking (matter ∩ source)
- [ ] Secrets only in env / secret manager; audit new deps in `DEPENDENCY_AUDIT.md`
- [ ] Scope minimization (Drive: least privilege; Graph: least privilege)
- [ ] Soft-delete remote files from index promptly on delete events

---

## 13. Testing strategy

| Layer | What |
|-------|------|
| Unit | Cursor merge, change classification, permission intersection, idempotent reprocess |
| Contract | FakeConnector + recorded HTTP fixtures for Drive/Graph (VCR-style) |
| Integration | MinIO/local object store + Postgres; sync → retrieve with two members |
| Eval gate | Existing `retrieval_eval.py` must not regress on corpus; add a small **source-sync ACL suite** (new JSONL: same query, different member → different hit set) |
| Chaos | Missed webhook, expired token, 429 storm, mid-download kill |

Do **not** claim retrieval quality wins from connectors; measure sync correctness and ACL isolation separately.

---

## 14. Suggested package layout

```text
legal-memory-retrieval/
  app/
    sources/
      __init__.py
      models.py              # dataclasses / pydantic
      store.py               # CRUD for connections, files, sync_state
      crypto.py              # token encrypt/decrypt
      factory.py
      sync_engine.py
      permissions.py         # intersection helpers used by retrieval SQL
      workers.py             # Redis consumers
      connectors/
        base.py              # Protocol
        fake.py
        google_drive.py
        microsoft_graph.py
      oauth/
        google.py
        microsoft.py
      api/
        router.py
        webhooks.py
```

Keep provider SDKs behind the connector boundary so the sync engine stays provider-agnostic.

---

## 15. Dependency / license notes

Before adding packages (Google API client, MSAL, Graph SDK, etc.):

1. Check license (prefer Apache-2.0 / MIT / BSD)
2. Record in `docs/legal/DEPENDENCY_AUDIT.md` (or project equivalent)
3. Reject AGPL/GPL/SSPL without human approval

Prefer thin HTTP clients + official docs over heavy SDKs if that reduces license surface.

---

## 16. Mapping to FirmOS plan

This plan extends FirmOS **Phase 4 (async ingestion)** and **Phase 5 (hierarchy)** with a new **Phase: Universal Sources**:

| FirmOS idea | Sync-engine mapping |
|-------------|---------------------|
| Upload → object storage → workflow | Download → same object storage → same workflow |
| Per-file failure isolation | Per `source_files` + ingest_items |
| Folder preservation | `path` / `project_folders` from remote parents |
| Never sync-all in request path | OAuth returns immediately; workers do the rest |

---

## 17. Success metrics

| Metric | Target (MVP) |
|--------|----------------|
| Time from OAuth complete → first file searchable | < 5 min for ≤100 small PDFs |
| Incremental sync lag after change (poll) | < 5 min |
| Incremental sync lag (webhook + delta) | < 2 min |
| Unchanged file re-download rate | ~0% (etag/hash skip) |
| ACL false-positive (user sees unauthorized doc) | **0** in suite |
| Retrieval eval regression | None on frozen corpus |

---

## 18. Recommended build order (executive)

1. **Phase 0** — schema, FakeConnector, queue, hook into existing ingest  
2. **Phase A** — Google Drive end-to-end (prove the abstraction)  
3. **Tighten ACL** — identity links + SQL intersection  
4. **Phase B** — Microsoft Graph (OneDrive, then SharePoint site picker)  
5. **Phase C** — webhooks everywhere, reconcile, more providers, optional app-only  

**Key insight:** do not start with “SharePoint UI.” Start with **sync_state + connector protocol + one fake provider**, then Drive, then Graph. SharePoint is a hierarchy + delta adapter on the same engine.

---

## 19. Open decisions (resolve before coding Phase A)

| # | Decision | Locked for Phase 0 |
|---|----------|--------------------|
| 1 | Matter binding | **one connection ↔ one matter** (`config.matter_id`) |
| 2 | ACL mode | **matter-trust** (source ACL stored; SQL intersection deferred to Phase A+) |
| 3 | Google OAuth client | Defer to Phase A (Workspace preferred when starting Drive) |
| 4 | Worker runner | **Redis list queues + inline drain**; custom loop, not Celery/Temporal yet |
| 5 | Delete policy | **soft-delete index** (tombstone `source_files`, delete chunks); object purge later |
| 6 | Multi-tenant org id | **reuse `settings.tenant_id`** as `organization_id` |

---

## 20. Next step after this plan

When approved:

1. Lock answers to §19  
2. Implement Phase 0 behind a feature flag (`SOURCES_SYNC_ENABLED=false`)  
3. Land migration + FakeConnector tests  
4. Only then start Google OAuth credentials + Drive adapter  

No provider SDK work until Phase 0 DoD is green.
