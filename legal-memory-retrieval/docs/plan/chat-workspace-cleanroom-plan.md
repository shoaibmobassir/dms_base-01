# Chat workspace — clean-room requirements and build plan

**Date:** 2026-09-25
**Status:** Implemented 2026-09-25 (R1–R9, viewer). Word-to-PDF pages wait on converter approval; Word files use the text view until then.
**Clean-room note:** Written from a product-level review of Mike (AGPLv3). This
file holds requirements in our own words only. It contains no Mike code, file
names, event names, component names, prompts, or layouts. Implement from this
file in a session that has **not** opened the Mike repository.

---

## 1. What a lawyer needs (requirements)

### R1 — Visible working steps
While an answer is being produced, the lawyer sees what the assistant is doing,
step by step: thinking, searching firm records, reading a document, searching
inside a document, drafting a file. Each step shows a short label and a
running/done state. Thinking text can be expanded or collapsed. Steps stay in
the transcript after the answer finishes.

### R2 — Research
The assistant can search the firm corpus and the documents attached to the
conversation, read whole documents, and look for specific passages inside one
document. It says which documents it used.

### R3 — Citations with exact quotes
Every factual claim drawn from a document carries a numbered marker. Each marker
resolves to: document, page, and the exact quoted words. One marker may point to
several quotes. A sources list under the answer shows all cited documents.

### R4 — Citation checking
After the answer, each quote is checked against the stored document text. A
quote that cannot be found is flagged clearly as unconfirmed. Confirmed quotes
show no warning (quiet by default).

### R5 — Clarifying questions
When the request is ambiguous or a needed document is missing, the assistant
stops and asks. The questions appear as a small form in the chat (pick an
option, type an answer, or attach a document). The answer is sent back as the
next turn.

### R6 — Document review with suggested edits
The lawyer can ask for a review of a document. The assistant proposes specific
changes (original text → proposed text, with a reason). Each change appears as a
card that can be accepted or rejected. Accepted changes produce a new document
version (tracked changes in DOCX). The cited location of each change can be
opened in the viewer.

### R7 — Generated files
The assistant can produce a DOCX or XLSX. It appears in the chat as a
downloadable file and can be opened in the viewer.

### R8 — Document viewer beside the chat (see §2)
Clicking a citation or a file opens the document beside the conversation, at the
right page, with the quoted words highlighted.

### R9 — Conversation management
Stop a running answer. Keep a history of conversations with auto titles. Attach
documents to a conversation. Choose a model and a work mode.

---

## 2. Viewer design (Part 2)

Goal: a plain, dependable viewer. Not an editor.

| Decision | Choice | Why |
|---|---|---|
| Layout | Chat left, viewer right, draggable divider (min 360 px each side); viewer collapsible; opens automatically on citation click | Lawyer reads answer and source side by side |
| PDF rendering | `pdfjs-dist` (Apache-2.0) rendering to canvas + text layer | Real pages, real page numbers, selectable text we can highlight. The current `<iframe>` gives no control over page or highlight |
| DOCX rendering | Convert to PDF on the server (LibreOffice headless, run as a separate process), cache the PDF per version, show it in the same PDF viewer | One viewer, one highlight method, true page numbers that match citations. Rendering DOCX as HTML has no fixed pages |
| Fallback | If conversion fails, show the extracted text view (what we have today) with the quote marked | Viewer never shows a blank panel |
| Aspect ratio | Each page keeps its own width/height ratio from the PDF (A4 ≈ 1 : 1.414). Default zoom = fit width of the panel | No stretched pages at any panel width |
| Scrolling | One vertical scroll container with all pages stacked, a gap between pages. Pages render only when near the viewport; placeholders keep correct height | Smooth for 300-page filings |
| Page controls | Toolbar: previous / next, editable "page N of M" box, zoom out / zoom in, fit width, fit page. Current page number follows scrolling. Keyboard: PgUp/PgDn, Ctrl+± | Required by user |
| Other toolbar items | Document title, download original, close | — |
| Highlight | On citation click: jump to cited page, find the quote in that page's text layer (whitespace/hyphen tolerant, then fuzzy), draw a translucent box over matched spans, scroll it to centre. If not found on that page, search ±1 page, then whole document. If still not found, show a notice and keep the page | Page numbers in extracted text can be off by one |
| Multiple quotes | Small "quote 1 of 3" switcher in the toolbar | R3 |

---

## 3. What we already have (gap vs. requirements)

| Req | Status today | Gap |
|---|---|---|
| R1 | Backend emits a reasoning event and tool events for read/find/create; UI shows reasoning text | No step timeline; tool events for search are not shown as steps |
| R2 | `search_firm_records`, `read_document`, `fetch_documents`, `find_in_document` tools exist | Check they work on newly uploaded documents |
| R3 | Citations produced and sent after the answer | Multi-quote per marker and sources list need review |
| R4 | `verify_citations.py` exists | UI flag for unconfirmed quotes needs checking |
| R5 | `ask_inputs` tool exists in backend | **Frontend does not handle it** — needs a form component and reply flow |
| R6 | DOCX redline generator exists | **No edit-proposal tool in chat, no accept/reject cards** |
| R7 | `generate_docx`, `generate_excel` tools exist | Confirm download and viewer open work |
| R8 | `CitationDocumentPanel` uses an `<iframe>` for PDF and a text view with the quote marked | **No page control, no zoom, no highlight on the real page, no DOCX pages** |
| R9 | Stop, sessions, titles, models, modes exist | Attaching documents to a conversation needs checking |

Chunks already store `page_number` (`app/documents/hierarchical_chunks.py`), so
citations can carry a page.

---

## 4. Build order

1. **Load test documents.** Ingest the 7 PDFs in `../docs/` through the normal
   upload path. Confirm chunks, page numbers, and embeddings exist.
2. **Viewer (R8).** New `DocumentViewer` component (our design, §2). New
   endpoint `GET /api/documents/{id}/render.pdf` that returns the PDF as is, or
   converts DOCX to PDF and caches it. Replace the iframe in
   `CitationDocumentPanel`.
3. **Step timeline (R1).** Show each backend event as a step in a vertical list
   above the answer. Add events for firm search.
4. **Clarifying questions (R5).** Form component for the existing `ask_inputs`
   event; submit as the next user turn.
5. **Citations (R3, R4).** Sources list, multi-quote switcher, unconfirmed flag.
6. **Review with edits (R6).** New chat tool `propose_edits` returning a list of
   {location, original, proposed, reason}. Cards with accept/reject. Accept →
   new version through the existing redline generator.
7. **Generated files (R7)** and **attachments (R9)** — check and fill gaps.
8. **Test on Bedrock.** Use the `.env` Bedrock settings (never hard-code keys).
   Run one scripted conversation per feature against the `docs/` PDFs. Add
   Playwright tests for: citation → viewer opens at the right page with a
   highlight; page box navigation; zoom; clarifying form; accept/reject.
9. **Security later.** Run with `AUTH_ENABLED=false` for now, as agreed.
   Tighten access checks afterwards.

## 5. New dependencies (need license check before install)

| Package | License | Notes |
|---|---|---|
| `pdfjs-dist` | Apache-2.0 | Permissive — OK |
| LibreOffice (system binary, not bundled) | MPL-2.0 | Run as a separate process; **flag for owner approval** |

Record both in `docs/legal/DEPENDENCY_AUDIT.md` before installing.
