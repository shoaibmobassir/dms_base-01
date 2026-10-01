# 02 — Seed dataset in Postgres; remove backend fakes

Closes: B1, B2, B3, B4, B6.

The corpus (`../dummy-firm/data`, loaded by `scripts/ingest.py`) already provides members, clients,
matters, documents, chunks, arguments. What's missing is the data that lets the UI and the ethical
wall be exercised. All of it goes into Postgres — nothing in `frontend/src`.

## Steps

1. **Firm identity.** New table `firm_profile` (single row: name, descriptor, office, tenant_id).
   `GET /api/system/firm` returns it; `home/stats` uses it instead of the "Apex Chambers" literal.
2. **Court deadlines.** New table `court_deadlines` (`deadline_id`, `matter_id` FK, `title`, `kind`
   [hearing|filing|limitation|compliance], `due_date`, `court`, `owner_member_id` FK, `status`
   [open|done], `notes`). `/api/tasks` reads it with `ACL_CLAUSE` (joined through `permissions`).
3. **Ethical wall.** Seed marks a small, fixed set of matters `restricted = true` with
   `allowed_members` = that matter's team from `matter_members`. Choose matters deterministically
   (e.g. lowest 6 `matter_id`s among Open matters + a few Closed).
4. **Client notes replace fake "client memory".** New table `client_notes` (`client_id`, `kind`
   [prefers|avoid|terms], `text`, `source_matter_id`, `author_member_id`). `GET /api/clients/{id}`
   returns them; the literal block is deleted.
5. **Delete fabricated endpoints.** `/api/knowledge/precedents` and `/api/knowledge/clauses` are
   removed (no data model exists; the UI pages go in 03).
6. **Orphans.** Delete `project_activity` rows whose `project_id` has no `projects` row.
7. **`scripts/seed_demo.py`** — idempotent, deterministic (fixed dates relative to a fixed anchor,
   no randomness without a seed), runs after `ingest.py` + `migrate.py`. Prints what it did.
   `--reset` clears only the rows it owns.

## Done when

- `python scripts/migrate.py && python scripts/seed_demo.py` twice in a row → identical row counts.
- `SELECT count(*) FROM permissions WHERE restricted` > 0; `court_deadlines` > 0; `client_notes` > 0.
- No endpoint returns hard-coded business data (grep for literal names in `app/api/routers`).
