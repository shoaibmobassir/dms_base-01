# Ask the Firm stored answers: test of plan 19 §3 (2026-10-02)

Tested the **uncommitted working tree of the main checkout** (the other session's implementation of
`docs/plan/19_ask_docket_and_stored_answers.md` §3), served on port 8021 without `--reload`, member
`MEM-00001`, over HTTP and in a real browser (Playwright driving Google Chrome). The code under test is
`app/km/ask_answers.py`, `app/api/routers/answers.py`, `frontend/src/api/ask.ts`,
`frontend/src/pages/AskPage.tsx` and the built `static/` bundle, none of which are committed yet.

Scripts: `evals/ask_store_check.py` (HTTP) and `evals/ask_refresh_loop_check.cjs` (browser; set `PLAYWRIGHT_PATH`,
`CHROME_PATH`, `BASE`). Re-run both after the fix below; the loop check should show one POST and an unchanged id.

## What works

| Check | Result |
|---|---|
| First ask returns a stable id (`saved_id`) | yes |
| Same question again | 0.0 s, `saved: true`, same id, same answer, no `delta` events (no model call) |
| `GET /api/answers/saved/{id}` | 200 with answer, panel, citations; query echoed |
| `GET /api/answers/history` | lists the id |
| Unknown id | 404 |
| Another member opens my id | 404, no answer leaked (ACL at read time) |
| `POST /api/answers` (non-stream) | same behaviour, returns `saved_id` |
| Delete by id | row gone, id 404 |
| Browser: `/ui/ask?q=…` | one `POST /api/answers/stream` (the question must go to the server once), then the URL becomes `/ui/ask/<id>` |
| Browser: reload `/ui/ask/<id>` | `GET /api/answers/saved/<id>` only, no POST, no model call |
| Browser: reopen the old `?q=` link | `GET saved?q=`, redirected to `/ui/ask/<id>`, no POST |
| Browser: id opened in a fresh browser context | `GET saved/<id>` only |
| Built bundle | contains the `/api/answers/saved/` calls |

So an Ask answer now behaves like an Assistant session: it has an id in the URL and reopening it does not
call the model. The only time the query goes to the API is the first time it is asked.

## Defect 1 (severe): Refresh on `/ask/<id>` loops forever

Clicking **Refresh** on a saved answer (`data-testid="ask-refresh"`) re-runs the model, then keeps re-running
it every ~10 s with a new id each time, until the tab is closed. Trace (browser):

```
 9.6s  GET saved/:id, POST stream            click → refresh run
17.7s  NAV /ui/ask/<new id>   GET saved/:id, POST stream   again
28.1s  NAV /ui/ask/<new id>   GET saved/:id, POST stream   again
37.5s … 47.4s … 56.5s …                                    and again
```

Cause, in two parts:
1. `useAskStream` computes `const refresh = runKey > 0`. `runKey` is never reset, so any later run of the effect
   is also a refresh.
2. The refresh path deletes the saved row first (`_drop_saved` in `answers.py`, lines 44–45 and 66–67), so the
   re-saved answer gets a **new id**. `onSaved` navigates to the new id, `answerId` changes, the effect re-runs
   with `runKey` still 1, and the cycle repeats.

Each lap spends a full model call plus grounding. Rows do not pile up (one row per member/question/scope), but
the id changes every lap.

**Fix (small):**
- `answers.py`: do not call `_drop_saved` on refresh. Skip only the *read* of the stored row. `ask_answers.save`
  already upserts on `(member_id, query, scope, scope_type)` and returns the existing row's id, so the id stays
  the same, `onSaved` returns early (`answerId === savedId`), and the loop cannot start.
- `ask.ts`: make refresh one-shot as a second guard, e.g. keep `lastRunKey` in a ref and set
  `const refresh = runKey !== lastRunKey.current; lastRunKey.current = runKey;` inside the effect.

## Defect 2: a refresh changes the answer's id

Same cause as above. `refresh=true` over HTTP changed `b5fed21c…` to `87d0d165…` and the earlier id then
returned 404. A link shared or bookmarked before a refresh breaks. With the fix above the id is stable, as an
Assistant session id is.

## Minor

- The Refresh control only appears on a *saved* view (`ask.fromCache`). Right after a fresh ask there is no
  Refresh until the page is reloaded.
- While a refresh from `/ask/<id>` runs, the page heading shows "…" because the hook has no `query` (only the id).
- After the first ask the page issues one extra `GET saved/<id>` once the URL becomes `/ask/<id>`; harmless, but
  it replaces the streamed state with the stored copy.
- `ask_history` is still written (173 rows) beside `ask_answers` (15 rows); the history list falls back to it
  for older questions.

## Test hygiene

The tests created `ask_answers`/`ask_history` rows (questions starting "Appeal No. 163 of 2018, have we prepared
a brief note of arguments? …"); all were deleted afterwards. `ask_answers` is back to its 15 original rows.
