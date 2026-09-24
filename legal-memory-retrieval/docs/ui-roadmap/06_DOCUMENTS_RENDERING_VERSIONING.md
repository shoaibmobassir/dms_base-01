# 06 — Industry-grade document rendering & versioning

Answers Q8: lawyers upload their own **DOCX and PDF** (and scans, emails, spreadsheets);
Precentis must render them faithfully, cite into them precisely, and version them the way
a DMS does. Supersedes the "generated sample PDFs" idea.

Product research on `mike/` (AGPL) was done at feature and dependency level only, per the
clean-room rule. Observed capabilities, rewritten as our requirements, are marked **[R]**
and recorded in `docs/legal/IP_ORIGIN_RECORD.md`. No mike code or schema was used.

---

## 1. Requirements

| # | Requirement |
|---|---|
| R1 | Upload DOCX, DOC, RTF, ODT, PDF (text or scanned), XLSX/CSV, EML/MSG, TXT — single or bulk, drag-and-drop, into a matter/folder. |
| R2 | The original file is kept **byte-for-byte**, hashed (SHA-256), never modified. Download returns the original. |
| R3 | Every document displays with page fidelity: what the lawyer sees matches what they'd print or file. |
| R4 | A citation opens the exact page and highlights the exact text, in both PDF and Word documents. **[R]** (quote highlighting inside rendered Word documents) |
| R5 | Upload a new version onto an existing document; full version history; any two versions comparable. **[R]** |
| R6 | A version indicator ("v4 · Final") appears wherever a document appears: tables, chat sources, citation previews, viewer. **[R]** |
| R7 | AI-suggested edits are produced as **tracked changes**, reviewed change by change (accept/reject, or accept all/reject all), and saved as a new version. **[R]** |
| R8 | Export a redline (tracked-changes DOCX and a PDF comparison report). **[R]** |
| R9 | Versions are never rewritten; "restore" creates a new version from an old one. Executed/final versions can be locked. |
| R10 | Scanned PDFs become searchable and citable (OCR), with the scan still shown as the page image. |
| R11 | Untrusted files can't harm the system (macros, malformed files, zip bombs, password-protected files). |
| R12 | Per-document permissions follow the matter (ethical wall), including renditions, thumbnails and text. |

## 2. Architecture decision: *original + canonical PDF rendition + one text layer*

```
upload ──► store ORIGINAL (object store, immutable, sha256)
          │
          ├─► sanitise (type sniff, size/page limits, AV scan, macro strip, encryption check)
          │
          ├─► RENDITION: canonical PDF
          │     PDF (text)  → as-is (linearised)
          │     PDF (scan)  → OCR adds invisible text layer (page images unchanged)
          │     DOCX/DOC/RTF/ODT → converted to PDF in a sandboxed converter
          │     EML/MSG → rendered to PDF (headers + body), attachments become child documents
          │     XLSX/CSV → no PDF; table rendition (sheets/cells) instead
          │
          ├─► TEXT LAYER extracted FROM THE RENDITION
          │     per page: words with bounding boxes + char offsets
          │     blocks (headings, clauses, paragraphs, tables) with page + bbox + offsets
          │     section paths ("Article XII › 12.3") from numbering/headings
          │
          ├─► chunks + embeddings built from those blocks (retrieval), each chunk → block ids
          │
          └─► thumbnails (first page), page count, status = Indexed
```

**Why derive text from the rendition, not the source file?** Because citations must land
on what the user sees. If text came from the DOCX XML and display came from a converted
PDF, offsets drift (headers, footnotes, numbering, field codes). Using one text layer for
retrieval, citation and highlight makes "open at the exact passage" reliable for every
format.

**Why a PDF rendition for Word files instead of only rendering DOCX in the browser?**
Browser DOCX renderers are good for quick previews but paginate differently from Word,
so "page 47" can't be trusted, and layout varies by browser. A server rendition gives
stable pages, printing, thumbnails, and one highlight engine. We still offer a **Word
view** for DOCX (browser-side renderer) for reading tracked changes and comments as
authored — but citations and page numbers always refer to the canonical rendition.

## 3. Components and technology (to license-audit)

| Concern | Open-source default | License | Commercial upgrade path |
|---|---|---|---|
| Office → PDF | LibreOffice headless behind **Gotenberg** (HTTP conversion service, own container, no network) | MPL-2.0 / MIT | Aspose.Words / Apryse for higher DOCX fidelity |
| PDF text + geometry | **pdfplumber** / **pypdfium2** (words, bboxes) | MIT / Apache-2.0 & BSD | — |
| OCR | **OCRmyPDF** (Tesseract) | MPL-2.0 / Apache-2.0 | ABBYY / cloud OCR |
| PDF viewing | **pdfjs-dist** with text + highlight layers, virtualised pages | Apache-2.0 | Apryse WebViewer / Nutrient (PSPDFKit) — adds annotation, redaction, compare UI |
| Word view (secondary) | **docx-preview** | Apache-2.0 | — |
| DOCX structure (headings, numbering, tracked changes) | **python-docx** + direct OOXML parsing | MIT | — |
| Tracked-changes output | existing `app/drafting/docx_redline_generator.py` (ours) extended to per-change `w:ins`/`w:del` with author/date | ours | — |
| Spreadsheet view | table rendition rendered with our DataTable; large sheets virtualised | ours | — |
| AV scan | **ClamAV** sidecar | GPL-2.0 — **runs as a separate service, not linked**; needs legal sign-off per DEPENDENCY_AUDIT rules | commercial scanner |

The viewer talks to the rendition through an adapter (`DocumentRenderer` interface), so a
commercial SDK can replace pdf.js later without touching chat/citations.

## 4. Viewer behaviour (extends `03_DOCUMENT_VIEWER.md`)

