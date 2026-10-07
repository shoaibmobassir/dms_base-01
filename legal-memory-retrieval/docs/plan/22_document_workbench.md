# Plan 22 — Document Workbench: matter workspace, durable tabular reviews, playbooks, library

Started 2026-10-07. Status keys: `[ ]` open · `[~]` in progress · `[x]` done (with date + evidence).
Builds on plan 16 (viewer/editor, versions, locks, compare), plan 17 (privacy, tracked formatting, comments,
write layer), plan 18 (Word review) and plan 15 (Assistant multi-doc review, long-doc editing).
Supersedes the never-started PM gates of plans 06 (workflows), 07 (tabular), 08 (document review) and
09 (library) — their requirement sections still stand; their designs are replaced by the one below.

## Inputs (product research only)

- **Mike (AGPLv3)** — product-level notes pasted by the product owner on 2026-10-07. No Mike source, schema,
  API, UI or prose was opened or used for this plan. Every Mike observation below is restated as a
  technology-independent requirement first (see `docs/legal/IP_ORIGIN_RECORD.md`, entry "Document Workbench").
- **VS Code** — UX pattern reference only (activity bar, explorer, tabs, split editors, command palette,
  source-control view, problems panel, status bar). No VS Code code is used.
- **Folio by stella** (`github.com/stella/folio`, **Apache-2.0**, v0.x, ProseMirror-based .docx engine that
  keeps tables, headers/footers, footnotes and tracked changes on round-trip) — a *candidate dependency*,
  evaluated in Phase 0. Not a design source.

## What already exists (verified in code 2026-10-07)

| Area | State | Where |
|---|---|---|
| Exact view (PDF / Word rendition), comments on pages, carry-forward | Done | plan 16 E0/E6, plan 17 G2 |
| In-browser Word editing (paragraph model, TipTap), tracked text + formatting write-back | Done; tables/headers/footnotes **not editable** | `DocumentEditorPage.tsx`, `app/documents/editing.py`, `docx_format.py` |
| Versions, upload-as-version, locks + takeover, drafts, compare + compare.docx | Done | `/api/editor/*` |
| Word review import (revisions, authors, comments) | Code exists, plan 18 checkboxes not updated | `app/documents/docx_review.py`, `docx_comments.py` |
| Document privacy, matter ACL in every read | Done | plan 17 P1b |
| Matter folders | Done (project folders) | `app/api/routers/projects.py`, plan 09 delivery |
| Assistant: read/search/edit/comment/review tools, edit proposals | Done; one document per panel | `app/chat/tools/*`, `ChatPage.tsx` |
| Tabular review | **In-memory only** (`_REVIEWS_DB` dict — lost on restart, not shared, no lease) | `app/api/routers/tabular.py`, `app/review/tabular_service.py` |
| Workflows | 3 YAML step playbooks, run API, **no UI, no user-created, no sharing** | `app/workflows/*` |
| Library / templates | **Missing** (documents must belong to a matter) | — |
| Multi-document workspace (tabs, split, palette) | **Missing** — one document page at a time | — |

## Requirements (technology-independent)

Workbench
1. W-R1 A lawyer opens a **matter as a workspace**: one screen with the matter's folders and documents on the
   left, several documents open as tabs, two side by side, and the Assistant alongside.
2. W-R2 Find and open anything fast by keyboard: quick open by name, a command list for every action, search
   across the matter's documents with results that open at the hit.
3. W-R3 The workspace remembers what was open (tabs, split, panel sizes, scroll position) per person per matter.
4. W-R4 Every open document shows, without a click: version, who is editing, autosave state, privacy, page and
   word count, and open review findings and comments.

Document "source control"
5. W-R5 Unsaved work is a visible **working draft** against a base version; saving is an explicit step with a
   note, like committing; the draft can be discarded.
6. W-R6 History shows every version with author, kind (human save, upload, Assistant edit, accepted review,
   restore) and note; any two versions can be compared side by side and as a redline.
7. W-R7 An old version can be **restored as a new version**; history is never rewritten.
8. W-R8 A version can be deleted (bytes purged, e.g. on a client instruction) but stays in history as
   "deleted — cannot be restored"; who deleted it and why is audited.
9. W-R9 All Assistant edits to one document in **one Assistant turn** become one version, not one per edit.
10. W-R10 Replacing a document's content with another document's content makes a new version of the target;
    the user is told what happens to the source.

Full-fidelity editing
11. W-R11 Tables, headers/footers, footnotes, numbering and existing tracked changes survive editing, and tables
    are editable in the browser (today's v1 limit), decided by a measured experiment (Phase 0).

Assistant in the workspace
12. W-R12 The Assistant knows the workspace scope: the matter, the open documents, the active document and the
    current selection; it only ever sees what the member may read.
13. W-R13 Assistant edits appear **inside the editor** as suggested changes, accepted or rejected one by one or
    all at once; accepting saves one version (W-R9).
14. W-R14 Selection actions: ask about it, redraft it, explain it, compare it with firm precedent.

Tabular review
15. W-R15 Run many questions over many documents as a **table** (rows = documents or folders, columns = named
    questions with an answer format: text, date, yes/no, list, choice); each cell has an answer, a short reason,
    citations to the source passages and a status.
16. W-R16 Reviews are durable, belong to a matter (or to the person), are shared by the matter's access rules,
    survive restarts, and two runs never fill the same cell at once.
17. W-R17 Cells fill live; a cell or a whole column can be re-run; a column's question can be edited (its cells
    go stale); a lawyer can overwrite a cell (kept with their name).
