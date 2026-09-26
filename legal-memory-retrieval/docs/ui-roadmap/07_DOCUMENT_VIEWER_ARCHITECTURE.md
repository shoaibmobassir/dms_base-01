# 07 — Document workspace

The document screen is a legal work surface. An 842-page agreement stays manageable because every location is an address: version, page, section, passage. The lawyer jumps there. They do not hunt by scrolling the application.

File conversion, OCR, and the text layer are `06_DOCUMENTS_RENDERING_VERSIONING.md`. This file is how that material is opened, addressed, compared, and cited.

---

## 1. Decisions

| Decision | What we do |
|---|---|
| Address | `document_id` + `version_id` + `page` + `block_id` + character range + `section_id` |
| App scroll | The application page never grows with the document. Sidebar and top bar stay fixed. |
| Default reading | **Single page.** One page in the canvas. Next, previous, and a typed page number replace it. |
| Continuous reading | Optional. The canvas may scroll a short run of pages. The application page still does not scroll. |
| What “page” means | A real page of the rendition when one exists. Until then the same controls move through **parts** of the text, labelled as parts, never as invented page numbers. |
| Render budget | Mount the current page and two pages either side. Prefetch two further ahead. Unload the rest. |
| Outline | Native headings first. An AI outline arrives later, labelled as AI, and never blocks reading. |
| Thumbnails | Optional, virtualised. They do not reorder pages. Page order belongs to the immutable version. |
| Versions | Append-only. Restore writes a new version. A matching hash is a duplicate, not a new version. A similar file asks; it never attaches itself. |
| Citations | Always name the version they were generated from. A later upload does not move them. |
| Right side | One panel. It switches among AI, versions, comments, bookmarks, and document info. |
| Permissions | The matter’s existing access check. Someone outside the matter gets the same not-found as everywhere else. No second role list. |
| Original bytes | Never rewritten. Download, print, export, OCR, and annotations read or copy. They do not edit the stored file. |

The loop the screen is built for:

**Search → jump → read → select → ask → cite → compare → annotate → come back to the same place.**

---

## 2. Shell

`/documents/:id` fills `<main>`. It opts out of the 1180px column and its page padding. `<main>` on this route is `overflow: hidden`. The workspace is `height: 100%`, column flex, `min-height: 0`, `overflow: hidden`.

```
┌─ viewport: overflow hidden ────────────────────────────────────────────────┐
│ sidebar      │ top bar                                                     │
│              ├─────────────────────────────────────────────────────────────┤
│              │ toolbar: title · version · page box · search · zoom         │
│              ├────────────┬──────────────────────────────┬─────────────────┤
│              │ left       │ canvas                       │ right panel     │
│              │ outline or │ the open page                │ AI, versions,   │
│              │ thumbnails │                              │ notes, info     │
│              └────────────┴──────────────────────────────┴─────────────────┘
```

- `min-height: 0` on the canvas, the left column, and the right panel. Without it, content stretches the page and the application scrolls.
- In single-page mode the canvas does not scroll the document. It shows one page, scaled. A scrollbar appears only if that one page is zoomed larger than the canvas.
- In continuous mode the canvas is the only document scroller, and it only mounts the render window in §4.
- Left and right columns scroll their own lists. They do not change the canvas height.
- Narrow screens turn both side columns into drawers. The canvas still fills the remaining height.
- Full screen hides the app sidebar and top bar. Escape restores them and keeps the same version and page.
- Empty, loading, restricted, and “still processing” states sit inside the canvas at full canvas height.

Chat can mount the same workspace in the context panel. The panel has a fixed height. The conversation keeps its own scroll.

Open documents are tabs on this workspace, not separate application pages:

```
[ Share Purchase Agreement ] [ SHA ] [ Disclosure schedule ]
```

Each tab remembers version, page, zoom, single/continuous, search query, active hit, and which side panels are open. Switching tabs restores that. Tabs live in the session. Reading position also persists on the server (§11), so reopening tomorrow offers “Continue on version 7, page 483”.

---

## 3. Page navigation

The toolbar always shows where you are and moves you without a search through the file.