- **Page view (default for all formats with a rendition):** virtualised pages, text
  selection from the text layer, highlight rects from block bboxes, zoom (fit width / fit
  page / %), page thumbnails strip, go-to-page, search (server hits → page + rects),
  rotate, full screen, download original, print rendition.
- **Word view (DOCX only):** faithful-ish browser rendering with tracked changes and
  comments visible as authored. Banner: "Page numbers follow the PDF view."
- **Table view (XLSX/CSV):** sheet tabs, frozen header, cell citations (`Sheet!B12`).
- **Email view:** header block, body, attachment list linking to child documents.
- Citations open Page view at the block's page, scroll to its bbox, pulse highlight.
- Mobile: page view with pinch zoom; thumbnails hidden.
- Large documents (1,000+ pages): render only visible pages ± 2; text layer lazily.

## 5. Versioning model

Uses the existing tables (`documents`, `document_versions` with `parent_version_id`,
`storage_uri`, `mime_type`, `page_count`, `change_summary`, `version_status`;
`version_diffs`; `annotations`) plus a few columns.

| Concept | Rule |
|---|---|
| Document | Logical record (title, matter, folder, type). `current_version_id` points at the working version. |
| Version | Immutable: original file + rendition + text layer + sha256. Numbered 1, 2, 3… per document. |
| Status | `draft` → `under_review` → `final` → `executed`; plus `superseded` automatically when a newer final exists. `executed` versions are locked (no new version without an explicit "amend" action that starts a new document lineage). |
| Upload new version | Drag a file onto a document (or "Upload new version"). Same-hash upload is rejected as a duplicate. Required: short change note. |
| AI edit → version | Suggested edits create a *proposal* (pending changes on top of version N). Reviewing = accept/reject each change; "Create version" writes version N+1 as a DOCX with the accepted changes applied **and** the tracked-changes history preserved, author = the reviewing lawyer, change note auto-drafted and editable. |
| Restore | Creates version N+1 as a copy of version k with note "Restored from v k". History never rewritten. |
| Compare | Any two versions (or two documents): block-aligned semantic diff (exists) + word-level redline; materiality flags from `version_diffs.risk_level`. |
| Citations & versions | Citations store `version_id`. Opening an old citation shows *that* version with a chip "Newer version available (v6)" and a "Show in current version" action that re-resolves the anchor. |
| Retrieval & versions | Search/chat use the **current** version by default; "include superseded versions" is a filter for due-diligence style questions. |
| Annotations | Anchored to a version's blocks; carried forward to new versions when the anchored text is unchanged (re-anchor by text hash), otherwise marked "orphaned" with the old quote. |
| Audit | Every upload, version, status change, restore, download writes `audit_events` (Q2). |

New columns/tables (migration): `document_versions.renditions jsonb` (pdf key, thumbnails,
page sizes), `document_versions.text_layer_uri`, `document_versions.locked boolean`,
`document_versions.ocr boolean`; `edit_proposals(proposal_id, document_id,
base_version_id, created_by, source_message_id, status)` and `proposal_changes(change_id,
proposal_id, block_id, kind ins|del|replace, before, after, rationale, status
pending|accepted|rejected)`.

## 6. Ingest service (backend)

- Split ingest into a **worker** (queue already exists in `app/sources/queue.py` /
  upload batches): stages `received → sanitised → rendered → text_extracted → indexed`
  (or `failed` with a reason the user can read). The Documents table shows these.
- Converter and OCR run in separate containers with **no network access**, CPU/memory
  and time limits, and a page cap per job; one retry, then `failed`.
- Password-protected files: status `needs_password`; the lawyer enters it once in the UI;
  the decrypted original is **not** stored — only the rendition and text.
- Macro-enabled files (DOCM, XLSM): original kept, macros never executed; rendition from a
  macro-stripped copy.
- Idempotent by sha256 per matter.

## 7. Backfill of the current corpus

- PCIJ and filing PDFs exist on disk (`dummy-firm/data/EN_PDF_ORIGINALSPLIT_FULL`,
  `docs/*.pdf`): re-ingest through the new pipeline to get originals, pages and bboxes.
- Documents with only text (synthetic corpus): keep Reader view; mark "No original file".
- Re-embedding is needed because chunks are rebuilt from blocks → run through the eval
  harness (`evals/retrieval_eval.py`) before switching the index (Recall@10 must not
  drop).

## 8. Phasing (replaces P6 in `00_ROADMAP.md`)

| Step | Delivers | Test |
|---|---|---|
| 6a | Object-store originals, sanitise, PDF passthrough, text layer with bboxes, page view in viewer, citations → page highlight (PDF only) | Upload a PDF, ask a question, click citation → page + rect contains quote |
| 6b | Gotenberg DOCX/DOC/RTF/ODT → PDF, Word view, thumbnails | Same test with a DOCX; page count matches Word's ±1 |
| 6c | OCR for scans, email rendering, table view | Scanned PDF answer cites a page; XLSX cell citation |
| 6d | Upload new version, version chip everywhere, restore, lock executed, citation version chip | Upload v2 → v1 citations show "newer version" |
| 6e | Edit proposals: AI suggested edits → review changes → new version with tracked changes; redline export | Proposal with 3 changes, accept 2, reject 1 → v(n+1) DOCX contains 2 `w:ins/w:del` pairs |
| 6f | Backfill + re-embed behind eval gate | Recall@10 ≥ current |

## 9. Acceptance

A lawyer can drag a 120-page executed PDF and a DOCX draft into Acme, ask "what is the
cure period for material breach?", click [1] and land on the right page with the clause
highlighted; ask the assistant to shorten the cure period in the draft, review the two
proposed changes, accept one, and download a tracked-changes DOCX that opens cleanly in
Word with the change attributed to them.
