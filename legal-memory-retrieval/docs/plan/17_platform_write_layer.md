# Plan 17 — Editor gaps, document privacy, write layer, calendar

Started 2026-09-28. Status keys: `[ ]` open · `[~]` in progress · `[x]` done (with date + evidence).
Follows plan 16 (Phase E). Decisions (product owner, 2026-09-28): scope P1b + P2 + P3 (P4 Word add-in waits for
Azure/Entra); formatting written back as Word tracked formatting changes; document privacy = Private + Restricted,
both only narrow matter access, `walls.manage` holders can always read and every such read is audited.

## Phase G — editor gaps

- [x] G4 Legacy annotations endpoint takes the author from the session, never the request.
      **Done 2026-09-28:** also refuses `comment`-type rows (comment rules live in `/api/editor`) and versions of other documents; test `test_legacy_annotation_endpoint_takes_the_author_from_the_session`.
- [x] G3 Lock tokens (per window) + takeover (same member, or matter manager); superseded window keeps its draft.
      **Done 2026-09-28:** `X-Edit-Lock` token on heartbeat/draft/save/upload/release (sessionStorage per window, survives reload); 409 reasons `held` / `held_by_you_elsewhere` / `superseded`, `can_take_over`; `?takeover=true` → `lock.takeover` event + audit. Superseded window turns read-only on its next autosave or heartbeat. Tests: 2 pytest, e2e “a second window … takes over”.
- [x] G2 Open comment threads carry forward to new versions (re-located by quote in the new rendition; "text changed" when not found).
      **Done 2026-09-28:** `list_comments` returns open earlier-version threads as `carried`; viewer marks can be a `quote` (found with `findQuoteInRuns`, boxes from the text layer, `onMarksLocated`); detached threads link to their version (`/render?version_id=`). Found + fixed: `/render` of the current version was cached 5 min, so a new version showed stale pages — now `no-cache` unless a version is named, and the exact view always names it. e2e “an open comment follows the document …”.
- [x] G1 Tracked formatting write-back (bold/italic/underline, paragraph style) via `app/documents/docx_format.py`;
      toolbar; eval checks format_accept_ok / format_reject_ok / render_ok.
      **Done 2026-09-28:** `w:rPrChange` / `w:pPrChange` by the session member, applied over the accepted text after the text pass (inserted text/paragraphs formatted directly); ops `format` + `style`/`runs` on replace/insert; style select + B/I/U toolbar (selection synced from the DOM before toolbar commands). `tests/test_docx_format.py` (7), 2 API tests, e2e “bold a clause and restyle …”. Eval (10/100/400 pages): format_accept_ok / format_reject_ok / tracked_render_ok (LibreOffice) 100 %, all earlier checks 100 %, 400-page save p95 2.28 s. Also fixed: vector-reuse query planned as a nested loop (100-page save 3.3 s → 1.2 s).

## Phase P1b — document privacy + wall sweep

- [x] Holes: chunk context ACL; review fetch/job/findings ACL; tabular/workflows `resolve_member`; Assistant
      `resolve_document_text` ACL; session doc cache keyed by ACL epoch; lapsed staffing (`ended_at`) loses access.
      **Done 2026-09-28:** all closed, plus one found during the sweep: `POST /api/projects/{id}/documents/{doc}` copied any document (any matter) into a visible matter — now requires read access and refuses private/restricted copies. The Assistant reader re-checks access on every read (stronger than an epoch key). Lapsed access: `acl_refresh_lapsed()` + `app/access/refresher.py` (every 10 min). Regression tests in `tests/test_document_privacy.py`.
- [x] Schema `document_access` / `document_shares`, compiled `visible_to` on documents + chunks, triggers, epoch.
      **Done 2026-09-28:** migration `20260928c_document_privacy.sql`; `doc_acl_state` feeds `acl_epoch()`.
- [x] `DOC_ACL` predicate in every document/chunk read path; matter aggregates; matter profiles exclude restricted docs.
      **Done 2026-09-28:** `doc_acl(alias)` beside every matter ACL clause (storage stores, retrieval channels, KM passages/panel/directory, documents/matters/home/activity/search/projects/review/chat routers); resolver index and matter profiles use only matter-visible document titles. SQL A/B: retrieval query p95 unchanged within noise (127–142 ms vs 134–150 ms).
- [x] Privacy API + audit (`document.privacy.change`, `document.privileged_read`); UI chip/dialog; private uploads.
      **Done 2026-09-28:** `app/documents/privacy.py`, `GET/PUT /api/editor/documents/{id}/privacy`, `/share-targets`; `PrivacyControl` chip + dialog (workspace + editor), lock icon in lists, “Private draft” on ingest (author_id now recorded).
