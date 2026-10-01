# Precentis UI roadmap — legal AI workspace

Status (2026-09-24): **P0 done** — see §6. Open questions answered — see §5.
Follows `docs/production-plan/` (security, data, pruning). Read in order:

| File | What it covers |
|---|---|
| `00_ROADMAP.md` | Vision, key decisions, phases, sequencing, open questions (this file) |
| `01_PAGE_AUDIT.md` | Every page: today vs `app/code_pre` vs target, with a verdict |
| `02_CHAT_WORKSPACE.md` | The AI workspace (chat) in full detail — the centre of the product |
| `03_DOCUMENT_VIEWER.md` | Viewer, citation anchors, selection actions, compare/redline |
| `04_BACKEND_GAPS.md` | Per feature: what the API already has, what to extend, what to build |
| `05_DESIGN_SYSTEM.md` | Tokens, dark mode, components, layout, responsive rules |
| `06_DOCUMENTS_RENDERING_VERSIONING.md` | Industry-grade DOCX/PDF rendering, citation highlighting, versioning, tracked-changes review |
| `07_DOCUMENT_VIEWER_ARCHITECTURE.md` | Document workspace: page jumps, virtualized pages, versioned citations, compare, notes |

---

## 1. What we are building

**Precentis** is a legal AI workspace. A lawyer works *inside a matter*: they ask questions,
the assistant reads the matter's documents (and, where configured, legal authorities), and
every claim links to the exact passage it came from. Documents, drafts, research and
deadlines hang off the same matter.

Reference points:

- **`app/code_pre`** — our own visual language (Paper / Ink / Wine, DM Serif Display +
  Manrope, hairline tables, meta-labels, generous vertical rhythm). We keep it. It is
  mock-driven, so we copy *layout and interaction*, never its data.
- **Legora (and similar tools)** — product principles only: matter-scoped AI chat, a
  context panel beside the chat, citations that open the source passage, document
  selection as chat context, tool menus for review/extract/draft/research. We do **not**
  copy its brand, assets, copy or exact layouts. Legora is proprietary.
- **`mike/`** — AGPL. Product research only (clean-room rule in `../../../CLAUDE.md`).

## 2. Principles (apply to every page)

1. **Real data only.** The UI renders only API data. Demo content (the Acme matter, its
   documents, conversations) is seeded into Postgres (`scripts/seed_demo.py`), never
   hard-coded in `frontend/src`. This rule came out of the production plan and stays.
2. **Provenance over confidence.** No numeric confidence scores. Every answer says what it
   is based on (N matter documents, N authorities) and marks what it could not verify.
3. **The matter is the unit of work.** Chat, documents, research, drafts and deadlines are
   all reachable from — and scoped by — a matter. Firm-wide is a scope, not a separate app.
4. **One citation system.** Ask, chat, research and document tools all emit the same
   citation shape and open the same viewer. Today Ask and Chat render citations differently.
5. **No theatre.** Status lines while streaming come from real server events (retrieval
   stage, document being read), not timers. No fake feedback buttons, no decorative filters.
6. **Ethical wall is visible, never leaky.** Restricted items are absent for outsiders
   (404 = "not found or outside your scope"), marked "Restricted" for insiders.
7. **Code_pre density and calm.** Hairline tables, no nested cards, `max-w-[1180px]` for
   directory pages; the chat workspace is the one full-bleed, three-column surface.

## 3. Key decisions (with reasoning)

| # | Decision | Why |
|---|---|---|
| D1 | **Merge Ask the Firm into Chat.** `/ask?q=` becomes "start a conversation with firm-wide scope". One AI surface, one answer component. | Two AI surfaces with different answer UIs (Ask = one-shot card, Chat = thread) confuse users and double the citation work. Legora-style tools have one assistant with a scope selector. Ask's strengths (key finding, sources column) move into the chat response. |
| D2 | **Chat is matter-scoped by default**, firm-wide on request. `chat_sessions.matter_id` already exists. | Retrieval quality and the ethical wall are both better with a scope. The spec's "Matter context active" indicator becomes real. |
| D3 | **Three-column workspace**: history rail · conversation · context panel (Sources / Document / Notes). Panels collapse and resize. | The context panel is where trust is built: sources and the opened passage sit beside the claim. |
| D4 | **Every uploaded file gets a canonical PDF rendition; text for retrieval and citations is extracted from that rendition.** Page view for all formats with a rendition, Word view for DOCX, table view for sheets, reader view only for text-only legacy records. | Citations must land on what the lawyer sees; one text layer for retrieval, citation and highlight is the only way offsets never drift. Detail in `06`. |
| D5 | **Citations anchor to blocks, not pages.** Anchor = `(document_id, version_id, block_id, char_start, char_end)`, resolved by the existing `resolve-anchor` endpoint; page number is display metadata when known. | Pages don't exist for most content (DOCX, emails, text). Blocks exist for every format and survive re-rendering. |
| D6 | **Activity comes back only as matter-scoped, audit-backed events** ("You generated a risk analysis"), not the removed global Activity page. | You asked to remove Activity because it re-labelled document dates as activity. The spec's matter "Recent activity" is useful *if* it is real: written by the API when users act. **Confirmed (Q2).** |
| D7 | **Legal AI Tools = catalogue-driven.** The tool menu lists workflows from `app/workflows/catalog/*.yaml` plus built-ins (review, extract → tabular review). | The workflow engine, review engine and tabular review already exist server-side; the menu should not hard-code features the server can't run. |
| D8 | **Research mode ships in two steps**: (a) authorities *cited in firm documents* (citation extraction over the corpus), clearly labelled; (b) external case law — **deferred (Q3 skipped)**; web research (Q4) covers public sources meanwhile. | We have no Indian case-law source today; CourtListener in `caselaw_router` is US-only. Pretending otherwise would violate principle 2. |
| D9 | **Product name "Precentis"; firm name is the tenant.** Sidebar shows the Precentis mark; the workspace switcher shows "Harbour International Chambers". | Separates product brand from customer identity; matches multi-tenant intent (`tenant_id`). |
| D10 | **Sample Acme matter is seeded as real files** (DOCX and PDF) uploaded through the production ingest pipeline, so rendering, page citations and versioning are exercised exactly as lawyers' own files will be. | Spec §31 asks for Acme data; rule 1 says it must live in the DB; Q8 says rendering must be industry grade, so the demo must use the real pipeline. |

