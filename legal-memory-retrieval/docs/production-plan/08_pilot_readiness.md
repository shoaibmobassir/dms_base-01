# 08 — Pilot readiness (from the 24 Sep reviews)

Sources: `PRODUCTION_READINESS_REVIEW.md` (P0-01…P0-06, P1 list),
`../docs/enterprise-production-readiness-review.md` (pilot gates 1–10, §8 order of work),
`../firmos_production_actionable_plan.md` (phase status overlay).

Each item below is either **code in this repo** (implemented here, with tests) or
**outside the repo** (needs a decision, an account, or a contract — listed in §3).

## 1. Holes found while verifying the reviews (not in the reviews)

| # | Finding | Evidence |
|---|---|---|
| N1 | Upload batches skip the matter ACL: any member can upload into a restricted matter | `routers/uploads.py create_batch` passes `matter_id` straight through |
| N2 | Upload batches have no owner check: any member can read or run any batch by id | `get_batch`, `run_batch` |
| N3 | Downloading an uploaded original returns 404 (path computed as `root/tenant/doc/filename`, but uploads use the object-store key layout) | `documents_router.document_download` |

## 2. Implemented here (in order)

| Step | Closes | Work |
|---|---|---|
| A1 | P0-02 | Generated files get an owner row (`generated_artifacts`); download checks owner before bytes leave; unknown ids 404 |
| A2 | P0-06, N1–N3 | Uploads: matter ACL on create, batch owner on read/run, streamed to object store with per-file / per-batch size caps and count cap, extension + magic-byte allow-list, quarantine status, download of originals through the object store with ACL |
| A3 | P0-05 | Word task pane renders results as text nodes; `static/_legacy` removed from the served tree; security headers (CSP, frame-ancestors for Office only on the task pane, nosniff, referrer policy) |
| B | P1-4, gate 10 (part) | Append-only, hash-chained `audit_events` (DB trigger forbids UPDATE/DELETE): sign-in, ask, chat prompt/answer, retrieval, download, export, upload, admin change; admin JSONL export; feeds matter activity (UI roadmap Q2) |
| C | P0-04, gate 2 | OIDC authorization-code + PKCE login, server-side sessions in an HttpOnly/Secure/SameSite cookie, CSRF token on writes, logout/revocation; members matched by verified email; API keys kept for service callers only; SPA stops storing keys |
| D | P0-06, gate 10 (part) | Ingest off the request path: DB-backed job queue + `ingest` worker process (upload → parse → embed); API only enqueues; Compose `worker` service |
| E | P0-01 (part), P1-6, P1-8, gate 7 (part) | Secrets from mounted files (`SECRETS_DIR`), log redaction of keys/tokens, backup + restore-drill script with written RPO/RTO, runbooks, one CI workflow running the full suite + Playwright + retrieval eval gate + dependency audit + SBOM, locked Python requirements |

## 3. Outside this repo — needs you

| Item | Why it can't be finished here | Default |
|---|---|---|
| IaC for the dedicated silo (P0-01, gates 3–7) | Needs a cloud choice and Terraform (not installed); can't be validated without an account | AWS first (Bedrock already integrated); Terraform modules written and `terraform validate`d once installed |
| Malware scanning (P0-06) | ClamAV is GPL-2.0 — separate service, but needs legal sign-off per `DEPENDENCY_AUDIT.md` | Scanner adapter + quarantine built; engine off until approved |
| Microsoft Graph connector | Needs an Entra app registration and a test tenant | After the pilot, per the review |
| Tenant column + RLS (P0-03) | Review says first firms get a dedicated stack; RLS is a later programme | Not started |
| Pen test, DPA, SOC 2 timeline, subprocessors, on-call | Not code | — |

## 4. Status (2026-09-24, evening)

| Step | Status | Evidence |
|---|---|---|
| A1 generated-file download | **Done** | owner-bound `generated_artifacts`; filenames sanitised; object store confined to its root — `tests/test_pilot_hardening.py` |
| A2 uploads | **Done** | matter ACL, batch owner, streamed + hashed, size/count caps (413 before parsing), magic-byte allow-list, quarantine, scanner fails closed; original download via object store |
| A3 HTML/headers | **Done** | Word pane text-node rendering, no inline handlers; `static/_legacy` → `archive/`; hash-based CSP, Office-only framing for the pane, API docs off in production; no CSP violations in the browser suite |
| B audit stream | **Done** | `audit_events` append-only (triggers) + hash chain; admin export (JSON/JSONL) + verify; matter activity feed; tamper test — `tests/test_audit_stream.py` |
| C firm sign-in | **Done** | OIDC code+PKCE+nonce, JWKS verification, HttpOnly session + CSRF, sign-out, admin revocation, idle timeout — `tests/test_oidc_sessions.py` (24) and a real-browser flow against `scripts/fake_idp.py` (`frontend/e2e/auth.spec.ts`) |
| D ingest worker | **Done** | `INGEST_MODE=queue`, `python -m app.workers.ingest`, SKIP LOCKED claims, stale reclaim; Compose `worker` service |
| E ops | **Mostly done** | secrets from files (`SECRETS_DIR`), log redaction, `scripts/backup.py` + verified restore drill (PASS: 14 tables, 37 originals, audit chain, 17 s), hash-locked `requirements.lock`, `evals/gate.py` retrieval gate. **Not done:** consolidated CI workflow, runbooks, image rebuild with the lock |

Found and fixed along the way: schema drift (a fresh database lacked `document_versions.mime_type` and 7 indexes — migration `20260924h`); `migrate.py` could not bootstrap an empty database; `seed_ci_minimal.py` renamed real members when run on the dev database (fixed; names restored from `dummy-firm/data/members.json`); tests that silently depended on the full corpus.

Stopped because the host disk filled (image builds) and Docker Desktop's storage failed; the dev Postgres container is down until Docker is restarted.
