# 03 — Document viewer, anchors, selection actions, compare

> File rendering (DOCX/PDF/scans/email/sheets), the ingest pipeline and versioning are
> specified in `06_DOCUMENTS_RENDERING_VERSIONING.md`, which supersedes §2 and §7 below where
> they differ. The Reader mode here remains the fallback for text-only documents.
> The workspace — fixed frame, page jumps, virtualized pages, versions, compare, and the
> side panels — is `07_DOCUMENT_VIEWER_ARCHITECTURE.md`. Selection actions in §4 are the
> menu that workspace opens.

## 1. What exists today (measured 2026-09-24)

| Fact | Consequence |
|---|---|
| 3,083 of 3,123 documents have **no original file** (`source_uri` null); the 40 that do point at pytest temp files | No PDF can be rendered; "Download" works for almost nothing |
| **38 of 36,229** chunks have `page_number`; 38 have `section_title` | "Page 47 · Section 12.3" citations are impossible from current data |
| `document_blocks` has 347 rows (only recently ingested docs) | Block-level anchors work only for a small set |
| `resolve-anchor`, `blocks`, `annotations`, `findings`, `versions/diff` endpoints exist | The anchor/annotation plumbing is there; the data isn't |
| Tests insert documents into the dev DB (pytest temp `source_uri`s) | Test isolation bug — fix alongside (04 §7) |

So the viewer must work **without** originals first, and gain page fidelity when ingest
stores originals (P6).

## 2. Decision: one `DocumentViewer`, two render modes (D4)

| Mode | When | What it shows |
|---|---|---|
| **Reader** | Always available (text + blocks/chunks) | Typeset document: title block, section outline, paragraphs with stable ids; looks like a clean legal document (serif headings, numbered clauses preserved), not a text dump |
| **Page (PDF)** | Original PDF stored and page map known | Real pages via a PDF renderer (pdf.js, Apache-2.0) with a text layer; highlights drawn from char offsets mapped to page text |

- The mode toggle appears only when both are available; citations open in Page mode if
  it exists, else Reader.
- DOCX originals: render via server-side conversion to PDF at ingest (LibreOffice
  headless in the worker) so Page mode covers Word files too; otherwise Reader.
- Spreadsheets (Cap Table.xlsx): **table mode** (sheet tabs + grid) from extracted
  cells; citations anchor to `sheet!cell` (the citation model already has `sheet`/`cell`).

**Why not PDF-only?** Most corpus documents have no PDF, and even with PDFs a reader view
is better for search, selection, accessibility and mobile. **Why not reader-only?**
Lawyers trust what they can see on the page they will file or sign; page numbers are how
they cite. Both, with one anchor model, is the only option that serves both.

## 3. Viewer anatomy (full page `/documents/:id` and panel mode)

```
┌ Share Purchase Agreement.pdf ─ v4 · 86 pp · Analyzed ─────────────────────────────┐
│ [Reader|Page] [🔎 Search] [−][+] [◀ p.47/86 ▶] [⬇] [⛶] [Ask about this document] │
├── Outline ──┬─────────────── Document ───────────────┬── Rail ───────────────────┤
│ Art. I      │  ARTICLE XII                            │ Matter: Acme Acquisition  │
│ …           │  TERMINATION                            │ Versions (4) · Compare    │
│ Art. XII ●  │  12.3 Termination for Material Breach   │ Findings (review engine)  │
│  12.1       │  ▌A Party may terminate this Agreement… │ Notes                     │
│  12.3 ●     │   (highlighted, linked to citation [1]) │ Cited in 3 conversations  │
└─────────────┴─────────────────────────────────────────┴───────────────────────────┘
```

- **Outline:** from `document_blocks` headings (or section detection at ingest); click
  scrolls; current section tracked while scrolling.
- **Search within document:** server-side (`?q=` highlight exists) with hit count, ↑/↓
  navigation, all hits highlighted.
- **Zoom:** Page mode scale; Reader mode font-size steps.
- **Rail:** matter link, versions (→ history/compare), **findings** from the review engine
  (real, per version — replaces code_pre's mock "AI findings"), notes, "cited in N
  conversations" (back-links to messages).
- **Panel mode** (inside chat): same component, rail hidden, outline as a dropdown.
- **Restricted:** outsiders get the standard not-found state; insiders see a Restricted
  badge.
- **Full screen:** `⛶` or `f`; Esc exits.

## 4. Selection actions (spec §14)

- Selecting text shows a floating toolbar anchored above the selection:
  **Ask AI · Explain · Summarize · Rewrite · Risk · Find similar · Compare · Define ·
  Draft alternative**.
- Each action sends a message to the active conversation (panel mode) or opens a new
  matter conversation (full page), with the selection attached as a **quoted context
  item** (anchor + text), so the answer can cite it precisely.
- "Find similar" = retrieval restricted to clause-like blocks across the matter/firm,
  results shown as source cards.
- "Add note" and "Copy with citation" (copies text + "Share Purchase Agreement, cl.
  12.3, p. 47") are always present.
- Keyboard: selection + `⌘⇧A` = Ask AI.

## 5. Compare & redline (spec §19)

Two entry points: version compare (same document) and any-two-documents compare.

```
VERSION 3 (10 Sep)                        VERSION 4 (18 Sep)          3 of 12 changes ◀ ▶
12.3 Termination                          12.3 Termination
… cure period of ~~thirty (30)~~ …        … cure period of __fifteen (15)__ …
[Accept] [Reject] [Comment]
```

- Alignment by section/block (the semantic diff in `app/documents/diff.py` already
  aligns blocks); inline word-level redline inside aligned blocks.
- Change list sidebar (type: added/removed/modified/moved) with navigation; filters
  (substantive only / all).
- **Accept / Reject** are meaningful only when producing a new working version: they
  build a pending version; "Create version" commits it (`POST versions/developing`
  exists). Comment → annotation on the block (exists).
- **Export:** tracked-changes DOCX (`/api/drafting/generate-docx-tracked` exists) and PDF
  comparison report.
- "Explain these changes" → chat with both versions as context.

## 6. Citation ⇄ viewer contract

1. Assistant message carries citations with anchors (02 §7).
2. Click → `DocumentViewer.open({document_id, version_id, anchor})`.
3. Viewer loads the version, scrolls the block into view, draws the highlight over
   `char_start..char_end` (Reader) or the mapped page rects (Page).
4. If the anchor can't be resolved (document changed), the viewer shows the quote in a
   banner "Cited text not found in this version — view the cited version" and offers the
   original version.

## 7. Ingest changes required (P6, detail in 04)

- Store originals in the object store at ingest (`documents.source_uri` → `s3://` or
  local object store key; never temp paths).
- Page-aware extraction: per block, record `page_start/page_end` and char offsets into
  the page text layer.
- Section detection: numbered headings (`ARTICLE XII`, `12.3`) → `section_path`.
- `pages` count and pipeline `status` on `documents` for the Documents table.
- Backfill the existing corpus from `dummy-firm/data/EN_PDF_ORIGINALSPLIT_FULL` and
  `docs/*.pdf` where originals exist.
