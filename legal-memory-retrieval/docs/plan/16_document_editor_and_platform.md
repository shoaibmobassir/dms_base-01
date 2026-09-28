# Plan 16 — Docs-style viewer/editor + platform phases

Started 2026-09-28. Status keys: `[ ]` open · `[~]` in progress · `[x]` done (with date + evidence).
Companion to the production plan (“Precentis DMS — Production Readiness, Azure Deployment & Next-Steps Plan”,
sections 5–11) and plan 15 (Part D long-document editing, owned by another session).

## Decisions (2026-09-28, product owner)

| Decision | Choice |
|---|---|
| Editor engine | **Hybrid now, Collabora later**: exact preview from a PDF rendition of the original file; our own editor over the document's paragraphs; saves write Word tracked changes into the *original* .docx (`app/drafting/docx_tracked.py`, plan 15 D3) and create a new version. APIs (lock, get file, save file) shaped so a Collabora WOPI connector can be added as “open in full editor”. |
| Co-editing | Not in v1: one editor at a time with an edit lock, presence and heartbeat; server-side draft autosave; versions. CRDT (Yjs) later. |
| Converter | **Gotenberg** (Apache-2.0) as a separate container, running LibreOffice (MPL-2.0); nothing linked into our code. |

## Requirements (technology-independent)

1. R1 See any firm document exactly as filed (PDF as-is; Word/Excel/PowerPoint as rendered pages).
2. R2 Edit Word documents in the browser like a document editor: text, headings, new/deleted paragraphs, undo/redo.
3. R3 Every save is a new immutable version by the signed-in person, with a note; untouched text keeps its exact formatting.
4. R4 Changes are visible as Word tracked changes with author and date; the version history shows who changed what; any two versions can be compared (redline on screen and as .docx).
5. R5 Only people with edit rights on the matter can edit; one editor at a time; others see who is editing.
6. R6 Work is never lost: drafts autosave; a save based on an old version is refused (no silent overwrite).
7. R7 PDFs (and other non-editable files) can be annotated/commented; text changes need a Word version.

## Phase E — viewer/editor (this plan)

- [x] E0 Gotenberg service in `docker-compose.yml`; `app/documents/pdf_render.py` uses `GOTENBERG_URL` first,
      local LibreOffice second; licences in `docs/legal/DEPENDENCY_AUDIT.md`. Gate: Acme SPA .docx renders as PDF.
      **Done 2026-09-28:** Gotenberg 8 container on 127.0.0.1:3000; `to_pdf` tries it first (content-hash cache). Word files render in the exact view (e2e `exact view renders the Word file as pages`).