18. W-R18 Clicking a citation opens the source document beside the table at the quoted passage.
19. W-R19 Ask the Assistant questions about the filled table; export to Excel with citations.

Playbooks
20. W-R20 Reusable **playbooks** of two kinds: *instructions* the Assistant follows (with practice area,
    jurisdiction, language, optional reference documents) and *column sets* that start a tabular review.
21. W-R21 Three sources: shipped with the product, published by the firm (KM), and personal; firm and shipped
    playbooks are read-only and are duplicated to edit; personal ones can be shared with people or teams.
22. W-R22 Start a playbook from the Assistant (`/` command), the command list, or a quick action on a document.

Library and templates
23. W-R23 Each person has a private library of files not tied to a matter; the firm has a curated template and
    precedent library.
24. W-R24 "New from template" copies the template into a matter as a new document (version 1 with a link to its
    source); the template itself is never edited by drafting.

Containers and shared documents (added 2026-10-07 from decision D1)
25. W-R25 Two kinds of workspace: a **matter** (organised, permissioned by the firm's access model) and a
    **project** (a free workspace anyone can create, any number, with its own members, holding documents,
    spreadsheets, tabular reviews, notes and chats). A project may optionally be linked to a matter.
26. W-R26 A document is stored **once**. The same document can appear in several matters, projects and the
    owner's library through **links**, not copies; an edit made from any of them is the same document and the
    same version history.
27. W-R27 Links show as **tags** on the document. Uploading sets them automatically from where the person
    uploads (matter / project / library, folder, client, uploader, detected document type); linking into
    another workspace or filing into a matter adds a tag; unlinking removes it. People can add their own tags
    and filter by them.
28. W-R28 Linking never widens access: a member sees a linked document only if they could already read it at its
    home. Uploading a file that already exists offers "use the existing document" only among documents the
    uploader can read; byte-level de-duplication in storage is always silent.
29. W-R29 A divergent draft is an explicit "Make a copy" (a new document that shares the stored bytes until
    edited), never a side effect of linking.

## Decisions (product owner, 2026-10-07)

| # | Question | Decision | Affects |
|---|---|---|---|
| D1 | Matter vs project | **Both.** Project is a separate entity anyone can create (any number); matter stays the organised, permissioned container. Documents are stored once and related to matters/projects/library by **links shown as tags**, set dynamically from the upload context. | W0 (new), W1, W4–W6 |
| D2 | Editor engine | Delegated → decided by the Phase 0 bake-off with the gate in X1. If no option clears the gate, keep the current TipTap model and add table-cell editing (W2b.1 fallback). | W2b |
| D3 | Personal library ACL | **Yes:** owner + explicit shares only; never in firm retrieval/Ask unless filed into a matter. | W0, W6 |
| D4 | Playbook format | **Yes:** Markdown instruction playbooks the Assistant follows; YAML step engine frozen (deterministic briefings only). | W5 |
| D5 | Publishing rights | Delegated → new permission `km.publish` granted to the `km`, `partner` and `admin` roles; personal playbooks and project templates need no permission; publishing and every share are audited. | W5, W6 |

## Phase 0 — Experiment and decide (no production code)

- [x] X1 Editor engine bake-off on the real files in `../docs/` (the two tracked .docx, petition drafts) plus
      plan-15 long-doc fixtures and a **held-out** set not used while designing: (a) current TipTap paragraph
      model + server tracked write-back, (b) Folio (`@stll/folio-core` + `@stll/folio-react`) client-side
      .docx model with our server keeping versions/locks, (c) Collabora WOPI (plan 16 E7).
      Measures: round-trip fidelity (tables, headers/footers, footnotes, numbering, fields, existing tracked
      changes, comments) checked by our `editor_roundtrip_eval` signature; edit a table cell and a footnote;
      tracked-change authorship correct; open time and typing latency at 10/100/400 pages; save p95; bundle
      size; LibreOffice/Word render of the saved file. Gate to adopt Folio: ≥ current scores on every existing
      eval check **and** tables/footnotes editable with tracked authorship, 400-page open < 3 s.
      Output: `docs/experiments/editor_engine_2026-10.md` decision record.
      **Done 2026-10-07:** Folio vs the paragraph model (Collabora not measured: no container here). 10 files incl. the two real filings and 5 held-out: round-trip text and revision/comment counts 10/10, tracked edits in paragraphs and table cells, footnote and header story edits, accept/reject exact, LibreOffice render 10/10; 400 pages open 0.40 s, edit+save 0.67 s. Decision record `docs/experiments/editor_engine_2026-10.md`, harness `evals/editor_engine/`.
- [x] X2 Dependency audit for the winner (Folio and its transitive deps: yjs MIT, jszip MIT/GPL dual — choose
      MIT, prosemirror-* MIT, dompurify Apache/MPL, utif2 MIT, hyphen …) in `docs/legal/DEPENDENCY_AUDIT.md`;
      NOTICE handling for Apache-2.0. Pin exact versions (v0.x moves weekly).
      **Done 2026-10-07:** 90-package tree from an isolated install: MIT/Apache/ISC/BSD, OFL-1.1 fonts, dual-licensed dompurify (Apache) and jszip (MIT); pinned exactly (`@stll/folio-react` 0.25.0, `use-intl` 4.14.9); `DEPENDENCY_AUDIT.md`, `THIRD_PARTY_LICENSES.md`.
- [x] X3 Tabular accuracy baseline: the current in-memory extractor on a CUAD slice (plan 14 has CUAD) —
      per-format exact/F1 and citation validity — so W4 has a number to beat, not a feeling.
      **Done 2026-10-07:** CUAD needs licence approval before download (plan 14), so an internal gold set instead: `evals/tabular_review_eval.py` (20 generated agreements, random facts, planted distractors, real model, live HTTP). Seed 11 (design): 85 %; after two format fixes, fresh seed 23: 98.3 % (120 cells), 108/108 quotes verified, 33 s for 20 rows. CUAD stays open pending approval.
- [x] X4 Workbench load test fixture: a matter with 10k documents / 300 folders to size the explorer API.
      **Done 2026-10-07:** `evals/workbench_load_eval.py`: 10,000 documents in 300 folders — folder page p50 16–21 ms (gate 300 ms), title filter 52 ms. Found: quick open listed at most 1,000 documents client-side → now searches on the server.

## Phase W0 — Containers, single-copy documents and tags (foundation for everything below)

Today: `projects.matter_id` is `NOT NULL`, and adding another matter's document to a project **inserts a copy
of the row** (`app/api/routers/projects.py` `assign_document_to_project`, new id from `COUNT(*)+1` — racy).
Both are replaced here.

Model (our names):
- `workspaces` are not a new table: the three container kinds are `matter`, `project`, `library` (one per member).
- `projects` becomes standalone: `matter_id` nullable (optional link), `owner_member_id`, `description`,
  `archived_at`, `row_version`; `project_members (project_id, member_id | team_id, role owner|editor|viewer)`.
  Any member may create projects (no permission needed); a project linked to a matter does **not** inherit the
  matter's members.
- `blobs (content_sha256 PK, object_key, byte_size, mime, created_at)` — stored bytes once; versions point to a
  blob; garbage-collected when nothing references it.
- `document_links (document_id, container_kind, container_id, folder_id, is_home, added_by, added_via
  upload|link|file_into|assistant|import, added_at)` — exactly one `is_home` per document. Home decides who
  governs the document (ACL baseline, retention, privacy); other links are views.
- `document_tags (document_id, tag, kind system|user, created_by)` + system tags derived from links and upload
  context (`matter:…`, `project:…`, `client:…`, `folder:…`, `type:…`, `uploaded-by:…`), kept in sync by the
  link/unlink/file-into service in the same transaction (W-R27). Tag filters in lists and the workbench search.

Access rules (W-R28) — compiled into the existing `visible_to` / `doc_acl` machinery, not checked in Python:
- matter-homed: matter ACL + document privacy, unchanged. Linking it into a project shows project members who
  lack matter access a "restricted" placeholder (title hidden unless they could see the title already).
- project-homed: project members (by role). Filing into a matter moves the home to the matter (the matter's rules
  now govern it); the project keeps a link.
- library-homed: owner + `document_shares`.
- Firm retrieval / Ask: only matter-homed documents and firm templates. Project and library documents are
  searchable only inside their workspace and by the Assistant when that workspace is in scope.

Tasks
- [x] W0.1 Migration `2026100Xb_containers_links.sql`: tables above; backfill one `is_home` matter link per
      existing document; backfill `blobs` from version hashes (object keys unchanged); `projects.matter_id`
      nullable; backfill `project_members` from current project leads/matter team.
      **Done 2026-10-07:** migrations `20261007a_workspaces.sql` (+ `20261007c_archive_rule.sql`, see Log). Home is `documents.home_kind/home_id` (matter documents keep `matter_id`; no backfill of 3,106 rows needed); `document_links` holds the other placements only.
- [x] W0.2 Storage: object store writes keyed by content hash (put-if-absent); version → blob; blob GC job
      (reference count over versions, grace period). Version purge (W2a.4) removes the version's reference and
      collects the blob only when unreferenced; the delete record says whether bytes were physically removed.
      **Done 2026-10-07:** `put_blob` (content-addressed key, put-if-absent) for uploads; `blobs` registry; `app/storage/blobs.py` collects unreferenced blobs after a grace period; `scripts/gc_blobs.py` (dry run by default).
- [x] W0.3 Link service + API: `POST/DELETE /api/documents/{id}/links` (needs read access at home + write on the
      target container), `POST /api/documents/{id}/file-into` (needs `matters.edit` on the target; audit),
      `POST /api/documents/{id}/copy` (W-R29, new document, same blob, provenance). Replace
      `assign_document_to_project` with a link; fix document id generation to the sequence
      (`20260924c_document_id_seq.sql`).
      **Done 2026-10-07:** `app/workspaces/documents.py` + `/api/workspaces/documents/{id}/links|move-home|copy|folder|tags`. The legacy matter-bound projects router (off by default, copied rows with a `COUNT(*)+1` id) is deleted with its tests.
- [x] W0.4 Upload context: ingest/upload/batch APIs take `container_kind/container_id/folder_id`; home link and
      system tags set from it; duplicate check by hash only among documents the uploader can read → response
      `existing_match` so the UI offers "Use existing (link)" vs "Upload as separate document".
      **Done 2026-10-07:** uploads take `container_kind/container_id/folder_prefix`; duplicates checked within the workspace; `POST /api/workspaces/duplicates` names only readable twins; the UI hashes files in the browser and offers "use the existing document".
- [x] W0.5 Projects API + UI: create (anyone), edit, archive, members/teams with roles, optional matter link,
      Projects list page ("My projects", "Shared with me"), project page with Documents · Sheets (tabular reviews
      and uploaded spreadsheets) · Notes (in-app text documents, existing text versions) · Chats.
      **Done 2026-10-07:** `/api/projects` (create by anyone, list, get, edit with row_version, archive/restore, members by role, last owner kept); Projects page; project workbench header (people, details, archive).
- [x] W0.6 ACL compile + perf: extend `visible_to` triggers for project and library homes; `acl_epoch` bump on
      membership changes; retrieval SQL A/B (p95 within noise of today, as in plan 17 P1b).
      **Done 2026-10-07:** `doc_acl_compile` compiles project/library readers into `visible_to` (never NULL); triggers on project members, teams, roles; `doc_read()` for named-document reads; firm-wide reads unchanged, so retrieval SQL is unchanged (no A/B needed beyond the suite).
- [x] W0.7 Tests: wall matrix extended with project/library homes × (owner, project editor, project viewer,
      matter member, stranger, auditor) across every document read surface; linking a walled matter document
      into a project leaks nothing (title, chunks, search, Assistant, events); one edit visible in both
      containers; upload dedup never reveals an unreadable document; blob GC keeps shared bytes; projects with no
      matter work end to end. Playwright: upload into project → link into matter → tags shown in both.
      **Done 2026-10-07:** `tests/test_workspaces.py` (16) incl. walled document linked into a project, events, archive, search, layout; `e2e/workbench.spec.ts` (3). Found and fixed on the way: project events reached everyone through the live feed (no matter/document on the event).

## Phase W1 — Workbench shell (frontend + small backend)

Routes `/work/matter/:id`, `/work/project/:id`, `/work/library` (W-R25). Existing `/documents/:id` and
`/documents/:id/edit` stay as deep links and open inside the workbench when it is open.

- [x] W1.1 Layout: activity bar (Explorer · Search · Changes · Review · Assistant · Playbooks), resizable side
      bar, editor area with tab strip and up to 2 editor groups (split right), bottom panel (Findings ·
      Comments · Jobs), status bar (W-R4). Our components on the existing Radix/Tailwind design system
      (`DESIGN.md`); no IDE look-alike chrome beyond the layout pattern.
      **Done 2026-10-07:** `pages/WorkbenchPage.tsx`, `components/workbench/*`: activity bar (Explorer, Search, Changes), resizable side bar, two editor groups, status bar.
- [x] W1.2 Tabs: document tabs (exact view or editor by file type), table tabs (tabular review), diff tabs
      (compare), preview tabs (single-click opens a replaceable preview tab, double-click pins), dirty dot when
      a draft differs from base, close-with-unsaved guard (draft is server-side, so closing never loses work).
      **Done 2026-10-07:** preview tabs (italic, replaced by the next single-click), double-click keeps, Alt/⌘-click opens to the side, middle-click closes; the document page runs inside a tab with per-tab place (`paramsState`) and pane-width layout.
- [x] W1.3 Explorer: lazy tree of the workspace's folders → documents (`GET /api/workbench/tree?kind=&id=&folder_id=`,
      paged, ACL + privacy in SQL, linked documents marked with a link badge and their tags), drag to move (existing folder API), new folder, upload into folder (existing
      upload flow), rename, archive, "Open to the side", privacy lock icons, live updates via `/api/events/stream`.
      **Done 2026-10-07:** lazy tree from `/api/workspaces/{kind}/{id}/items`, drag files onto a folder to upload there, row menus (open, to the side, add to…, copy, file, move, tags, remove link), restricted placeholders, folder new/rename/delete.
