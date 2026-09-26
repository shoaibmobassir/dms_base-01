# 06 — DB-backed tests

Closes: B12 and the "untested ethical wall" gap.

## Steps

1. `tests/test_ui_contract.py` — for every endpoint the SPA calls, against the seeded DB:
   status 200, response shape the frontend types expect, and non-empty data.
2. `tests/test_security.py` — traversal (S1), auth flag from `.env` (S2), key auth (S3),
   chat ownership (S5), and for each seeded restricted matter: non-member cannot see it via
   matters list/detail, documents, arguments, client detail, person detail, deadlines, search,
   retrieval; a member of its team can.
3. Fix or correct `test_sync_wrapper_score_raw_fallback` (B12) — decide which side is wrong.
4. Frontend: Vitest + Testing Library smoke test per kept page, rendering against a fetch stub
   **recorded from the seeded API** (`scripts/record_fixtures.py`), so fixtures are DB data, not
   hand-written.
5. `make test` target runs migrate → seed → pytest → frontend tests.

## Done when

- `pytest tests/` fully green.
- Security tests fail if any ACL clause is removed (spot-check by deleting one).