- [x] E1 Versions API: upload a file as the next version (`POST /documents/{id}/versions/upload`, multipart,
      `base_version_id`, note, label) — author from the session, never the client; `document_locks` (TTL +
      heartbeat); `document_events`; compare (`GET /documents/{id}/compare?from=&to=` JSON redline,
      `.../compare.docx` tracked changes in the *from* file's formatting).
      **Done 2026-09-28:** `app/documents/editing.py` + `/api/editor` (paths are `/api/editor/documents/{id}/versions|lock|compare|compare.docx|history`); migration `20260928a_document_editing.sql`.

- [x] E2 Editor backend: `GET /documents/{id}/edit` (paragraph model of the current version: pid, style,
      runs with bold/italic/underline) · lock/heartbeat/release · `PUT /documents/{id}/draft` autosave ·
      `POST /documents/{id}/edit/save` {base_version_id, ops, note, mode tracked|clean} → tracked changes in
      the original .docx (or accepted) → new version. Text-only documents (no original file) save as a text version.
      **Done 2026-09-28:** edit model / lock / draft / save (tracked|clean) / text-version save. Save reads the file once, fast style lookup (`style_namer`, 13.6k paragraphs: 4.1 s → 0.6 s); vectors of unchanged chunks reused, the rest embedded in the background under a per-document advisory lock (fixes a chunk-replace/embed deadlock that left a version with no chunks). Lock TTL 5 min, heartbeat 90 s.

- [x] E3 Editor UI (TipTap/ProseMirror, MIT): page canvas, toolbar (undo/redo, Normal/H1/H2, bold/italic/
      underline), paragraph ids kept as node attributes; “Exact view” (PDF) ⇄ “Edit”; changes panel (my
      edits vs base), version panel, lock/presence banner, autosave indicator, save dialog (note, tracked/clean).
      **Done 2026-09-28:** `frontend/src/pages/DocumentEditorPage.tsx`, `lib/editorOps.ts`, `components/editor/*`; route `/documents/:id/edit`, Edit button on the document workspace. Page is its own scroll container (was 80 px too wide, long documents could not scroll). Toolbar has undo/redo only: the style and bold/italic/underline buttons are left out of v1 because formatting changes are not written back (see Known v1 limits).

- [x] E4 Tests: pytest (upload version attribution, lock conflicts + expiry, stale base 409, read-only 403,
      save → reopen → accepted text == edited text, rejected == original, untouched formatting signature equal)
      and Playwright (open → edit → save → v+1 in history with author → compare shows the change).
      **Done 2026-09-28:** `tests/test_document_editor.py` (15) + `tests/test_document_comments.py` (7); `frontend/e2e/editor.spec.ts` (3). Full `pytest tests/`: 806 passed, 1 skipped; Playwright `--project=app`: 41 passed, 4 LLM-gated skipped.

- [x] E5 Fidelity eval `evals/editor_roundtrip_eval.py` on real uploaded .docx + plan-15 fixtures:
      untouched-paragraph formatting 100 %, accept_ok / reject_ok 100 %, save p95 < 3 s at 400 pages.
      **Done 2026-09-28:** `evals/editor_roundtrip_eval.py` over live HTTP → `evals/last_editor_roundtrip.json`. 10/100/400 pages × 3 rounds: read/accept/reject/untouched-formatting/tables/next-edit/vectors all 100 %; 400-page save p95 2.24 s (was 7.7 s), edit-model load 0.5 s (was 2.4 s), rendition 3.9 s, ~97 % of vectors reused at save.

- [x] E6 PDF annotation/comments in the exact view (existing annotations API); “needs a Word version” notice.
      **Done 2026-09-28:** comments on the exact view: select text on a rendered page → comment (page + boxes in page fractions + quote), one level of replies, resolve/reopen, delete by author/manager, per-version with a count of threads on other versions. Reuses `annotations` (migration `20260928b_document_comments.sql`), `app/documents/comments.py`, `/api/editor/documents/{id}/comments`; viewer gained `marks` / `onSelectText` (additive). Works for PDFs and Word renditions alike.

- [ ] E7 (later) Collabora WOPI connector: CheckFileInfo/GetFile/PutFile/Lock on the same lock + version APIs.

**Known v1 limits** (by design): formatting changes inside edited text (e.g. making a word bold) are not written
back — inserted words take the formatting of the run they join; tables, headers/footers, footnotes and fields
are shown in the exact view but not editable in the browser (Word add-in / Collabora for those).

## Platform phases (production plan §5–§11), in order after Phase E

- [ ] P1b Document-level privacy (private draft / restricted document), enforced at every document read,
      with an endpoint wall matrix test.
- [ ] P2 Write layer: matters, staffing with start/end dates, timeline events, arguments, related matters,
      clients (intake + conflict check), people; domain-event outbox + SSE; Home “my work”.
- [ ] P3 Calendar: events model, Mine/My team/Matter/Firm filters, create/edit (court deadlines confirmed),
      ICS feed; Outlook sync after Azure/Entra.
- [ ] P4 Word add-in (NAA auth, open/save as version) — reuses E1/E2 APIs.

## Log

- 2026-09-28 — Plan written; decisions above. Reusing `app/drafting/docx_tracked.py` (plan 15 D3, other
  session) for the save path — imported, not modified.
- 2026-09-28 — E0–E6 done (evidence on each item). Found while testing: the editor e2e stalled for 24 min
  because the test server fetched models from the network at warm-up (now `HF_HUB_OFFLINE=1` in
  `playwright.config.ts`); python-docx `paragraph.style` scans the styles part per unstyled paragraph (fixed in
  the shared DOCX extractor too, output identical on 62 files); `save_version_chunks` replaces all of a
  document's chunks, so vector reuse snapshots them first. Open issues: comments stay on the version they were
  made on (no carry-forward to new versions yet); no "take over lock" for managers (stale locks now clear in 5 min).
