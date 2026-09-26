# 02 — AI chat workspace

The centre of Precentis. Replaces today's `ChatPage` and absorbs `AskPage` (D1).
Spec references (§n) point to the product brief you pasted.

## 1. Layout

```
┌ Sidebar ┐┌ History rail ┐┌──────── Conversation ────────┐┌─ Context panel ─┐
│ nav     ││ search       ││ Header: matter · status ·     ││ Sources│Doc│Notes│
│ matter  ││ Today        ││   Matter Sources (24 docs)    ││                  │
│ picker  ││  • SPA term… ││                               ││ source cards /   │
│         ││ Yesterday    ││ messages …                    ││ document viewer  │
│         ││  • …         ││                               ││ / notes          │
│         ││              ││ [context chips]               ││                  │
│         ││              ││ [ composer                  ] ││                  │
└─────────┘└──────────────┘└───────────────────────────────┘└──────────────────┘
   256px       240px (collapsible)      flexible (max 820px text)    360–640px resizable
```

- **Desktop (≥1280px):** all four columns; history rail and context panel collapsible
  (`[` and `]` shortcuts), context panel resizable by dragging its left edge.
- **Tablet (768–1279):** sidebar collapsed to icons, history rail as a popover from the
  header, context panel as a right drawer.
- **Mobile (<768):** conversation only; history via header button (sheet); context panel
  and document viewer full-screen with a back arrow. Bottom nav visible.
- The workspace is full-bleed (no `max-w-[1180px]` wrapper) — the only such page.

## 2. Header (spec §5)

```
Matters / Acme Acquisition                          [Matter Sources · 24 documents]
AI Legal Assistant   ● Matter context active                  [⋯ conversation menu]
```

- Breadcrumb = scope. Firm-wide chats show `Firm-wide` and a neutral dot.
- **Status dot semantics** (real, not decorative):
  - green "Matter context active" — the session has `matter_id` and the member can
    access it;
  - amber "Limited context" — some selected documents are no longer accessible
    (permission changed) and were dropped;
  - grey "Firm-wide" — no matter.
- **Matter Sources** button opens the Sources tab in "matter" mode: all documents in
  the matter with checkboxes → becomes the selected-documents context.
- Conversation menu: Rename · Move to matter · Share (internal, snapshot, ACL re-checked — `00_ROADMAP.md` Q6) · Export (DOCX/PDF of the
  conversation with citations) · Archive · Delete.

## 3. Welcome state (spec §6)

- Heading "What would you like to work on?" (serif), sub "Ask questions, analyze
  documents, research authorities, or draft legal work."
