# Workbench architecture (plan 22)

The workbench is where a lawyer works on the documents of one **workspace**: a matter, a project, their own library,
or the firm's template library. Plan: `docs/plan/22_document_workbench.md`. Decisions: plan 22 "Decisions";
editor engine: `docs/experiments/editor_engine_2026-10.md`.

## Workspaces and single-copy documents

| Home | Who reads | Who edits | In firm search / Ask |
|---|---|---|---|
| matter (`documents.matter_id`) | matter ACL, narrowed by document privacy | matter edit level | yes |
| project (`home_kind='project'`, `home_id`) | project members (owner / editor / viewer, people or teams) | editors and owners | no |
| library (`home_kind='library'`, `home_id` = member) | the owner, plus explicit shares | the owner | no |
| firm templates (`home_kind='firm'`, `home_id='templates'`) | every member (unless a template is made private) | `km.publish` holders | no |

- A document is stored **once** and has one home, which governs access. `document_links` show it in other workspaces;
  a link never widens access (a reader who cannot read it at its home sees a "restricted" placeholder).
- Readers of project, library and private documents are compiled into `documents.visible_to` / `chunks.visible_to`
  by `doc_acl_compile` (migrations `20261007a`, `…c`, `…i`), with triggers on members, teams, roles and homes.
- Two SQL predicates in `app/api/acl.py`: firm-wide reads keep `ACL_CLAUSE` + `doc_acl` (which leave non-matter homes
  out); reads of named documents use `doc_read()` (home-aware). `app.access.document_access()` is the Python twin.
- Tags: people's own (`document_tags`) plus tags derived when read from the home, the links the reader can see, the
  client and the type — so they follow every move with no sync.
- Stored bytes are content-addressed (`put_blob`, `blobs`), collected when unreferenced (`app/storage/blobs.py`,
  `scripts/gc_blobs.py`). A copy shares the bytes until edited.

Services: `app/workspaces/` (projects, documents, state). Routes: `/api/projects`, `/api/workspaces`.

## Versions

Plan 21's commit model (clean current version, commit log, diff, blame, restore) plus:
- `origin` kinds `upload | editor | assistant | import | restore | review | copy`;
- one Assistant turn makes one version: accepted edits from the same turn amend that turn's version while it is the
  newest, the same person's and nothing is attached (`editing._amendable`);
- purge (`POST …/versions/{id}/purge`): content, file (unless shared), index and comments go; the history keeps the
  entry; every later use answers 410;
- copy-from: another document's content as this document's next version.

## Editing

- Paragraph editor (`/documents/:id/edit`, plan 16): paragraphs, styles, B/I/U as Word tracked changes.
- Word editor (`/documents/:id/write`, workbench "Edit (Word)" tab): Folio (`@stll/folio-react`, Apache-2.0) edits the
  whole package — tables, headers/footers, footnotes, other people's changes. `POST …/save-docx` re-stamps every new
  revision with the session member and the server clock (`app/documents/docx_restamp.py`), stores the clean version,
  records who changed what. Same lock / draft-free / version contracts as the paragraph editor.

## Tabular reviews

`tab_reviews / tab_columns / tab_rows / tab_cells` (migration `20261007f`). Rows are documents or folders; columns have
an answer format. `app/tabular/runner.py`: workers claim a row with a lease (`FOR UPDATE SKIP LOCKED`), answer all its
open columns in one model call over the row's own best passages (`app/review/batch.py` screen → map, quotes located in
the passages), write cells with citations and the documents they drew on, release the row. A run is done as its
starter; a viewer who cannot read a cell's source documents sees it as restricted (page, export and Assistant alike).
Interrupted runs resume when the review is next opened. Baseline accuracy: `evals/tabular_review_eval.py`.

## Playbooks

`playbooks / playbook_shares / playbook_files` (migration `20261007h`). Instruction playbooks are read by the Assistant
(`list_workflows` / `read_workflow`, fenced as `<workflow-instructions>`); column sets start reviews. Shipped ones are
`app/playbooks/catalog/*.md`, synced by content hash.

## Assistant in the workbench

Chat sessions may belong to a workspace (`chat_sessions.workspace_kind/id`). Its tools gain `search_workspace` (the
workspace's own documents, which firm search does not cover) and `read_review_cells`; both results ground answers.
Open tabs go with each question as attachments; pages can be dragged in.

## Frontend

`pages/WorkbenchPage.tsx` and `components/workbench/*`: activity bar (Explorer, Search, Assistant, Reviews, Playbooks,
Changes), side bar, two editor groups of tabs (document / Word editor / review), status bar, ⌘P quick open (server
search), ⇧⌘P commands. Layout saved per person per workspace (`workbench_state`). Document pages run inside tabs with
their place kept per tab and laid out by pane width.

## Operations

`WORKBENCH_ENABLED` (default true), `TABULAR_WORKERS` (default 4). Metrics: `precentis_tabular_cells_total{status}`,
`precentis_tabular_row_seconds`, `precentis_workbench_saves_total{path}`, `precentis_workbench_save_seconds{path}` (Word editor).
Evals: `evals/editor_engine/`, `evals/tabular_review_eval.py`, `evals/workbench_load_eval.py`,
`evals/word_editor_roundtrip_eval.py` (+ `word_editor_driver.cjs`), `evals/workbench_perf_audit.cjs` (20 tabs),
`evals/a11y_audit.cjs` (axe, external tool; see `docs/legal/DEPENDENCY_AUDIT.md`).

Save cost: a version save replaces the document's chunk and block rows in one pipelined batch and reuses vectors of
unchanged chunks through two analysed temp tables, so its time no longer depends on the planner's statistics for
`chunks` (which a save leaves stale).