```
[ ← ]  [  47  /  842 ]  [ → ]
```

The page number is an input. Typing `632` and confirming (Enter, or leaving the field) opens page 632. A number past the end stays in the field and does not move. First and last page are Home and End.

| Input | Action |
|---|---|
| Next / previous buttons, Left / Right | Adjacent page |
| Page Up / Page Down | Adjacent page in single-page mode; one canvas height in continuous mode |
| Home / End | First page / last page |
| `G`, or Cmd/Ctrl+`G` | “Go to page” with the number focused |
| Outline click | That heading’s page, then the heading on the page |
| Search result, bookmark, citation, AI page chip | That page and that passage |

Shortcuts apply when the workspace is focused. They do not fire while the lawyer is typing in search, the page field, a comment, or the AI composer.

Go to page:

```
Go to page
[ 632 ]
```

Enter confirms. Escape closes and leaves the current page.

The toolbar also names the section in view once the outline knows it (`12.3 Termination`). That label is a jump target back to the heading, not decoration.

---

## 4. What is rendered

A thousand-page file does not become a thousand DOM nodes, canvases, or text layers.

On open, load only:

1. Header: title, matter, type, `current_version_id`, page count, original present, processing stage.
2. Version list metadata. No bodies.
3. Outline headings, when they exist.
4. The landing page: page 1, the stored reading position, or the citation page.

Then the window around the current page:

```
Current: 47
Mounted: 45–49
Prefetched, not painted: 50–51
Unloaded: 1–44 and 52–end
```

Scrolling or jumping updates the window. Pages that leave it are destroyed, including their text layer. The current page stays mounted.

The window widens by a page or two while jumps stay fast, and shrinks back when they do not. It never becomes “load the document”.

| Surface | How it loads |
|---|---|
| Page pixels | HTTP range requests on the rendition. pdf.js in a worker paints the mounted pages only. |
| Text layer | The words and boxes for the mounted pages, used for selection and highlights. |
| Thumbnails | A virtualised strip. Mount thumbnails near the current page. Size is adjustable. Selecting one jumps. |
| Reader, no rendition yet | The same shell. Items are blocks in a range (`from`, `limit`), grouped into parts. The control says `Part 12 / 80`, not a false page number. |
| Sheets | Sheet tabs in the toolbar. Rows virtualised in the canvas. A citation is `sheet!cell`. |

Jumping never uses `scrollIntoView` on the application page.

1. Resolve the target to a version and a page (or a part).
2. Replace the mounted window.
3. In continuous mode, set the canvas scroll offset from the page index.
4. Highlight `char_start..char_end`, or the page rectangles.
5. If the anchor does not resolve, show the stored quote inside the canvas and a control to open the cited version.

Search hits, outline entries, and thumbnails that are not on the current page are lists of addresses. They are not pre-rendered pages.

---

## 5. Outline, thumbnails, search

### Outline

Left column, default tab.

```
1. Definitions
   1.1 Defined terms
2. Transaction
   2.1 Purchase price
```

Clicking a heading opens its page and marks the heading. The heading that contains the current page stays marked while the lawyer moves.

Source of the tree, in order:

1. Heading blocks already extracted (`section_id`, `section_title`, page). Label: the document’s own structure.
2. If those are missing and a later job produces an outline, show it under a visible label that it was generated. It can be wrong. It is not mixed into the native tree.

The document opens before either tree exists. The left column says the structure is not ready yet.

### Thumbnails

Second tab of the left column, closed until asked. Virtualised. No drag-to-reorder. Rearranging pages would be a different file, which is a new version created on purpose, not a gesture in the viewer.

### Search

The box searches the open version’s text index on the server. The client does not scan page images.

```
indemnification          3 / 18

Page 42    …indemnification obligations…
Page 87    …indemnification shall survive…
```

Choosing a row opens that page and highlights the match. Every match on the current page is marked. The active match is the one in the `3 / 18` counter.

Enter is next hit. Shift+Enter is previous hit. Both jump. They do not walk the lawyer through intervening pages.

---

## 6. Selection and the right panel

Selecting text on the page opens a bar on the selection:

