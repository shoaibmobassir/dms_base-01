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
- [ ] tokenizer for numbers/dates, merge del+ins, visible gap, golden tests

## C2 — clean-HEAD commit model
- [ ] migration, history, diff, restore, blame, two-commit Word import, backfill

## C3 — frontend
- [ ] clean default view, History tab, Review-changes toggle, commit message on save

## Log
- **2026-10-04** A1: the Assistant no longer reports scan reading errors as document defects (cards 100% → 0%, live prose 2/3 → 0/10).
- **2026-10-04** Investigated all three problems (three read-only explorations, measurements on the real PDF and
  DB), plan approved. Built and verified B1 over HTTP and in Chrome.