## 4. Phases

Each phase ends with Playwright tests against the seeded DB (as in production plan 06).

| Phase | Scope | Depends on | Backend work (see 04) |
|---|---|---|---|
| **P0 Foundations** | Design tokens incl. dark mode, component library (§32 list), resizable 3-column layout, mobile bottom nav, Precentis branding, Q7 navigation, Acme seed matter (documents authored as DOCX/PDF, ingested later by P6 pipeline; text-only until then) | — | seed extension, `firm_profile` fields |
| **P1 Chat workspace** | Unified chat (Ask merged), matter context header, context chips + selector, advanced composer, streamed stage events, response header/actions, citation chips + hover + Sources tab, provenance footer, history search/rename/archive/move-to-matter | P0 | chat context API, stage SSE events, citation anchors, regenerate, archive/move |
| **P2 Document viewer** | Reader mode, anchor highlight, in-document search, selection toolbar → chat, Notes tab | P1 citations | block API already exists; notes table |
| **P3 Matter workspace + Documents** | Matter tabs (Overview/Chat/Documents/Research/Drafts/Timeline/Notes), activity (if Q2 = yes), documents table with multi-select → Ask AI, drag-drop multi-upload with pipeline status, folders | P1, P2 | audit events, upload batches UI, folders for matters |
| **P4 Legal AI tools** | Tools menu, review findings panel, extraction → tabular view with export | P1 | workflow/review/tabular endpoints exist; wire + ACL |
| **P5 Compare & redline** | Version compare (exists), any-two-documents compare, change navigation, accept/reject/comment, export | P2 | cross-document diff endpoint, redline export exists (drafting) |
| **P6 Rendering & versioning** | Steps 6a–6f in `06_…`: originals, PDF/DOCX/scan/email/sheet renditions, page-accurate citations, upload new version, restore/lock, AI edit proposals with tracked changes, redline export, corpus backfill | P2 | ingest worker, converter/OCR containers, proposals tables |
| **P7 Research** | Research mode UI over authorities cited in firm documents, plus web research (Q4) with its own provenance class | P1 | authority extraction table; web search provider |
| **P8 Directory pages to code_pre depth** | Clients, People, Arguments, Deadlines, Teams, Settings with the richer code_pre layouts, all derived from real data | P0 | small aggregate endpoints |
| **P9 Polish** | Keyboard shortcuts, a11y audit, route code-splitting (bundle is 568 kB), empty/error/skeleton coverage | all | — |

Suggested order: **P0 → P1 → P2 → P6a–c → P3 → P6d–e → P4 → P5 → P8 → P7 → P9**. Real file
rendering moves ahead of the matter workspace, because lawyers adding their own documents is
the first thing a real firm will do. Directory polish (P8) is cheap and can run in parallel.

## 5. Decisions on the open questions (answered 2026-09-24)

| # | Question | Decision |
|---|---|---|
| Q1 | Merge Ask into Chat | **Yes.** `/ask?q=` creates a firm-scope conversation and sends `q`. |
| Q2 | Matter-scoped activity | **Yes**, from real `audit_events` only; no global Activity page. |
| Q3 | External case-law source | **Skipped for now.** Research = authorities cited in firm documents (D8 step a). The connector interface is kept so a source can be added later. |
| Q4 | Web research | **Yes.** Firm-level setting (default on for this firm), per-message toggle. Only the user's query is sent; document text never is. Web results are a fifth provenance class ("Web", globe icon) and are never mixed silently with matter sources. Queries logged in `audit_events`. Needs a search provider API key (admin setting). |
| Q5 | Voice input | **Yes.** Uses the browser's speech recognition. Tooltip on first use: "Audio is processed by your browser's speech service." Firm setting can switch to server-side transcription later. |
| Q6 | Sharing | **Decided — see below.** |
| Q7 | Navigation | **Decided — see below.** |
| Q8 | Documents | **Real DOCX + PDF rendering for lawyers' own files**, with versioning → `06_DOCUMENTS_RENDERING_VERSIONING.md`. The Acme sample documents are authored as DOCX (python-docx, already a dependency) and PDFs, then **uploaded through the same pipeline** — no separate PDF generator. |

