# Plan 21 — document search, PDF edit false-positives, git-like versioning

Started 2026-10-04. Status keys: `[ ]` open · `[~]` in progress · `[x]` done (with date + evidence)

Approved plan: three user-reported problems, each traced to a root cause.

1. The assistant "corrected" `knowledgeand → knowledge and` on a PDF whose printed page is fine. The PDF's
   pages 14–16 are scanned images with an embedded OCR text layer; the layer itself has no space glyph there
   (`pdfplumber` extracts the same string as `pypdf`), so a different extractor does not fix it.
2. Search found nothing for words inside a document: `/api/search` matched titles and types only, truncated the
   list after matters, and the palette's empty message never rendered (see B1).
3. An edit appeared as `~~1,20,00,000~~1,50,00,000`: space-only tokenizing glues del+ins, the default view
   renders stored tracked changes, there is no clean HEAD and no restore.

Decisions: Word files with tracked changes import as two commits (original, then accepted result credited to
the authors); PDFs get recommendations only; branches deferred; raw uploads are kept for every version. No
PyMuPDF (AGPL).

## B1 — search finds document text
- [x] 2026-10-04 `/api/search` documents: title/type match **or** words in the document via `chunks.tsv_full`
      (GIN-indexed, `websearch_to_tsquery`), title hits first, then `ts_rank_cd`; returns `match_kind` and a
      highlighted `snippet`; ACL and document privacy unchanged
- [x] 2026-10-04 per-kind quotas (5 matters / 8 documents / 3 clients / 4 people, scaled to the limit, unused
      slots go to the others) replace `results[:limit]`
- [x] 2026-10-04 palette: snippet under the title, "Type at least 2 characters", "Searching…", an error state with
      Try again, and an honest empty message. Found root cause on the way: cmdk's `CommandEmpty` never renders
      while the "Ask the Firm" row is listed, so the old "No results" message was never visible
- [x] 2026-10-04 `tests/test_search_api.py` (9 tests: quotas, content hit, ranking, restricted-document wall by
      title and by content, odd input, blank query) and `evals/search_palette_check.cjs` (browser)
- Measured on the live DB: "knowledge and belief" 5 documents (was 0 title matches), "impleadment rejoinder" 2
  (was 0), "freeze funds terrorist" 12, "Security Council" 8 matters + 12 documents; 11–160 ms.
- Note: `DOC-F5E089EA53` is not found by "knowledge and belief" because its text layer reads "knowledgeand";
  A1 covers the extraction side.

## A1 — stop false corrections on PDF text
- [x] 2026-10-04 page provenance from the stored PDF (`app/documents/text_origin.py`, cached by hash; no migration):
      Rejoinder pages 14–16 are scans, 1–13 born-digital
- [x] 2026-10-04 `read_document` marks scanned pages inside the text; prompt and `propose_edits` description say a
      PDF is read-only and spacing/OCR differences are not errors
- [x] 2026-10-04 `app/chat/tools/edit_guard.py` in `propose_edits` and `edit_document`: spacing-only edits dropped on
      any PDF; one-word look-alike typos dropped on scanned pages when the odd word is rare and the fix common;
      numbers, insertions, deletions and swaps between common words kept
- [x] 2026-10-04 same test on the answer's prose (quoted scan-only word called an error; original/fix pairs)
- [x] 2026-10-04 PDF cards are read-only recommendations; export returns 409 for a PDF
- [x] 2026-10-04 `tests/test_edit_guard.py` (21), `evals/pdf_artifact_eval.py` (408 artifacts: false-correction rate
      100% → 0%, controls kept 100%), `evals/pdf_edit_live.py` (10 live runs: 0 spacing cards, 0 artifact claims,
      8/10 found the real defects). Decision record: `docs/experiments/pdf_false_corrections_2026-10-04.md`
- Plan changed after measuring: a better extractor does not help (the OCR layer itself has no space glyph); no
  `text_origin` migration (derived from the file); no word-frequency glue test (spacing edits on a PDF are dropped
  outright).
- [ ] hallucinated quotes (`Hon\'ble`) are not checked against the stored text
- [ ] normalize known OCR glue for **search** only

## C1 — token-aware diff
- [x] 2026-10-04 `app/documents/tokens.py`: one tokenizer (whole numbers/dates, words, punctuation apart) and
      `word_ops` (changes separated only by a space are one change), used by the tracked-change writer
      (`docx_tracked._replace`), the editor compare (`_word_diff`), the redline and the engine's change summary
- [x] 2026-10-04 `tests/test_diff_tokens.py` (22): lossless tokens, `INR 1,20,00,000.` marks only the number, `1`→`7`
      and `17`→`7` are whole-number replaces, accept/reject round trip, docx XML has exactly one del and one ins
- [x] 2026-10-04 one existing expectation updated on purpose: the verifier summary reads `[-9-]{+10+},` (comma
      untouched) instead of `[-9,-]{+10,+}`. `evals/editor_roundtrip_eval.py` gates unchanged (all checks OK, save
      p95 1.39 s < 3 s, LibreOffice render OK)
- **Finding that changes C3:** the file we write is correct (`<w:del>1,20,00,000</w:del><w:ins>1,50,00,000</w:ins>`,
  which rejects to the old text and accepts to the new). The "glued" look is only how LibreOffice/Word draw adjacent
  del+ins, and a visible gap cannot be put in the file (it would change the text on accept/reject). The user's
  `~~1~~7` is simply `1` replaced by `7`. So the fix for the look is rendering: clean view by default and our own
  diff view with a gap (C3).

## C2 — clean-HEAD commit model
- [x] 2026-10-04 migration `20261004a_version_commits.sql` (additive: `is_clean`, `restored_from_version_id`,
      `source_storage_uri`); commit message = `change_summary`, kind = `origin`