- [x] Wall-matrix tests (`tests/test_document_privacy.py`), retrieval gate + latency unchanged.
      **Done 2026-09-28:** 16 tests — 16 surfaces × owner / shared member / shared team / lead / stranger / auditor
      for private and restricted, audit of privileged reads, who may change, row_version, share validation, team
      changes, new versions stay private, private upload, epoch, hole regressions, lapsed staffing. e2e
      `privacy.spec.ts`. `pytest tests/`: 834 passed, 1 skipped; Playwright: 45 passed, 4 LLM-gated skipped.
      Ask the Firm live eval (HTTP, 109 q): 109/109 pass (was 108/109), evidence p50 462 → 322 ms; total p50
      10.5 → 12.8 s is LLM/grounding time (model variance), not retrieval. `evals/retrieval_eval.py` + `gate.py`
      could not be used: `evals/dataset.jsonl` targets an older synthetic corpus (only 427 of its 2,039 gold
      document ids exist; its matter ids none) — `last_retrieval_run.json` restored; needs a rebuilt dataset.

## Phase P2 — write layer

- [x] Schema: matter/argument audit columns, `matter_events`, `matter_links`, `conflict_checks`, client status, `domain_events`, permissions.
      **Done 2026-09-28:** migration `20260928d_write_layer.sql`; new permissions `clients.create` (partner, risk, admin), `conflicts.decide` (risk); onboarding reuses `users.manage`.
- [x] Matters create/edit/close; staffing with dates; timeline events; arguments; related matters.
      **Done 2026-09-28:** `app/firm/matters.py` + `app/api/routers/firm.py`. Create needs `matters.create`, an active client; creator leads; access defaults to team (restricted → grants for the team). Edit needs manage + `row_version`; a matter always keeps a lead; screened people cannot be staffed; ended assignments lose team access. Links need edit on both matters and never reveal a walled matter. Timeline = document dates + entered events; activity feed shows the new actions.
- [x] Clients intake + conflict check (redacted hits on invisible matters); decisions.
      **Done 2026-09-28:** `app/firm/clients.py`: trigram search over clients (names, aliases, subsidiaries) and every matter's opposing party (walls included); requester sees "a matter you cannot see — ask Risk"; no hits → clear; hits → Risk decides (waive/conflict need reasons); client active / prospective / declined follows the decision; matters cannot be opened for non-active clients.
- [x] People self-edit + onboarding (`users.manage`).
- [x] Domain events + SSE stream (ACL-filtered) + frontend live invalidation.
      **Done 2026-09-28:** `domain_events` written in the same transaction as each write; `/api/events` (poll) and `/api/events/stream` (SSE, reconnect with Last-Event-ID/`since`), filtered by matter ACL, document privacy and conflict-check ownership; the cursor moves past hidden events. `useLiveEvents` (fetch stream) invalidates matter/matters/clients/people/my-work queries.
- [x] Home "my work".
- [x] UI dialogs; tests `tests/test_firm_writes.py`; Playwright `firm.spec.ts`.
      **Done 2026-09-28:** New matter, edit/close, team editor with dates, timeline and argument editors, link dialog, client intake wizard + Risk queue, "Edit my expertise", Admin onboarding, My work on Home. 14 pytest; 3 e2e (incl. a second browser seeing a timeline entry live). E2E records are prefixed `E2E-TMP` and removed by `e2e/global-teardown.ts` → `scripts/e2e_cleanup.py`.

## Phase P3 — calendar

- [x] `calendar_events`, deadline confirmation (second lawyer), ICS feeds (token, revoke, redaction).
      **Done 2026-09-28:** migration `20260928e_calendar.sql` (existing docket deadlines marked confirmed-as-imported); `app/firm/calendar.py`. Hearing/filing/limitation dates stay unconfirmed until a lawyer who neither entered nor owns them confirms; moving the date re-opens confirmation. ICS: token hashed at rest, rotate/revoke, restricted matters shown as "Restricted matter" unless opted in, `[UNCONFIRMED]` prefix, RFC 5545 escaping and folding; feed router mounted without the sign-in dependency (the token is the credential).
- [x] Calendar API with Mine / My team / Matter / Firm scopes.
      **Done 2026-09-28:** matter-linked items follow the matter ACL; personal events only owner + attendees; attendees of matter events must see the matter.
- [x] CalendarPage: scopes, create/edit, confirm, week view, subscribe; tests `tests/test_calendar.py`, `calendar.spec.ts`.
      **Done 2026-09-28:** list/week/month, scope tabs, new event / new court date, item dialog (confirm, move, done, delete), subscribe dialog. 5 pytest; 2 e2e; existing calendar e2e updated to the scoped API.

Verification (2026-09-28): `pytest tests/` 853 passed, 1 skipped; Playwright `--project=app` 50 passed, 4 LLM-gated skipped.

## Log

- 2026-09-28 — Plan written from exploration: document reads are matter-ACL only; several unchecked paths (see P1b
  holes); matters/clients/people are read-only; calendar reads `court_deadlines` only; no outbox/SSE besides chat.
- 2026-09-28 — Phase G and P1b done (evidence on items). Stale eval found: the frozen retrieval dataset no longer
  matches the corpus (see P1b last item) — rebuild it from the current corpus before trusting `gate.py` again.
- 2026-09-28 — P2 and P3 done (evidence on items). Noted: the Playwright auth stack uses port 8011 with
  `reuseExistingServer`, so ad-hoc eval servers must use another port (8021) or the auth project could hit a
  server without sign-in. Open: Outlook/Graph calendar sync (after Azure/Entra); P4 Word add-in; rebuild
  `evals/dataset.jsonl` for the current corpus.