### Q6 — Sharing: internal, permission-checked, snapshot-based

Lawyers share work with colleagues constantly, but a shared AI answer must never become a
side door through the ethical wall.

1. **Who:** only members of the firm. There are no public links. Outside parties get an
   **Export** (DOCX/PDF with citations listed), which is audited.
2. **What:** a conversation (read-only), a single answer, a saved draft, or a document
   deep-link (with anchor).
3. **With whom:** by default the matter team; you can also pick individual members. The
   picker only offers people who can access the matter. Firm-wide conversations can be
   shared with named members.
4. **Access is re-checked when the recipient opens it.** If the recipient loses access to a
   cited document, the citation renders as "Restricted source". The text of that passage is
   never shown.
5. **Snapshot by default:** the recipient sees the conversation as it was when shared. A
   "Continue in my own conversation" action forks it, so their follow-ups don't edit your
   thread.
6. **Revocable:** the sharer can revoke access. Every share, open and revoke is written to
   `audit_events`.
7. **UI:** a Share dialog with the member picker, a "Matter team" quick option, the current
   access list and a revoke action. A "Shared with me" filter is added to the history rail.
8. **Data:** `shares(share_id, object_type, object_id, snapshot jsonb, created_by, created_at,
   revoked_at)` and `share_recipients(share_id, member_id)`.

### Q7 — Navigation: organised around the matter

Final sidebar:

- **Work:** Home · Chat · Matters · Documents · Calendar · Research
- **Knowledge:** Arguments · Clients · People
- **Manage:** Settings (which gains a **Teams** section; `/teams` redirects there)
- **Below:** Pinned matters, then Recent conversations

Reasoning:
- **Calendar stays top-level** (renamed from Deadlines, with list and month views). A missed
  limitation or filing date is the costliest error in practice, and litigators check it
  across matters every day. It also appears on Home ("Coming up") and in each matter's
  Timeline.
- **Arguments moves under Knowledge.** It is reference material, not daily work.
- **Teams moves into Settings.** It is organisational admin, rarely visited.
- **Clients and People stay** under Knowledge, as directories reached from matters.
- **Mobile bottom nav:** Home · Matters · Chat · Documents · Profile. Calendar is reached
  from Home and ⌘K.

## 6. Progress

### P0 Foundations — done (2026-09-24)

- Dark mode (warm palette, `.dark` tokens, pre-paint script — no flash), theme menu in the
  top bar and Settings → Appearance; toasts follow the theme.
- Precentis branding (mark, title, favicon); firm shown as the workspace.
- Q7 navigation; `/deadlines` → `/calendar` (list + month view); `/teams` → Settings → Teams.
- Pinned matters (`member_pins`, ACL-filtered, pin/unpin on the matter header) and recent
  conversations in the sidebar; sidebar resizable by drag (220–320px, double-click resets).
- Mobile bottom nav; secondary table columns hidden on phones; breadcrumbs show record titles.
- Acme sample matter (`scripts/seed_acme.py`) authored as DOCX and ingested through the real
  upload pipeline, with a second SPA version (30 → 15-day cure period) for compare.
- Tests: pin contract + wall tests; 6 new browser tests (theme, calendar, redirects, pinning,
  resize, mobile nav, Acme ingest). Backend 559 passed; browser 15 passed.

Bugs found and fixed while doing P0:

| Bug | Fix |
|---|---|
| Uploaded documents were never embedded — invisible to semantic retrieval until `embed.py` was run by hand | `app/embeddings/pending.py`, called at the end of every upload batch |
| Uploads stored no matter code, client, author or date (showed "—") | Upload insert fills them from the matter and the uploader |
| New versions never reached the search index (unique `(document_id, chunk_index)` clash, error swallowed) — search kept returning the old text | Index holds the current version only; `reindex_current_version()` for repair/backfill |
| Matters/documents/clients pagination overlapped or skipped rows (non-unique sort keys) | Tie-breaker columns in `ORDER BY` |

Deferred from P0: the three-column resizable *chat* layout lands with P1; **Research** joins the
nav when its page exists (P7); each retrieved passage currently appears twice (parent and child
chunk) — fixed in P1 with citations.

Shared dev-database note: other sessions' fixtures (`seed_ci_minimal.py` renamed
`MEM-00001`/`MEM-00002`; `e2e-*` chat sessions; `MTR-CI-OPEN-001`) live in the same database.
Tests are written to tolerate them; the clean fix is a separate test database (04 §2).

## 7. Out of scope (for now)

Billing/time entry, email ingestion UI, e-signature, client portal, Word add-in redesign
(its auth is unfinished — production plan 07, item 3).