- [x] 2026-10-04 save stores the clean document (authorship still recorded from the tracked form); a file with someone
      else's pending changes keeps them until cleaned
- [x] 2026-10-04 Word upload with tracked changes becomes commit(s) credited to the reviewers, raw file kept
- [x] 2026-10-04 `GET commits`, `GET diff` (+ word counts), `POST restore` (new version, re-indexed), `GET blame`
- [x] 2026-10-04 `scripts/clean_versions.py` backfill (dry run by default). **Not applied** to the shared database
- [x] 2026-10-04 tests: `tests/test_document_history.py` (15), four editor tests updated on purpose, Word review tests
      now build legacy rows; full suite 988 passed. Decision record: `docs/experiments/document_commits_2026-10-04.md`
- Plan changed after measuring: blame is computed on demand (0.9 s cold for 1,172 paragraphs × 200 versions), so there
  is no `document_version_changes` table
- Found by the tests: the object store keys every version file `original.<ext>`, so the raw upload overwrote the
  clean copy; the raw copy is stored as `uploaded.<ext>` and the backfill refuses to overwrite
- [ ] apply the backfill (the CTO agreement from the report is `DOC-7405413EC8`)
- [ ] one commit per reviewer on import (allows reverting one person's changes)

## C3 — frontend
- [x] History tab (commit log: message, kind, author, date, size change), Changes dialog (old → new with an arrow, word
  counts, Redline .docx link), "Who wrote what" tab, Restore dialog (creates a new version)
- [x] clean default: a file that still carries tracked changes opens in the Final view
- [x] verified in Chrome on a throwaway CTO-style agreement (`evals/history_ui_fixture.py`, `evals/history_ui_check.cjs`):
  INR 1,20,00,000 → 1,50,00,000 shows as `1,20,00,000` (struck) → `1,50,00,000`; restoring v1 made v4 current
- [x] "Review changes" button in the document toolbar: opens History on what the current version changed
- [x] commit-message prompt on save: the editor's Save dialog already takes a note (it became the commit message)
- [x] `static/` bundle rebuilt (2026-10-04, after D)
- [x] document queries and the commit log refetch when the tab regains focus, so an edit accepted elsewhere shows up

## D — drag a page to the Assistant; accepting an edit changes the document

Reported 2026-10-04 (the CTO agreement, "fix this page 9, I don't want tracked changes but the actual change").
Causes found by reading the code and a live run:
1. **Accept only recorded a decision.** The document changed only through the "Word file (N)" button, which wrote
   tracked changes (crossed-out text) into a new file. So accepting did nothing "in real time", and what finally
   appeared was the crossed-out look again.
2. **"Page 9" meant nothing.** A Word file with no page rendition is shown as *Part 1 of 1*; the Assistant had no way
   to know what the lawyer was pointing at and asked which page they meant.
3. **The answer was cut up.** The verifier judged the Assistant's own sentences about its edits ("I'll fix…", "Please
   accept…") as claims about the documents and removed them ("4 statements removed…"); the sentence splitter also
   broke `"3. Remuneration"` after the "3.".

- [x] **Accept writes the change** (`app/documents/assistant_apply.py`, `chat_router.decide_edit/decide_edits_bulk`):
  the accepted edits become one clean version ("Assistant: <instruction>"), placed by paragraph id when that paragraph
  still reads as proposed, otherwise by finding the passage in exactly one paragraph; anything else stays pending with
  the reason. An applied edit cannot be un-accepted from the card (History → Restore). PDFs stay recommendations.
  Export after accepting is a **redline** between the two versions and writes nothing.
- [x] **Drag a page**: pages/parts in the page list and the "Page n of N" handle in the reader are draggable; the AI tab
  is a drop zone ("Continue in Assistant" hands the pages and the typed instruction to the chat, pre-filled, never
  auto-sent); the chat composer is also a drop target. A reference (`document_id`, version, page|part, part_size) is
  stored on the message; the server resolves its text itself (`app/chat/page_reference.py`, ACL-checked) and puts it in
  the prompt, and the prompt tells the model "this page" means that text.
- [x] **Reports are not claims**: in a turn that produced edit cards, sentences that report the Assistant's actions or
  restate a proposed edit skip verification; real claims are still checked. The splitter keeps a quoted clause number in
  its sentence.
- [x] Tests: `tests/test_assistant_apply.py` (11), `tests/test_grounding.py` (+4), `tests/test_edit_document_flow.py`
  (legacy export). Browser: `evals/assistant_drag_check.cjs` (drag → AI tab → chat attachment, composer drop, accept all →
  "In the document · v4", no struck text left, History + Review changes); live model: `evals/page_reference_live.py`
  (reads the dragged page and proposes the edit without asking; 1 of 2 runs still lost one prediction sentence before the
  last regex tweak, not re-measured).
- [ ] accepted edits are not yet visible in a document open in another tab until it refetches (queries are invalidated
  in the same tab only)
- [ ] a model that ignores the page and asks anyway: not seen in 3 live runs, no counter-measure built

## Log
- **2026-10-04** D: accept writes a clean version; drag a page to the Assistant; edit-turn reports no longer cut as
  unsupported claims; Review changes button. 1003 passed / 5 skipped, typecheck clean, Chrome + live runs.
- **2026-10-04** C3: History panel, diff dialog with arrow, blame, restore; typecheck clean, 988 passed / 5 skipped, Chrome check clean.
- **2026-10-04** A1: the Assistant no longer reports scan reading errors as document defects (cards 100% → 0%, live prose 2/3 → 0/10).
- **2026-10-04** Investigated all three problems (three read-only explorations, measurements on the real PDF and
  DB), plan approved. Built and verified B1 over HTTP and in Chrome.