**Ask AI · Explain · Summarize · Rewrite · Identify risk · Compare · Find similar · Copy · Add note**

Copy includes a citation line: title, version, section, page.

Every action carries the address of the selection (version, page, section, quote). The result opens in the right panel. “Ask AI” focuses the composer with the passage quoted above it:

```
Share Purchase Agreement · Version 7 · Page 47 · §12.3
“The Seller shall indemnify…”

What would you like to know?
```

Suggested prompts sit under the quote: explain, risks, related clauses, compare with the previous version, similar language, summarize, draft alternative language. Related clauses and similar language are retrieval over this matter, restricted to clause-like blocks, and each hit is a jump address.

The panel header can also run document-level jobs against the **open version**:

| Group | Jobs |
|---|---|
| Analyze | Summary, key provisions, risks, obligations, unusual clauses, missing provisions |
| Extract | Parties, dates, amounts, obligations, termination, indemnities, governing law, jurisdiction, caps, definitions |
| Review | Contract review, risk review, clause consistency, defined terms, cross-references |
| Compare | This version against another, or this document against another the lawyer can see |

These are jobs with a status, not a spinner that locks the page. Results are findings. Each finding has one or more addresses. A chip `Page 47` jumps. A comparison finding has two: `Version 6 · Page 47` and `Version 7 · Page 49`.

The composer always sends the open document, the open version, and the current page. Moving to page 300 changes that context for the next question. It does not rewrite earlier answers.

An answer stores the version it used:

```
Generated from Share Purchase Agreement · Version 6 · 842 pages
Current version is 7
[Compare changes]
```

Opening that answer later still cites version 6.

The right panel is one column with tabs: **AI · Versions · Comments · Bookmarks · Info**. Opening a tab does not remount the canvas.

---

## 7. Versions

A document is the identity (title, matter, folder, type). A version is an immutable snapshot: original bytes, checksum, rendition, text, page count, status, author, file name, size, source, change note. `current_version_id` is what search uses, and what the viewer opens when the URL names no version.

```
Version 7          Current · 24 Sep 2026 · Shoaib
Version 6          23 Sep 2026 · Sarah
Version 5          21 Sep 2026 · Shoaib
```

The versions tab shows the chain. The toolbar chip repeats the open one (`v7 · Final`). If the open version is not current, the chip says a newer version exists and offers to switch. Switching does not move citations that named the old one.

Metadata on a version: number, author, time, file name, size, page count, type, SHA-256, source (`upload`, `restore`, `proposal`), change note, status (`draft`, `under_review`, `final`, `executed`), parent version, locked flag.

The URL is the open location:

```
/documents/:id?version=:versionId&page=47&block=:blockId
```

Absent `version` means current. Changing version reloads outline, page count, and the window. The shell stays. The same section path is kept when the new version has it; otherwise page 1. Back returns to the previous address.

On the version: open, compare, download original, rename the label, edit the change note, restore. Rename and the note do not change bytes or the checksum. Restore creates version N+1 as a copy, note “Restored from version k”. History is not rewritten. `executed` is locked until an explicit amend, which is also a new version.

Upload of the same hash is rejected as a duplicate. Upload of a different file that looks like this document (name, title, structure, similarity) asks:

```
This looks like a new version of Share Purchase Agreement
[Upload as version 8]  [Save as a separate document]
```

Nothing is overwritten either way.

`/documents/:id/history` redirects here with the versions tab open.

### Compare

Compare is a mode of this workspace, not another application page.

```
Version 6  ↔  Version 7          Change 12 of 48
[Previous change]  [Next change]  [Redline | Clean]
```

The canvas splits. Each side is its own page window, virtualised the same way. Scroll stays in sync unless the lawyer turns that off. Previous and next jump both sides to that change. Added, removed, and modified text are marked on the page. Clean mode shows the later version without marks.

“Summarize the significant changes” runs in the AI tab against those two versions. Each bullet jumps to both pages.

Accept and reject exist only while reviewing a proposal. Creating the version writes N+1. It does not edit version N.

Export of a tracked-changes DOCX or a comparison PDF downloads a new file.