- **Six suggestion cards** (Analyze a document, Find a clause, Compare documents, Legal
  research, Draft, Summarize). Each card has an icon, title and an example prompt.
  - The example prompt is **filled with real names** from the current matter (e.g. the
    newest agreement's title) by `/api/chat/suggestions?matter_id=` — no fixed Acme text.
  - Cards that need something the matter lacks are disabled with a reason ("No two
    versions to compare yet").
- Clicking a card **inserts** the prompt and pre-selects context (e.g. "Compare" selects
  the two latest versions); it does not auto-send, so the lawyer can edit.

## 4. Composer (spec §7–8)

```
[24 Matter documents ×] [3 selected ×] [Legal research ✓] [Current matter]
┌──────────────────────────────────────────────────────────────────────┐
│ Ask Precentis anything about your matter…                             │
│                                                                      │
│ [📎] [⊕ Add documents] [🔎 Search matter] [⚖ Legal research] [🌐 Web] │
│                                   [🎙] [Model: Legal Reasoning ▾] [↑] │
└──────────────────────────────────────────────────────────────────────┘
```

- **Context chips** reflect exactly what the next message will use; each removable:
  - `24 Matter documents` — retrieval over the whole matter (default when scoped);
  - `3 Selected documents` — restricts retrieval to those documents (click → list with
    ✓ names, remove individually, "3 documents · 142 pages");
  - `Legal research` — include authorities (D8);
  - `Web research` — firm setting on (Q4); sends only the query, never document text; web
    results carry their own "Web" provenance class;
  - `Current matter` / `Firm-wide` — the scope.
- **📎 Add context menu:** Upload document · Select matter documents · Select folder ·
  Add precedent (P4+) · Add legal authority (P7) · Paste text · Connect cloud storage
  (only when sources sync is enabled).
  - Upload from the composer uploads **into the matter** (it's a record, not a
    throwaway attachment) and shows pipeline progress in the chip until indexed; the
    message can be sent once status = indexed.
  - Drag-and-drop files anywhere on the workspace → same flow.
- **Search matter** toggles the retrieval mode that the assistant already uses; it's
  shown for transparency and can be switched off for pure drafting prompts.
- **Model selector:** lists models from `/api/chat/models`, shown by friendly
  capability name ("Legal Reasoning", "Fast") with the model id in a tooltip. Admin
  maps ids → names in settings.
- **Voice:** enabled (Q5), using browser speech recognition. On first use it shows a notice
  that the browser's speech service processes the audio.
- **Keys:** Enter send · Shift+Enter newline · ⌘K palette · `/` opens the Legal AI
  Tools menu inline (slash commands: `/review`, `/extract parties`, `/draft memo` …) ·
  Esc stops generation · ↑ edits the last message.
- Composer grows to 40% of viewport, then scrolls. Draft text is kept per conversation
  (localStorage) so switching conversations doesn't lose it.

## 5. Streaming (spec §25)

Status line above the answer, driven by **server events**, replacing each other:

| Server event (new SSE types) | Shown as |
|---|---|
| `stage: scoping` | "Using 24 matter documents…" / "Using 3 selected documents…" |
| `stage: retrieving` (+count) | "Searching relevant clauses…" |
| `doc_read` (exists) | "Reading Share Purchase Agreement…" |
| `stage: verifying` | "Checking cited provisions…" |
| `text_delta` begins | status fades; text streams |

- Text should stream token-by-token. Today the agent calls the LLM non-streaming and
  emits one delta per round → **backend change** (Bedrock streaming) in 04.
- Stop (Esc / button) keeps the partial answer (works today).
- After completion the status line collapses into "Worked through 5 steps" (expandable
  trail — exists today).

## 6. Response anatomy (spec §9, §26–27)

```
Precentis AI · Legal Reasoning                 [Copy][Regenerate][Save][Share][Export]
─────────────────────────────────────────────────────────────────────────────────────
Key finding (serif, 1–2 sentences)                                      [1][2]

## Termination rights
1. **Material breach** — either party may terminate after a 30-day cure period. [1]
2. **Failure to close** — long-stop date of 31 March… [2]
…
| Right | Trigger | Notice | Exposure |      ← tables render as real tables
> "…material breach which remains uncured for a period of thirty (30) days…"  [1]

Based on 4 matter documents · 2 legal authorities
⚠ 1 statement could not be verified against the available sources.
AI-generated content should be reviewed by a qualified legal professional.
```

- **Header:** "Precentis AI", model capability label, actions:
  - Copy (markdown + citations as footnotes), **Regenerate** (new assistant turn for the
    same user message; previous kept as "version 1/2" switcher), **Save** (to matter
    Notes or Drafts), **Share** (Q6), **Export** (DOCX with footnote citations).
- **Rendering:** headings, numbered/bulleted lists, tables, block quotes for quoted
  clauses, **defined terms** highlighted (terms in quotes-capitalised form that appear in
  a document's definitions block get a subtle underline with hover definition — P4).
  Needs a real Markdown renderer with GFM tables (see 05 for dependency choice).
- **Provenance line (§26):** counts come from the citations actually used, split by
  source class. No confidence numbers.
- **Unsupported claims (§26–27):** the server already verifies quotes
  (`verify_document_citation`). A citation whose quote isn't found renders as a muted
  chip "source not found"; sentences with no citation in a factual paragraph get a thin
  left rule and the footer line "N statements could not be verified…".
- **Four provenance classes (§27)** are visually distinct everywhere (chips, source cards,
  research answers):
  | Class | Marker |
  |---|---|
  | Matter sources (firm documents) | document icon, wine chip |
  | Legal authorities | gavel icon, ink outline chip |
| Web results (Q4) | globe icon, dashed outline chip, domain shown |
  | User-provided (uploaded/pasted in this chat) | paperclip icon, grey chip |
  | AI-generated analysis | no chip; the prose itself, under an "Analysis" heading when mixed |
- Footer disclaimer on every assistant message, small and muted.

## 7. Citations (spec §10–11)

- **Inline chip:** superscript number, subtle (wine text on transparent, underline on
  hover) — not the current filled pill.
- **Hover preview (300ms delay):** document title · page/section (if known) · 2-line
  quote · "View in document →". Keyboard: focusable, Enter opens.
- **Click:** opens the Context panel → **Document** tab at the anchor, highlight pulses
  once; the Sources tab keeps the card selected. On mobile: full-screen viewer.
- **Anchor model:** `{document_id, version_id, block_id, char_start, char_end, page?,
  section?, quote}` (D5). The agent's `quotes[]` are resolved to blocks server-side via
  `resolve-anchor` at citation time, so the client never guesses.
- Citation numbering is per message, contiguous (already enforced by the prompt).

## 8. Context panel (spec §12–13)

Tabs **Sources | Document | Notes**, remembers width and last tab.

- **Sources** — for the selected assistant message (defaults to the latest):
  "12 sources", grouped by class (Matter documents / Authorities / Provided). Card:
  ✓ title, page range or sections cited, click → Document tab. Toggle "Matter sources"
  mode = all matter docs with checkboxes (feeds composer context).
- **Document** — the shared `DocumentViewer` (03, rendering in 06) in panel mode: header with name,
  search, zoom ±, prev/next page (PDF mode) or section (reader), download, open full
  screen, close. Selection toolbar works here (03 §4) and sends to *this* conversation.
- **Notes** — notes attached to the conversation/matter (new): quick add, "Save answer
  to notes", each note links back to the message it came from.

## 9. Research answers (spec §21)

When "Legal research" is on, the response template changes:

1. **Answer** — short direct answer.
2. **Legal position** — explanation.
3. **Relevant authorities** — list of authority cards (case/statute, court·year, 1-line
   holding, Open).
4. **Analysis** — how the authorities apply to the matter documents.
5. **Sources** — citations, split by class.

Implemented as a server-side response mode (system prompt + structured sections), so the
UI renders sections by type rather than parsing prose.

## 10. Legal AI Tools menu (spec §15)

Opened from the composer (`/` or the tools button). Four groups, each item = a
**workflow** the server can run, shown only if available:

- **Review:** Review contract · Identify risks · Find missing clauses · Find unusual
  provisions · Check defined terms · Check cross-references
- **Extract:** Parties · Dates · Obligations · Termination rights · Payment terms ·
  Governing law · Liabilities → runs **tabular review** over selected documents; the
  answer embeds a table preview with "Open as table" (full tabular view, export XLSX —
  endpoint exists).
- **Draft:** Clause · Agreement · Response · Legal memo · Email · Summary → produces a
  draft saved to the matter's Drafts (DOCX export; tracked-changes endpoint exists).
- **Research:** Find authorities · Find similar cases · Search legislation · Search
  regulations · Search precedents → research mode (D8 limits).

Selecting a tool inserts a structured prompt card into the composer ("Extract:
Termination rights · 3 documents") that the user can edit before sending.

## 11. Conversation history (spec §22)

- Rail: search box (server search over titles + first message), grouped Today /
  Yesterday / This week / Month. Filter: this matter / all.
- Item menu: Rename · Move to matter (ACL-checked: member must access target matter) ·
  Share · Archive · Delete. Archived view at the bottom.
- Matter workspace Chat tab shows only that matter's conversations.

## 12. States

| State | Behaviour |
|---|---|
| No model configured | Composer disabled with admin hint (exists) |
| Retrieval returns nothing | Answer says so plainly; suggests selecting documents or widening scope |
| Stream error | Inline error + Retry (exists) |
| Document lost access mid-conversation | Chip turns amber, citation chips to it render "restricted" (no title) |
| Slow first token (>8s) | Status line keeps showing real stage; no spinner loops |
| Long conversation | Virtualised list; history window on server already capped (`chat_history_max_pairs`) |

## 13. Components (spec §32)

`ChatWorkspace`, `ConversationHeader`, `HistoryRail`, `ChatMessage`, `AIResponse`,
`ResponseActions`, `Citation` (+ `CitationPreview`), `ProvenanceLine`, `StageStatus`,
`Composer`, `ContextChips`, `ContextSelector`, `AddContextMenu`, `LegalToolMenu`,
`ModelSelector`, `ContextPanel` (`SourcesTab`, `DocumentTab`, `NotesTab`), `SourceCard`,
`ResearchAnswer`, `AuthorityCard`, `SuggestionCards`, `FileUploader`.

## 14. Acceptance (Playwright, seeded Acme matter)

1. Open Acme workspace → header shows matter, "24 documents" equals API count.
2. Select 3 documents → chip reads "3 Selected documents"; the request carries their ids;
   answer cites only those.
3. Ask the §31 termination question → answer has ≥4 citation chips; clicking [1] opens the
   Document tab scrolled to a highlighted passage whose text contains the citation quote.
4. Hover a chip → preview with title and quote.
5. Stop mid-stream → partial answer saved (exists).
6. Regenerate → "2/2" switcher; both versions persisted.
7. Outsider persona cannot see the restricted matter's conversations or cite its documents.
8. Mobile viewport: citation opens full-screen viewer; back returns to the message.