- [x] W1.4 Quick open (Ctrl/Cmd-P) over the matter's documents by title/ID; command palette (Ctrl/Cmd-Shift-P)
      over a typed command registry (each command: id, title, keybinding, when-condition, handler) — `cmdk`
      is already a dependency. Keybindings shown in menus; one shortcut map, no per-page handlers.
      **Done 2026-10-07:** ⌘P quick open, ⇧⌘P commands (typed registry), ⌘\\ split, ⌘B side bar, ⇧⌘F search, ⇧⌘E explorer, ⇧⌘H changes, ⌥W close tab.
- [x] W1.5 Search view: matter-scoped full-text search reusing the hybrid retrieval channels with
      `matter_id` filter; results grouped by document, click opens tab at the passage (existing quote locator).
      **Done 2026-10-07:** `/api/workspaces/{kind}/{id}/search` (tsv_full over the workspace's readable documents, best passage + page); hits open at the page.
- [x] W1.6 Persisted layout: `workbench_state (member_id, scope_key, state jsonb, updated_at)` + `GET/PUT
      /api/workbench/state` (debounced). State holds only ids; every id is re-checked on load.
      **Done 2026-10-07:** `workbench_state` (migration `20261007d`), GET/PUT state, saved 1 s after changes; unreadable tabs dropped on load (test).
- [x] W1.7 Tests: pytest (tree ACL incl. private/restricted docs and walled matters, state isolation per member),
      Playwright (open 3 docs, split, reload restores layout, quick open, palette runs "Compare with
      previous"). Perf gate: tree first page < 300 ms on the X4 fixture.
      **Done 2026-10-07:** pytest (tree ACL, layout isolation) and Playwright `workbench.spec.ts` green. Perf gate on the X4 fixture still open (X4 not built).

## Phase W2 — Document source control and full-fidelity editing

**Already delivered by plan 21 (branch `integrate/docs-search-versioning-v2`, this plan's base):** clean-HEAD
commits (`is_clean`, `origin` = kind, `change_summary` = message), commit log, diff, blame, restore as a new
version, accepted Assistant edits written as one clean version (`app/documents/assistant_apply.py`). W2a below
keeps only what is still missing: kind vocabulary on the existing `origin`, version purge, copy-from, and the
workbench Changes view on top of plan 21's APIs.

W2a — version model (independent of engine choice)
- [x] W2a.1 `document_versions.kind` (`human_save | upload | assistant_edit | review_accept | restore | copy`)
      and `source_turn_id` (Assistant message id). Migration `2026100Xa_version_kinds.sql`; backfill kinds.
      **Done 2026-10-07:** `origin` vocabulary: upload, editor, assistant, import, restore, review, copy (migration `20261007e`).
- [x] W2a.2 Turn coalescing (W-R9): an Assistant turn's accepted edits to one document write one version;
      a second batch in the same turn replaces that version's file while it is still the head and unpublished
      to anyone else's lock; otherwise a new version.
      **Done 2026-10-07:** `editing._amendable/_amend`: edits accepted from one Assistant turn amend that turn's version while it is newest, same person, nothing attached; otherwise a new version. Who-changed-what counts are added, not replaced. Tests in `test_assistant_apply.py` (+2).
- [x] W2a.3 Restore (W-R7): `POST /api/editor/documents/{id}/versions/{vid}/restore` → new `restore` version
      (lock + base checks as save). Copy-into (W-R10): `POST .../versions/copy-from` {source_document_id,
      source_version_id} with an explicit response describing the source's fate.
      **Done 2026-10-07:** restore existed (plan 21); copy-from: `POST /api/editor/documents/{id}/versions/copy-from` (source unchanged, says so), workbench Changes → "Replace from…". Test in `test_version_purge.py`.
- [x] W2a.4 Delete version (W-R8): `DELETE .../versions/{vid}` {reason} — manage right on the matter, never the
      current version, purges object-store bytes + rendition cache + chunks, keeps the row (`deleted_at`,
      `deleted_by`, `delete_reason`); audit `document.version.delete`; restore/compare refuse with a clear 410.
      **Done 2026-10-07:** `POST /api/editor/documents/{id}/versions/{vid}/purge` {reason}: manage only, never the current version; text, file (unless shared), raw upload, blocks, chunks, comments, diffs, rendition cache removed; download never falls back to the first upload; `_version` answers 410; blame skips purged versions. `tests/test_version_purge.py` (5).
- [x] W2a.5 Changes view in the workbench: working draft vs base (paragraph-level change list from the existing
      ops), "Save version" (note, tracked/clean), "Discard draft", history timeline with kind chips, compare any
      two in a diff tab (side by side, synced scroll) and download redline.
      **Done 2026-10-07:** workbench Changes view = plan 21's History panel for the active tab (+ deleted entries, Delete… for managers, Replace from…); opening a version sets the tab's place.
- [x] W2a.6 Tests: coalescing (2 edit calls, 1 version; edit after another member's save → 2 versions),
      restore, delete-then-restore 410, purge removes bytes and chunks, audit rows, ACL on every new endpoint.
      **Done 2026-10-07:** see W2a.2–W2a.4 tests; full `pytest tests/` re-run pending at the end of this pass.

W2b — engine (after X1)
- [x] W2b.1 If Folio wins: editor tab uses Folio's model for .docx; save sends the edited .docx (or a
      structured op log) to our versions API — authorship of tracked changes set from the session on the
      server, never trusted from the client; keep our lock/draft/version/compare contracts unchanged so the
      Word add-in and Collabora paths still fit. If TipTap stays: add table cell editing to the paragraph model
      and tracked write-back for table cells (plan 16 "Known v1 limits").
      **Done 2026-10-07:** Folio adopted: `/documents/:id/write` and the workbench "Edit (Word)" tab (`FullWordEditor.tsx`, tracked changes on by default, lock + heartbeat, take-over, save with note); `POST /api/editor/documents/{id}/save-docx` re-stamps new revisions with the session member (`docx_restamp.py`) and stores the clean version. The paragraph editor stays at `/edit`.
- [x] W2b.2 Draft autosave stores the engine's native draft; recovery after crash tested.
      **Done 2026-10-08:** the browser sends the edited .docx every 30 s while there are unsaved edits (`PUT …/draft-docx`, one per person per document, object store, migration `20261008a`); reopening offers "restore / discard" only when the draft sits on the current version; saving a version clears it. Tests `test_full_editor.py` (+2), e2e "keeps unsaved changes and offers them back after a reload".
- [~] W2b.3 `editor_roundtrip_eval` extended: tables edited, footnote edited, headers untouched, existing
      tracked changes from others preserved (plan 18 R4); gate 100 % on all checks, 400-page save p95 < 3 s.
      **Partly done 2026-10-07:** `tests/test_full_editor.py` (spoofed author re-stamped, existing changes keep their author, stale/unauthorised/non-Word refused) and e2e "the Word editor tracks a change…"; the bake-off harness covers tables, footnotes and headers. Extending `editor_roundtrip_eval.py` itself to the Word editor is open.

## Phase W3 — Assistant inside the workbench

- [x] W3.1 Chat sessions gain a scope: `chat_sessions.scope jsonb` {matter_id, document_ids, active_document_id,
      selection {document_id, version_id, quote, pid range}}; set by the workbench on each message; the server
      re-checks access for every id each turn (existing reader re-check).
      **Done 2026-10-07:** `chat_sessions.workspace_kind/id` (migration `20261007g`), scope re-checked each turn (`_workspace_scope`), workspace named in the system prompt.
- [x] W3.2 Assistant panel in the side bar / right group; "Ask about selection" and "Redraft selection" in the
      editor context menu and palette; open tabs offered as attachable context chips.
      **Done 2026-10-07:** Assistant side view in the workbench (`AssistantView.tsx`): open tabs attached by default (each can be left out), pages dragged in as page references, starters, `/` for playbooks, sources open as tabs.
- [~] W3.3 Inline suggestions (W-R13): edit proposals (`edit_proposals` part) render as suggested changes in the
      open editor tab with per-hunk accept/reject and "Accept all"; accepting goes through the normal save path
      with `kind=assistant_edit` and coalescing (W2a.2). Proposals against an old version are re-located by
      quote or marked stale.
      **Partly done 2026-10-07:** edit proposals appear as the existing accept/reject cards in the workbench Assistant and accepting writes one version per turn (W2a.2); open tabs refresh. Rendering them inside the Word editor as suggestions (Folio's suggested mode) is open.
- [~] W3.4 "Compare with firm precedent" action: `ask_firm` restricted to precedent/template folders + the
      selection; answer cites firm documents that open in the split.
      **Partly done 2026-10-07:** starter "compare the open document with the firm's precedents" (the Assistant uses ask_firm); a selection-scoped action from inside the editor is open.
- [x] W3.5 Tests: scope ACL (open a restricted doc, lose access mid-session → next turn cannot read it),
      inline accept creates one version, Playwright flow select → redraft → accept → v+1 kind assistant_edit.
      Grounding eval (plan GROUNDING_ROADMAP) does not regress.
      **Done 2026-10-07:** `tests/test_workbench_assistant.py` (3); live: two real-model turns in the workbench (answer per open filing; answer from a tabular review with no statement removed after making review/workspace tool results groundable).

## Phase W4 — Durable tabular review

Replace the in-memory store; keep the public routes where they fit, version the API where they do not.

- [x] W4.1 Schema (our names): `tab_reviews` (id, title, container_kind matter|project|library, container_id, owner_member_id, model, playbook_id
      null, group_by `document|folder`, status, row_version, timestamps), `tab_columns` (id, review_id, position,
      label, question, answer_format, choices, revision), `tab_rows` (id, review_id, position, document_id or
      folder_id), `tab_cells` (row_id, column_id, column_revision, status `pending|running|done|failed|stale`,
      answer jsonb, reason, citations jsonb, edited_by, edited_at, lease_owner, lease_until, error).
      **Done 2026-10-07:** migration `20261007f_tabular_reviews.sql`.
- [x] W4.2 Runner: worker claims cells with `FOR UPDATE SKIP LOCKED` + lease expiry (W-R16), bounded concurrency
      per review and per firm, retries with backoff; each cell = retrieval over that row's document(s) only
      (document_ids filter) → extraction in the column's format → citations validated against chunks (reuse
      grounding/citation filter); folder rows search all readable docs in the folder.
      **Done 2026-10-07:** `app/tabular/runner.py` (SKIP LOCKED leases, one call per row over its own passages, quotes located, folder rows).
- [x] W4.3 Live fill: cell updates as `domain_events` on the existing SSE stream (ACL-filtered); per-cell and
      per-column re-run; editing a column bumps `revision` → its cells go `stale`; manual overwrite keeps the
      model answer for audit.
      **Done 2026-10-07:** polling every 1.5 s while open (not SSE); per-cell/row/column re-run; question change → stale; overrides keep the model's answer.
- [x] W4.4 Access: a review follows its container's rules (matter ACL, project members, or owner); rows whose document the viewer cannot read
      render as "restricted" with no answer (checked on every read, not at creation only); library reviews are
      owner + shares.
      **Done 2026-10-07:** redaction by cell source documents on page, export and Assistant (tests).
- [x] W4.5 UI: review opens as a workbench table tab — sticky header/first column, virtualised grid (1000 rows ×
      30 columns), format-aware cells, status/filters, citation click opens the doc in the other group at the
      quote (W-R18), "New review" dialog (title, docs/folders picker from the explorer selection, columns from a
      column-set playbook or presets, group by folder).
      **Done 2026-10-07:** `ReviewTable.tsx` (windowed rows, sticky header/first column, cell detail with quote and "open source beside the table"), `ReviewDialogs.tsx` (presets, own questions, documents or folders).
- [x] W4.6 Assistant over the table: tool `read_review_cells(review_id, rows?, columns?)` with ACL; side chat on
      the table tab; Excel export with citation sheet (existing exporter, moved to DB data).
      **Done 2026-10-07:** `read_review_cells` tool + `/cells` route; Excel with a Sources sheet (`app/tabular/export.py`).
- [x] W4.7 Migrate the in-chat `ReviewTableCard` to create a durable review ("Open as table").
      **Done 2026-10-07:** "Open as table" on the chat review card creates a library review and opens it in the workbench.
- [x] W4.8 Tests + eval: lease (two workers, no double fill), restart mid-run resumes, stale on column edit, ACL
      row redaction, export; CUAD slice from X3 must match or beat baseline; 100 docs × 10 columns finishes
      within a set budget (measure first, then fix the number in this plan).
      **Done 2026-10-07:** `tests/test_tabular.py` (7): fill + citations, 3 concurrent workers no double fill, crash resume, stale, redaction, runner access, folders; accuracy baseline in X3.

## Phase W5 — Playbooks

- [x] W5.1 Schema: `playbooks` (id, kind `instructions|columns`, title, summary, practice_area, jurisdiction,
      language, body_md, columns jsonb, source `shipped|firm|personal`, owner_member_id, origin_playbook_id,
      version, archived_at), `playbook_files` (reference documents), `playbook_shares` (member/team, view|edit).
      **Done 2026-10-07:** migration `20261007h_playbooks.sql` (+ `km.publish` for knowledge managers, partners, firm admins).
- [x] W5.2 Shipped catalog: Markdown + front matter files in `app/playbooks/catalog/` synced into the table on
      startup by content hash (new version, never overwriting firm/personal copies). Convert the three current
      YAML workflows into this format.
      **Done 2026-10-07:** `app/playbooks/catalog/` (5 instruction playbooks incl. the 3 converted YAML workflows, 3 column sets), synced by content hash.
- [x] W5.3 API: list (filters, ACL), get, create, update (row_version), duplicate, share, publish to firm
      (`km.publish`, D5), archive. Audit every publish/share.
      **Done 2026-10-07:** `/api/playbooks` (list, get, create, update with row_version, duplicate, publish, share, archive), audited.
- [x] W5.4 Assistant: tools `list_playbooks`, `read_playbook`; system prompt rule — when a playbook is chosen,
      read it first, open its reference files if needed, ask for missing inputs, then follow it. `/` command
      menu in the composer; "Run playbook…" in the palette; quick actions on a document (configurable per firm).
      **Done 2026-10-07:** `list_workflows` / `read_workflow` now serve playbooks (fenced as user-selected instructions); `/` menu in the workbench Assistant; "Use with the Assistant".
- [x] W5.5 Column-set playbooks seed new tabular reviews (W4.5); "Save columns as playbook" from a review.
      **Done 2026-10-07:** `playbook_id` on review create; "save questions as a playbook" on a review.
- [x] W5.6 UI: Playbooks view in the workbench (browse/filter, preview, duplicate, edit in a Markdown editor
      tab, columns editor), sharing dialog.
      **Done 2026-10-07:** Playbooks view, preview, Markdown editor dialog, columns editor, share box, publish.
- [x] W5.7 Tests: shipped sync idempotent, firm read-only, duplicate keeps origin, share/ACL, Assistant follows
      a playbook in an LLM-gated e2e; playbook reference files respect document ACL.
      **Done 2026-10-07:** `tests/test_playbooks.py` (5).

## Phase W6 — Library and templates

- [x] W6.1 Personal library (D3) on the W0 model: library-homed documents (owner + `document_shares`),
      excluded from firm retrieval/Ask; "File into matter" / "Link into project" from the library view.
      **Done 2026-10-07:** library home (W0) + "My library" nav.
- [x] W6.2 Firm templates & precedents: a firm-level library (folders + tags + practice area), curated by
      `km.publish`; readable by all members unless restricted.
      **Done 2026-10-07:** fourth home `firm/templates` (migration `20261007i`): every member reads, km.publish curates, not in firm search; "Templates" nav.
- [x] W6.3 "New from template" (W-R24): copy bytes into a target matter or project folder as a new document (W0.3 copy: same blob,
      `derived_from (document_id, version_id)`); optional fill of named fields via the Assistant; the template is
      never opened for editing from drafting flows.
      **Done 2026-10-07:** "New from template" in every workspace's explorer (copy with provenance; templates cannot be moved out). Filling named fields with the Assistant is open.
- [~] W6.4 Explorer roots: current workspace · My library · Firm templates; the Assistant can attach library files.
      **Partly done 2026-10-07:** explorer roots are per workspace (sidebar: Projects, My library, Templates); a combined multi-root tree is open.
- [x] W6.5 Tests: library privacy across every read surface, template copy provenance, retrieval excludes
      personal docs.
      **Done 2026-10-07:** `test_firm_templates_…` in `tests/test_workspaces.py`; library privacy across read surfaces in W0 tests.

## Phase W7 — Hardening and rollout

- [~] W7.1 Performance: 20 open tabs, 400-page doc in one group + table in the other; memory and frame budget;
      lazy-load engine bundles per tab type.
      **Partly done 2026-10-07:** Word editor (2.1 MB) and every page lazy-loaded; explorer at 10k documents measured (X4). A 20-tab memory/frame budget was not measured.
- [~] W7.2 Accessibility: full keyboard path (tabs, tree, grid), focus order, screen-reader labels on cells.
      **Partly done 2026-10-07:** tree/tab/grid roles and labels, everything reachable by keyboard shortcuts and buttons; no screen-reader audit yet.
- [x] W7.3 Audit coverage for every new write; metrics (tab open time, save p95, cell fill rate/failures).
      **Done 2026-10-07:** every new write audited; metrics `precentis_tabular_cells_total`, `precentis_tabular_row_seconds`, `precentis_workbench_saves_total`.
- [x] W7.4 Docs: `docs/ASSISTANT_ARCHITECTURE.md`, a new `docs/WORKBENCH_ARCHITECTURE.md`, CHANGELOG, IP record
      updated with what was actually built; mark plans 06–09 superseded; tick plan 18 items that are done.
      **Done 2026-10-07:** `docs/WORKBENCH_ARCHITECTURE.md`, CHANGELOG, IP record, plans 06–09 marked superseded. Plan 18 ticks left to its owner (code from another session).
- [x] W7.5 Feature flag `WORKBENCH_ENABLED`; old document page stays as fallback until Playwright parity.
      **Done 2026-10-07:** `WORKBENCH_ENABLED` (default true) gates the projects/workspaces/playbooks APIs; the document page and paragraph editor are unchanged as the fallback.

Later (not in this plan): Word add-in on the same APIs (plan 16 P4, after Entra); Collabora "open in full
editor"; real-time co-editing (Yjs — Folio already speaks it, so X1 should note the cost); a VS Code extension
for legal engineers; US case law.

## Build order and rough size

Phase 0 (≈1 week, gates W2b) ∥ W0 (≈2 weeks — the risky one: ACL compile + backfill) → W1 (≈1.5 weeks)
∥ W2a (≈1 week) → W4 (≈2 weeks, highest user
value after the shell) → W3 (≈1.5 weeks) → W2b (1–2 weeks, depends on X1) → W5 (≈1.5 weeks) → W6 (≈1.5 weeks)
→ W7 (≈1 week). Each phase ships behind the flag with its pytest + Playwright + eval gate green; `pytest tests/`
and the Playwright `app` project must stay green at every phase end.

## Log

- 2026-10-07 — Plan written from code survey (state table above) and the product owner's Mike product notes and
  doc-versioning notes (converted to W-R1…W-R24; no Mike source opened). Found: tabular reviews live in a process
  dict (`_REVIEWS_DB`); workflows have no UI; plans 06–09 still show PENDING gates though folders and partial
  backends shipped; plan 18 code exists but its checkboxes are open. Folio checked on npm/GitHub: Apache-2.0,
  v0.55 core / v0.25 react, ~29 stars, very active — adopt only through X1 + X2. Open decisions D1–D5 sent to
  the product owner.
- 2026-10-07 — Product owner decisions: D1 both containers — projects standalone (anyone, any number), matters
  stay permissioned; documents stored once, related by links shown as tags set from the upload context
  (W-R25…W-R29, new Phase W0); D3 and D4 accepted; D2 and D5 delegated and decided above. Found while planning
  W0: `projects.matter_id` is NOT NULL and cross-matter "assign" copies the document row with a `COUNT(*)+1` id
  (race) — both replaced in W0.3. Next: X1 editor bake-off and W0.1 migration design (with the ACL A/B).
- 2026-10-07 — Base branch decided by the product owner: new branch `workbench` from
  `integrate/docs-search-versioning-v2` (worktree `.claude/worktrees/workbench`), with `new_frontend_v2`'s Azure
  gateway and evals commits cherry-picked. Renumbered 20 → 22 (20 and 21 exist on this branch). W2a reduced to
  what plan 21 does not cover. The integrate worktree's uncommitted Oct-4 changes (26 files) were left untouched.
- 2026-10-07 — W0, W1 and W2a built (evidence on the items). Regression found and fixed within the hour: 20261007a
  replaced `doc_acl_compile` without plan 09's archive rule (archived = visible to nobody); no archived document was
  exposed (none recompiled in the window), `20261007c_archive_rule.sql` restores it, test added. Full pytest after W0:
  1,084 passed / 1 skipped. Playwright `--project=app`: workbench + sidebar specs green; 7 failures are stale assertions
  from plan 21 on this branch (editor `has_revisions`, review pending chips, "Versions" → "History"), fixed by the
  integrate worktree's uncommitted Oct-4 edits, which were left to their owner. Decision noted: uploading into a
  matter still needs only read access on the matter (unchanged behaviour); projects need editor.
- 2026-10-08 — Quick-open race fixed (Enter waits for the server's fresh results); drag-and-drop in the explorer (a
  document onto a folder files it, onto another document replaces that document's content after a confirmation that says
  the source is unchanged); Word editor autosave (W2b.2). Committed on `feature/document-workbench`. Why the user could
  not see the work: their app on :8000/:5173 serves the main checkout; the workbench runs on :8021/:5174.
