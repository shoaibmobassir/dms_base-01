# Documents as commits: clean current version, commit log, restore, blame (2026-10-04)

Plan: `docs/plan/21_documents_search_versioning.md`, C2. Reported: after changing "INR 1,20,00,000" to "1,50,00,000" the
document showed both numbers, the old one struck, and the user wants versioning and changes "like git".

## What was wrong

- Every save wrote the author's changes into the stored `.docx` as Word tracked changes and **kept them there**
  (`save_edits` mode `tracked`, the default). So the current version was never clean, a download carried the whole
  edit trail, and the default "Exact" view drew all of it (`ExactView.tsx:41`, `renderView = "markup"`).
- There was no restore, and `/history` was an audit log of events, not a list of versions.
- Measured on the shared database: 676 versions; 396 with a stored file, of which 380 are Word files and **163 carry
  tracked changes**. 160 of those are two e2e test documents (`DOC-03082`, `DOC-03186`). The real ones are
  `DOC-7405413EC8` (*Employment Agreement - CTO.docx*, the one in the report, 2 versions) and `DOC-BA2F648943`.

## Model

A **commit** is a `document_versions` row whose stored file is the clean document (every change accepted). HEAD is
`documents.current_version_id`. What a version changed is the difference to its parent, computed on demand; a
tracked-changes Word file is generated only by `compare.docx`. History is linear. Raw uploads are kept.

| Piece | How |
|---|---|
| Columns (`20261004a_version_commits.sql`, additive) | `is_clean`, `restored_from_version_id`, `source_storage_uri`. The commit message is the existing `change_summary`; the kind is the existing `origin` (`editor`, `upload`, `import`, `restore`) |
| Save | stored file = `accept_everything(result)`; the tracked form is kept only to record who changed what (`document_revision_authors`), so contributor statistics still work. `mode` is accepted for compatibility and the response says `clean` |
| Safeguard | a file that still carries **someone else's pending changes** (an old row) is saved as before: accepting them as a side effect of an edit would decide for the reviewer. `is_clean` stays false until the backfill |
| Word upload with tracked changes (decided) | two commits: the text before the changes, then the accepted result credited to the people who made them, with the raw file kept as `source_storage_uri`. The first is skipped when it equals the current version (the usual case: someone reviewed the current version in Word and sent it back) |
| Restore | `POST /documents/{id}/restore {version_id, base_version_id, note}`: a new version with the old content, `origin = restore`, `restored_from_version_id`; stale base → 409, current version → 422, other editor's lock → 409, readers → 403. Goes through `_create`, so blocks, chunks and vectors are rebuilt and search follows |
| Log | `GET /documents/{id}/commits`: message, author, kind, size change, `is_current` |
| Diff | `GET /documents/{id}/diff` (alias of `/compare`), now with `words_added` / `words_removed` |
| Blame | `GET /documents/{id}/blame`: for each paragraph, the version and person that last changed it |
| Backfill | `scripts/clean_versions.py` (dry run by default): clean copy stored beside the old file, old file kept; idempotent; **not applied** to the shared database |

## Measured

- **Blame cost** (decided on-demand, no persisted per-change table): 1,172 paragraphs and 200 versions of small edits:
  0.9 s cold, 0.27 s at the default depth of 60, then cached. A real 299-version document is trivial (6 paragraphs).
- Full suite after the change: 988 passed, 5 skipped. The editor round-trip eval gates are unchanged (see C1).
- Dry run of the backfill: 217 versions already clean, 163 to convert (160 in the two e2e documents), 14 PDFs
  skipped, 2 files unreadable on the machine that ran it.

## Defect found while building it

The object store names every version's file `original.<ext>`. The first import stored the raw upload and the clean file
under the same key, so the clean copy was overwritten by the raw one and `storage_uri == source_storage_uri`. The new
test caught it; the raw copy now goes to `uploaded.<ext>` beside the clean file, and the backfill refuses to write a
clean copy over the only copy.

## Tests changed on purpose

Four in `test_document_editor.py` asserted that markup stays in the stored file (tracked save, next edit has
revisions, formatting revisions, compare stats) and now assert the new behaviour: no markup in the file, authorship in
the version row and the redline, and word counts. `test_word_review.py` keeps testing the pending-changes workflow, but
creates its versions the way the old upload did, because new uploads no longer leave changes pending. `test_semantic_diff`
now expects `50,000` to be the change rather than `$50,000.`. New: `tests/test_document_history.py` (15 tests).

## Limits and what changed for users

- For a new upload, **accepting or rejecting one reviewer's changes selectively is gone**: all are accepted into one
  commit credited to them. Per-reviewer commits (one per author) would allow reverting one person's changes and are not
  built. The Review panel still works for the legacy rows until they are cleaned.
- Comments: Word comments in an uploaded file are imported as before (`index_version` on the raw file). Comments are not
  yet carried into restored versions beyond what the file holds.
- Restore copies the file as it stood; if a version's file is missing on the machine it refuses instead of restoring text
  only.
- Blame uses stored text, so it follows the text, not formatting.
- The UI still shows the Exact view with markup by default; C3 changes that.

## To apply to the shared data

```
python scripts/clean_versions.py                       # count (what is above)
python scripts/clean_versions.py --apply --document DOC-7405413EC8     # the CTO agreement from the report
python scripts/clean_versions.py --apply               # everything; back up data/object_store first
```
