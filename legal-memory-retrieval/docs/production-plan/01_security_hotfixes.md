# 01 — Security hotfixes

Closes: S1, S2, S3, S4, S5, S6 (read paths used by the UI), S7, B11.

## Steps

1. **SPA static handler (S1).** Resolve the requested file with `Path.resolve()` and serve it
   only if it is inside `static/`. Anything else falls back to `index.html`.
2. **Auth flag (S2).** Add `auth_enabled: bool = False` to `Settings`; `app/auth/deps.py` reads
   `settings.auth_enabled` at call time (tests can monkeypatch it).
3. **API keys (S3).** New migration `app/db/migrations/20260924_api_keys.sql` creating `api_keys`
   (`IF NOT EXISTS`). Add `scripts/migrate.py` that applies every `migrations/*.sql` in name order and
   records them in `schema_migrations`. `_load_keystore` becomes a single-row lookup by hash and
   no longer swallows DB errors (a DB outage must be a 503, not a 401).
4. **Missing identity (S4).** In `resolve_member`, when auth is on, identity is mandatory (already
   true). When auth is off, an absent `X-Member-Id` stays "anonymous admin" for local tools, but
   the SPA must always send one (plan 03/04). `ENV=production` refuses to start with auth off (07).
5. **Chat authorization (S5).** Every `/api/chat` route takes `member_id = Depends(resolve_member)`.
   - `POST /sessions`: owner = resolved member, ignoring the body's `member_id` when auth is on.
   - `GET/PATCH/DELETE /sessions/{id}`, `POST .../messages|ask`: 404 unless the session's
     `member_id` equals the caller (anonymous-dev caller may access sessions with no owner only).
   - `GET /sessions` lists only the caller's sessions.
6. **ACL on UI read paths (S6).** Apply `ACL_CLAUSE` to `knowledge/arguments`, `clients` detail +
   client matters, `people/{id}` matter list, `home/stats` (counts in scope), `teams` matter counts.
7. **CORS (S7).** `CORS_ORIGINS` setting (comma list, default `http://localhost:5173`);
   `allow_credentials` only when origins are explicit.
8. **docker-compose (B11).** Fix `redis` indentation so it's a service.

## Done when

- `GET /ui/..%2f.env` → SPA shell, never file contents (regression test).
- With `AUTH_ENABLED=true` in `.env` only (not exported), requests without `X-Api-Key` → 401.
- Member B gets 404 on member A's chat session; listing returns only own sessions.
- A restricted matter is invisible to non-members on every endpoint above (tested in 06 with seed data).
- `docker compose config` lists `postgres` and `redis` services.
