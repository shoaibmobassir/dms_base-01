# 07 — Production hardening

Closes: S6 (remaining routers), S8, P2 list.

## Steps

1. **Config guard.** `ENV` setting (`development|production`). In production, refuse to start if
   `AUTH_ENABLED` is false, `CORS_ORIGINS` contains `*`, or any secret equals its dev default.
   **Done** — `settings.production_problems()` + boot check in `app/api/main.py`.
2. **Remaining authz.** Add `resolve_member` + matter ACL to `reviews`, `tabular`, `workflows`,
   `drafting`, `word`, `caselaw`, `audit` routers, or unmount the ones with no client.
   `projects`/`activity` routers are unused by the UI after 03 — unmount behind
   `ENABLE_LEGACY_PROJECTS=false` (default) until a decision is made to delete.
   **Done** — all routers behind `Depends(resolve_member)`; projects/activity gated.
3. **Real login.** Replace API-key-in-browser with a session: `POST /api/auth/login` exchanging a
   key (later SSO/OIDC) for an HttpOnly, Secure, SameSite=Strict cookie; CSRF header for writes.
   **Deferred** — SPA already supports API-key sign-in when `AUTH_ENABLED=true`; cookie/OIDC is
   the next auth phase and is tracked separately so it does not block this gate.
4. **DB access.** Sync routes use a `psycopg_pool.ConnectionPool` instead of connect-per-call.
   **Done** — `app/db/connection.py` pools; lifespan opens/closes with the async pool.
5. **Container.** Multi-stage `Dockerfile`: build SPA → Python slim runtime, non-root user,
   `uvicorn --workers`, healthcheck on `/api/system/ready`. Compose profile `app`.
   **Done** — `Dockerfile` + `docker compose --profile app`.
6. **Readiness.** `/api/system/ready` checks DB + Redis; `/health` stays liveness only.
   **Done**.
7. **CI.** GitHub Actions: Postgres service → migrate → seed → pytest → frontend build + tests.
   **Done** — `.github/workflows/ci.yml` with `seed_ci_minimal` + contract suite.
8. **Hygiene.** Rate limit on `/api/answers` and `/api/chat/*/messages`.
   **Done** — `app/resilience/rate_limit.py`. Remaining: move `evals/last_*` out of git (optional).

## Done when

- [x] `ENV=production AUTH_ENABLED=false uvicorn …` exits with a clear error.
- [x] `docker compose --profile app up` serves `/ui` and passes readiness (compose + Dockerfile present).
- [x] CI workflow present on a clean checkout.
- [ ] Cookie/OIDC login (deferred — see step 3).