### Citations

A citation that says only “SPA.pdf, page 47” is incomplete. The stored form is:

```
Share Purchase Agreement
Version 7
Page 47
Section 12.3
```

plus `document_id`, `version_id`, `block_id`, and the character range. Opening it loads that version even after version 8 exists.

---

## 8. Comments, marks, bookmarks

Comments and marks hang off a version, a page, and a text range (and a block when there is one). Version 6’s comment is not drawn on version 7 unless the anchored text hash is unchanged, in which case it is carried forward. If the text changed, the comment is kept on version 6 and shown on the new version as orphaned, with the old quote. It is not pinned to the wrong paragraph.

A comment thread:

```
Page 47 · §12.3
Shoaib — This termination period should be reviewed.
Sarah  — Agreed. Updated in version 7.
```

Marks: highlight, underline, strikethrough, note. Same address as a comment. They are annotations, distinguished by type.

Bookmarks are the lawyer’s own jump list:

```
★ Termination     v7 · page 47
★ Liability cap   v7 · page 61
```

Clicking one opens that version and page. Bookmarks do not follow a newer version on their own.

---

## 9. Split view

Three arrangements, same shell:

| Arrangement | Canvas | Right side |
|---|---|---|
| Read | One version | Panel tab |
| Compare | Two versions, or two documents the lawyer can see | Change list, or AI |
| Notes | One version | Comments for this page |

Document + AI is the read arrangement with the AI tab open. It is not a separate product surface.

---

## 10. Zoom, print, info

Zoom: in, out, fit width, fit page, actual size. Default is fit width, single page. Full screen is §2.

Download the original of the open version. Print the current page, or a page range, from the rendition. Export selected pages, an annotated copy, a comparison, or an AI analysis as a new file. None of these write back to the original.

Info tab:

```
Share Purchase Agreement
PDF · 842 pages
Version 7 of 7
Uploaded 24 Sep 2026 · Shoaib
Checksum, size, source, change note
```

---

## 11. Coming back

Per member and document, the server stores the last version, page, zoom, and single/continuous choice. On return:

```
Continue
Share Purchase Agreement · Version 7 · Page 483
```

Search text and which panel was open are restored from the session when the tab is still there. They are not required to survive for weeks.

---

## 12. Processing

The original file is immutable. Each version is processed on its own:

```
original bytes
  → version row (hash, name, size, author, note)
  → rendition (page images / PDF)
  → text layer (and OCR text, if the scan had none)
  → sections (blocks)
  → search index
  → embeddings
  → AI jobs (outline fallback, review, extraction)
```

The toolbar shows the stage. The lawyer can open the file as soon as a page can be painted and, if text exists, selected. Search waits for the index. AI actions wait for their own job. Outline generation and review do not hold the first page hostage.

```
✓ Uploaded
✓ File checked
✓ Text extracted
✓ Pages indexed
● Structure
○ Review
```

A scan with no text layer says so in the canvas and offers OCR. OCR text is stored beside the original. The original bytes stay the scan. After OCR, search, selection, and page citations use the text layer.

Pipeline detail, converters, and page caps stay in `06`.

---

## 13. Data already in the system

Use the tables that exist. Add columns and two small tables. Do not create a parallel document model.

| Idea | Where it lives |
|---|---|
| Document | `documents` (`current_version_id`, matter, folder) |
| Version | `document_versions` (number, parent, status, hash, `storage_uri`, `page_count`, `change_summary`, author, source). Add rendition pointer, text-layer pointer, file name, byte size, `locked`, `ocr`. |
| Page | A page record per version: number, width, height, text-layer slice, thumbnail key. Not a second copy of the file. |
| Section | `document_blocks` (`section_id`, `section_title`, `page_number`, offsets, `text_hash`). Add `outline_source`: `native` or `generated`. |
| Text | Text layer of that version, sliced by page. |
| Comment, highlight, note | `annotations` (already version, page, offsets, quote, hash, author). Add `parent_annotation_id` for threads. |
| Comparison | `version_diffs` |
| AI finding | `findings` + `evidence_anchors` (already version, page, block, quote) |
| Citation on an answer | The message’s citation stores `version_id`, page, block, offsets. |
| Activity | `audit_events` (upload, version, download, comment, compare, restore, export, AI job). Shown in the info tab. |
| Bookmark | New `document_bookmarks`: member, document, version, page, block, label. |
| Reading position | New `member_document_state`: member, document, version, page, zoom, mode. |
| Ingest stage | The version’s processing status, same worker stages as `06`. |

