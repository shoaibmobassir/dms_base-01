# Production plan — execute in order

Findings live in [`AUDIT.md`](AUDIT.md). Each plan below closes a set of audit ids.
Plans are sequential: don't start N+1 until N's **Done when** checks pass.

| # | Plan | Closes | Status |
|---|---|---|---|
| 01 | [Security hotfixes](01_security_hotfixes.md) | S1–S7, B11 | **done** |
| 02 | [Seed dataset in Postgres; remove backend fakes](02_seed_dataset.md) | B1–B4, B6 | **done** |
| 03 | [Prune the frontend](03_frontend_prune.md) | B5–B7, frontend table | **done** |
| 04 | [Wire every page to the API](04_frontend_api_wiring.md) | AppContext, B6 | **done** |
| 05 | [Chat experience](05_chat_experience.md) | B8–B10 | **done** |
| 06 | [DB-backed tests](06_db_backed_tests.md) | B12, test gaps | **done** |
| 07 | [Production hardening](07_production_hardening.md) | S6 (rest), S8, P2 | **in progress** |

## Rules that apply to every plan

1. **No frontend data.** The UI renders only what the API returns. Demo content lives in
   Postgres via `scripts/seed_demo.py`, never in `frontend/src`.
2. **ACL before data.** Every endpoint that returns matter-derived data takes
   `member_id = Depends(resolve_member)` and filters with `ACL_CLAUSE`.
3. **Clean room.** `mike/` is AGPL. Use it only to write technology-independent requirements
   (see `05_chat_experience.md`), then design independently. Record inspirations in
   `docs/legal/IP_ORIGIN_RECORD.md`.
4. **Gates.** `pytest tests/` green, `npm run build` green, and the plan's own checks.

## How to run everything locally

```bash
docker compose up -d                       # Postgres :55432, Redis :6380
source .venv/bin/activate
make migrate seed                          # schema + demo deadlines / ethical wall / firm
uvicorn app.api.main:app --port 8000
cd frontend && npm run dev                 # http://localhost:5173/ui  (proxies /api)
```

CI: `.github/workflows/ci.yml` — migrate → `seed_ci_minimal` → `seed_demo` → contract suite + frontend build.