Access to every one of these is the document’s matter check. A range of pages is not a new permission.

---

## 14. APIs the workspace calls

These existing calls return an entire body, every block, or every chunk. The workspace does not use them to paint:

- `GET /documents/{id}/versions/{version_id}` when the payload includes `body`
- `GET …/blocks` with no range
- `GET /documents/{id}/chunks`

| Call | Returns |
|---|---|
| `GET /documents/{id}` | Header only. No body, no chunks. |
| `GET /documents/{id}/versions` | Metadata list. No bodies. |
| `GET …/versions/{id}/outline` | Headings: id, section path, page, index, `outline_source`. |
| `GET …/versions/{id}/pages/{n}` | Size, text-layer slice, thumbnail URL. |
| `GET …/versions/{id}/blocks?from=&limit=` | A range, plus `total`. Used for reader parts. |
| `GET …/versions/{id}/search?q=` | Hits: page, block, offsets, snippet, count. |
| Rendition `GET` | Honour `Range`. |
| `PUT` reading state, bookmarks, annotation threads | The rows in §13. |
| Upload, restore, diff | Existing version endpoints. The client then sets `version` in the URL to the id returned. |

Similar-file detection runs at upload and returns a suggestion. The client chooses version or new document.

---

## 15. Permissions

Seeing the document is the matter access check already used on document routes. Failing it is a not-found, including for an old version, a thumbnail, a text layer, and a comment.

On top of that, actions check the member’s ability on the matter:

| Action | Who |
|---|---|
| Read, search, jump | Anyone who can see the matter |
| Comment, bookmark, mark, AI on this document | Members who can work the matter |
| Upload a version, restore, edit the change note | Members who can add documents |
| Download, print, export | Members who can see the matter; each download is audited |
| Delete a document | Not a viewer gesture. Versions are not deleted from this screen. |

There is no in-viewer role called owner, reviewer, or external collaborator. People outside the firm receive an export, not a login to this workspace.

---

## 16. Build order

Each step is done only when a long document opens inside the fixed frame and the application’s own scrollbar never appears.

| Step | Done when | Status |
|---|---|---|
| 1. Shell and page box | The route fills the frame. Single-page controls replace the page. Typing a number jumps. Side columns scroll on their own. | **Done** (`DocumentWorkspace`, fill-frame `AppShell`) |
| 2. Window | Only the current page ±2 is mounted. Jumping unloads the rest. Reader parts use the same controls and are not labelled as PDF pages. | **Partial** — reader loads one part (5 blocks/chunks) at a time; not continuous ±2 yet |
| 3. Jump lists | Outline click, search next/previous, and a citation open the page and highlight the passage. | **Partial** — outline + chunk deep-link; in-document search next |
| 4. Versions | URL holds version and page. Rail, metadata, restore-as-new, newer-version chip. `/history` redirects here. | **Partial** — URL + rail + chip; restore not wired in UI yet |
| 5. Right panel | Selection actions and document jobs return findings with page chips. An old answer still names its version. | Stub (link to Chat) |
| 6. Marks | Comments, bookmarks, and “continue on page N” survive a reload and stay on the version they were made on. | Not started |
| 7. Compare | Two windows, change N of M, redline and clean, AI summary with both addresses. | Not started |
| 8. Tabs, thumbnails, split | Several documents open, thumbnail strip virtualised, compare layout is the split. | **Partial** — thumbnail list windowed |
| 9. Real pages | Rendition, range requests, workers, OCR, processing checklist (`06`). Search and citations use those page numbers. | Not started |

Steps 1–8 work on the text and versions already stored. Step 9 is what turns a part number into a page number a lawyer can trust.
