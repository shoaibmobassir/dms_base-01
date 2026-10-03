# 08 Frontend audit and change plan

Status: pass 1 implemented on 2026-10-03 (see "Delivery status" at the end). The audit below is the original report.
Date: 2026-10-03. Branch: `fixes-portals`.
Method: read the shell, Home, Ask, Chat (all), Matters, Matter detail, Documents, Clients, People, Arguments, Settings, Calendar (first half), Admin (first third), Document workspace (first 700 lines), Editor page (first 260 lines), and the shared components (primitives, DataTable, QueryState, Inspector, EntityLink, CommandPalette, AIAnswer, AskComposer, KmPanel, DocumentPanelDrawer, MyWork, HistoryPane, ui/button). Then ran greps across all of `src/` for cross-cutting problems and checked the built CSS.

Not read in full (findings on these are marked "verify"): `DocumentViewer.tsx` (pdf.js), `ExactView`, `ReviewPanel`, `PrivacyControl`, `MatterAccessTab`, `ClientIntake`, `MessageParts`, `CitationDocumentPanel`, the second half of `CalendarPage`, `DocumentEditorPage` and `AdminPage`.

Design mode (impeccable): **Operate**. This is a working tool for lawyers and a KM desk. Scanability, consistency and trust outrank expression. Brand lives in precise details (wine accent, DM Serif page titles). The `design-taste-frontend` and `high-end-visual-design` skills are marketing-page skills and are used here only for anti-slop checks, not for layout.

Prior context: `docs/ui-roadmap/00` to `07` and `frontend/DESIGN.md` already set the direction (wine / ink / paper, hairline tables, serif titles). This report does not restart that. It records what is still wrong, what is missing, and what to build next.

---

## 1. Confirmed defects (verified in code or build output)

These are facts, not opinions. Fix first; most are small.

| # | Defect | Evidence | Effect |
|---|---|---|---|
| D1 | Tailwind v4 class names used on a Tailwind v3.4 build: `outline-hidden`, `shadow-2xs`, `shadow-xs`, `rounded-xs`, `rounded-tr-xs`, `backdrop-blur-xs`, `py-0.2` | `package.json` has `tailwindcss ^3.4.17`; the built CSS contains 0 matches for each | Silently no-ops. Composer, search and select inputs show the global `:focus-visible` outline on top of their own focus ring. Chat bubble corner, message card shadow and header blur never render. |
| D2 | `document.title` is never set | grep finds no assignment; `index.html` has a static "Precentis" | Every tab is titled the same. Browser history and screen readers cannot tell pages apart. |
| D3 | Breadcrumb shows raw ids | `Topbar.tsx` `LABELS` has no `edit`; `/ask/:answerId` has no title lookup | `/documents/DOC-1/edit` shows "edit"; `/ask/<uuid>` shows the UUID. |
| D4 | `Icon` drops `aria-label` and `data-testid` | `primitives.tsx` `Icon` takes only `name/className/style` and hardcodes `aria-hidden` | The private/restricted lock icon on Documents has no accessible name and its test id never renders. |
| D5 | DM Serif Display has one weight (400) but is used with `font-bold` / `font-semibold` | `ChatPage.tsx` h1 and EmptyThread h2; font link loads 400 only | Faux bold. Looks smeared. |
| D6 | `.doc-page-body { color: hsl(var(--foreground)) }` while tokens are `oklch()` | `index.css` line 196 | Invalid declaration; editor text colour falls back to inheritance. |
| D7 | Enter-to-send ignores IME composition | no `isComposing` anywhere; `AskComposer` and Chat `Composer` both submit on Enter | Hindi, Chinese or Japanese input commits a half-typed word and sends the question. Matters for an Indian firm. |
| D8 | Chat forces scroll to bottom on every message update | `useLayoutEffect(... scrollTo bottom, [messages])` | A reader who scrolls up while the answer streams is yanked down on every token. |
| D9 | Uploads in Chat file the document into "the first open matter" | `uploadDocument` calls `/api/matters?limit=1` regardless of the conversation's matter | Privilege and confidentiality risk: a client document lands in an unrelated matter. |
| D10 | Documents "Add document" has no file picker | `UploadDialog` is title + matter + pasted text; defaults `target` to the first open matter silently | Lawyers cannot upload a PDF or Word file from the Documents page. Wrong matter is easy to file by accident. |
| D11 | Right rail in the document workspace is `hidden lg:flex` and its toggle `hidden lg:inline-flex`; left rail `hidden md:flex` | `DocumentWorkspace.tsx` | On a phone or small tablet there is no way to reach versions, info, privacy or outline. |
| D12 | Table rows are mouse-only | `DataTable` puts `onClick` on `<tr>`, no `tabIndex`, no link | Keyboard users cannot open a row. No open-in-new-tab, no right-click. |
| D13 | "Ask a follow-up" is a fresh question | `AskComposer` navigates to `/ask?q=` with no reference to the previous answer | The label promises context the system does not carry. |
| D14 | "Clear" in Ask recent questions deletes all history in one click | `deleteAskHistory()` with no confirm | Destructive, no undo. |
| D15 | Filters silently truncate at 200 matters | `useMatters({ limit: 200 })` in Documents filter, upload dialog, Calendar | A firm with more than 200 matters cannot find the rest in these dropdowns. |
| D16 | Single 1.2 MB JS chunk, no route-level code splitting | `static/assets/index-*.js` is 1,223 KB; only the PDF viewer is lazy | Slow first load on firm networks. TipTap, Chat and Admin load for everyone. |
| D17 | Fonts and icon font load from Google CDN | `index.html` | Material Symbols uses `display=block`, so icon names show as text until it loads. A law-firm deployment may block or log third-party requests. |
| D18 | `h-screen` / `100vh` in the app frame and editor | `AppShell`, `ExactView` (`calc(100vh-14rem)`) | iOS Safari address-bar jump; magic offsets break when the header changes height. |

---

## 2. Cross-cutting findings

### 2.1 Visual system
- **Two icon systems.** Material Symbols across pages; lucide in Chat, History, Sheet, Dialog, Command, Dropdown. Mixed stroke weights. Decision: standardise on Material Symbols (90 percent of usage); wrap the few `ui/*` lucide glyphs in a local `Icon` mapping so there is one family.
- **Two citation languages.** Ask uses wine chips; Chat uses amber badges with a dashed border for partial. Same concept, two looks. Decision: one `CitationChip` (wine, dashed border for partial or unverified) used by both.
- **Token bypass.** Hard-coded `amber / emerald / sky / indigo / purple / rose` Tailwind colours appear dozens of times (about 40 distinct uses of amber alone), several with no dark-mode variant (`bg-amber-100 text-amber-900` on Clients status). Add semantic tokens `--info`, `--warning-soft`, `--success-soft`, `--danger-soft` and replace.
- **Type scale.** 86 uses of 9, 10 or 11 px text. Too small for a reading tool. Floor at 12 px for metadata, 13 px for controls, 15 px for body. Keep uppercase tracked labels only for table headers; status labels and eyebrows go sentence case.
- **Template chrome.** An eyebrow above every page title, plus uppercase `meta-label` section headings, plus uppercase status labels with a dot. Cut the eyebrow from list pages (the title says it). Keep it only where it carries information ("Matter", "Client memory").
- **Card discipline.** Matter Overview, MyWork, KmPanel, Admin onboard and Argument detail use bordered cards while the design system says hairlines. Keep cards only where they group a form or an interactive unit.
- **Spacing rhythm.** Pages use `space-y-6`, `8`, `10`, `12` with no rule. Set: directory pages `space-y-6`, record pages `space-y-8`, Home `space-y-10`.
- **Dark mode.** Tokens exist. Gaps: `theme-color` meta is fixed light; chips above; `.doc-page-body` colour (D6); locked-paragraph amber uses raw rgb.

### 2.2 Components
- **`DataTable`**: no sort, no sticky header, no row selection, no keyboard or link semantics (D12), no empty-row skeleton shape. Needs: first cell renders a real `<Link>`, row is focusable, optional sortable columns, optional selection column, sticky header inside scroll containers.
- **`QueryState`**: always shows a table skeleton, even for card or detail pages; 15 places roll their own "Loading…" text. Needs `variant="table|detail|list"` skeletons and one error style.
- **`EmptyState`**: the title is styled as a tiny uppercase eyebrow. Make the title a real sentence; keep the dashed box only for first-run emptiness; for "no results" use a quiet inline line with a "Clear filters" action.
- **Forms**: three different `inputCls` strings, raw `<input>` next to `ui/Input`, placeholders used as labels in every dialog (Upload, New matter, Timeline, Argument, Link). Build `Field` (visible label, hint, error) and `Select`/`Combobox` primitives and migrate dialogs.
- **Native `<select>`**: 33 uses. Fine for short fixed lists (status). Replace with a searchable `Combobox` (cmdk is already installed; `MatterScopePicker` is a working pattern) for matters, people, clients.
- **Tooltips**: 114 `title=` attributes, none reachable by keyboard or touch. `ui/tooltip` exists and is unused. Use it for icon-only buttons; remove `title` where a visible label exists.
- **Hover-only actions** (Arguments and Timeline edit/delete are `opacity-0 group-hover`): invisible on touch. Show them always on touch (`@media (hover: none)`) or move to a row menu.
- **`Pager`**: previous/next only. Add page size and "go to page" when `total` exceeds 5 pages; keep the current page in the URL.
- **State in the URL**: Matter tabs, Admin sections, Arguments selection and all list filters live in `useState`. Refresh, back button and shared links lose them. Move tab, search, status, page and selection into search params (Ask, Chat and Document workspace already do this).

### 2.3 Accessibility baseline
- Skip-to-content link absent; no focus move or live announcement on route change.
- Landmarks: `main` exists; page titles missing (D2).
- Focus: `focus:outline-none` ×7 and the invalid `outline-hidden` (D1). Standardise on one `focus-visible` ring token.
- Touch targets: 20 icon buttons at `p-1` or `p-0.5` (about 20 to 24 px). Minimum 32 px (44 px on touch).
- Motion: reduced-motion handled in CSS. Good.
- Colour: status meaning is carried by colour plus a tiny dot plus uppercase text. Acceptable, but the amber-on-cream warnings need a contrast check.

### 2.4 Performance and delivery
- Route-level `lazy()` for Chat, Editor, Admin, Calendar, Arguments (D16). Target main chunk under 400 KB.
- Self-host Manrope, DM Serif Display, IBM Plex Mono and the icon font (D17); subset Material Symbols to the glyphs used.
- Chat re-parses the whole Markdown on every delta; memoise per message and render only the streaming tail as live.
- Calendar list fetches 390 days at once; fine today, window it when volumes grow.

---

## 3. Feature by feature: how it should be, what changes, where it goes

Format: **Now** (verified) / **Should be** / **Changes** / **Placement**.

### 3.1 App shell, navigation, search
- **Now:** sidebar 220 to 320 px resizable, collapses to 68 px (collapse state is not remembered); two marketing lines in the footer; `Admin` appears first in Manage; topbar has breadcrumbs, search chip with a fixed "⌘K" label, theme menu, user menu; mobile has a 5-item bottom nav (Home, Matters, Assistant, Ask, Documents); toasts sit bottom-right under the bottom nav on phones.
- **Should be:** a shell that makes the two AI surfaces unmistakable and puts "what needs me" one click away.
- **Changes:**
  1. Remember collapsed state. Replace the footer slogans with the signed-in user and a "Help and shortcuts" link.
  2. Keep both **Assistant** (draft, review, edit documents) and **Ask the Firm** (find what the firm already knows). Show the one-line hint under both in the sidebar and under the matching bottom-nav labels' long-press or in the first-run tour. Never call either "Chat" in the UI (route stays `/chat`).
  3. Search chip shows `Ctrl K` on Windows and Linux.
  4. Command palette: add actions (New matter, Add document, New court date, Toggle theme), a "Recent" group, a conversations group, `↵` and `⌘↵` hints, and a `?` cheat sheet of shortcuts.
  5. Toaster offset above the bottom nav on phones. `h-screen` to `h-dvh`.
  6. Breadcrumbs: fix D3; for `/ask/:id` show the question text, for `/documents/:id/edit` show "Edit".
  7. Set `document.title` per route (`Matter title · Precentis`).
  8. Add a notifications entry only when the backend has a feed. `MyWork` already carries deadlines, comments, access requests and conflict checks, so a topbar bell that opens the same data is realistic and cheap.
- **Placement:** `components/shell/*`, one `usePageTitle()` hook in `lib/`.

### 3.2 Sign-in and boot
- **Now:** works for OIDC and dev API key; boot error screen has retry; loading is a line of text.
- **Should be:** same, with the firm name and a branded loading state so a slow API does not look like a blank page.
- **Changes:** skeleton shell during boot; distinguish "server unreachable" (retry) from "no members seeded" (setup message already exists); session-expiry message already handled (keep).
- **Placement:** `AppShell.tsx` (`BootError`, `SignIn`).

### 3.3 Home `/`
- **Now:** title "Firm Intelligence", big Ask composer with four corpus-specific examples, `MyWork` cards, Coming up, Open matters (first 6), right column of recent questions, recent conversations and "In your scope" counters.
- **Should be:** the lawyer's morning view: what is due, what needs a decision, where I left off, then the way into the firm's knowledge.
- **Changes:**
  1. Order: header and compact Ask composer, **Needs you** (overdue first, then due in 7 days, comments, decisions), **Continue** (draft in progress, last conversation), **My matters** (pinned and mine), then recents. Fold "Open matters" and "My matters" into one list with a Mine / Pinned / All switch.
  2. Replace the four static example questions (they name the demo corpus) with server suggestions per member, like Chat's `/suggestions`.
  3. Shrink "In your scope" to one quiet line.
  4. First-run state: when a member has no matters, no deadlines and no history, show a 3-step starter (open a matter, ask a question, upload a document) instead of four empty boxes.
  5. Subtitle "The firm's knowledge, at work." is filler; remove or replace with the date and firm.
- **Placement:** `pages/HomePage.tsx`, `components/home/MyWork.tsx`.

### 3.4 Ask the Firm `/ask`, `/ask/:id`
- **Now:** centred composer when empty; with an answer, a 3-column layout (history, answer, context) that collapses to one column when the document panel opens; streaming phases; saved-answer banner with Refresh; KM panel (matters, documents, people); matter brief; no scope control in the composer; separate mini Markdown renderer.
- **Should be:** a KM desk: ask, see a grounded answer, see exactly which matters, documents and people it rests on, act on it.
- **Changes:**
  1. **Scope control in the composer** (matter or client picker plus "whole firm"), with a removable scope chip. Today scope can only arrive through a URL.
  2. **True follow-up.** Either carry the previous answer id so the backend can use it, or relabel to "Ask another question". Product decision (see section 6).
  3. **Answer actions**: copy with citations, copy link, print or export, "Ask in Assistant" (exists in KM panel; surface it at the answer), thumbs feedback if the backend stores it.
  4. **One Markdown renderer** shared with Chat so numbered lists, tables and bold work in answers (today bold is stripped and `1.` lists render as plain paragraphs).
  5. Show when a saved answer was produced and by whom; "Refresh" stays.
  6. Confirm before "Clear" (D14); add Undo toast instead of a modal if deletion is soft.
  7. IME guard (D7).
  8. Keep the history column only on wide screens; on narrow screens put history behind a "Recent" sheet like Chat.
  9. Plan 19 work is in flight on `AskPage.tsx`, `ask.ts`, `types.ts`, `answers.py`. Coordinate before editing (see section 5).
- **Placement:** `pages/AskPage.tsx`, `components/ai/*`, new shared `components/common/Markdown`.

### 3.5 Assistant (Chat) `/chat`, `/chat/:id`
- **Now:** 1,485-line page; history dock or sheet; thread; composer with attach, work modes (Cite, Reason, Research memo, Risk review), stop, retry, copy, rename, pin, delete; right panel with document and "All sources"; starter cards; matter scope picker; edit proposals, review tables, generated files.
- **Should be:** the drafting workspace. Reliable, calm to read, safe with documents.
- **Changes:**
  1. D8: stick to bottom only when the user is at the bottom; show a "Jump to latest" pill otherwise.
  2. D9: uploads go to the conversation's matter; if there is none, ask which matter before filing (reuse `MatterScopePicker`). Never default silently.
  3. Accept multiple files, drag-and-drop and paste; show per-file progress with cancel (today it polls up to 3 minutes with no cancel).
  4. D5, D1, D7 fixes. Replace amber and multi-colour starter icons with one neutral icon colour.
  5. Sources are shown three times (inline badges, inline "Sources" grid, right panel). Keep inline badges and the right panel; collapse the inline grid behind "Show sources (n)".
  6. Message timestamps; "Export conversation" (docx or pdf); copy as plain text and as text with footnotes.
  7. Mobile: the header packs History, New, title, model, scope and Sources into one row that cannot wrap. Move model and scope into one "Settings" popover under 640 px. Verify at 375 px.
  8. Citation hover preview must also open on keyboard focus and on tap.
  9. Split the file: `ChatThread`, `Composer`, `AssistantMessage`, `EmptyThread`, `ThreadSources`, `DocumentPicker` into their own modules. Behaviour unchanged.
  10. The static line "Reviewing relevant matter documents and statutory precedents…" shows before any step events; use the real step timeline or "Working on it…".
- **Placement:** `pages/ChatPage.tsx` and `components/chat/*`.

### 3.6 Matters list `/matters`
- **Now:** search, All / Open / Closed pills, server pagination, seven columns, New matter gated by permission.
- **Should be:** "my matters first", fast to filter, sortable.
- **Changes:** add **Mine** toggle (default on for fee earners), practice-area filter, sort (newest, next deadline, client), first cell becomes a link, keep the table (no card grid), filters in the URL. Status pills should come from the API's real status set, not a hard-coded three.
- **Placement:** `pages/MattersPage.tsx`.

### 3.7 Matter detail `/matters/:id`
- **Now:** header with title, client, code, status; actions Ask, Assistant, Pin, Edit; underline tabs in local state (Overview, Documents, Timeline, Deadlines, People, Arguments, Related, Access); Overview is boxed facts and parties.
- **Should be:** the workspace for one matter, shareable by link.
- **Changes:**
  1. Tab in the URL (`?tab=documents`).
  2. Overview: add next deadline, document count, last activity, and an AI summary only if it is generated once, cached and cited. Drop the boxed cards for hairline sections.
  3. Documents tab: **Add document here** (matter pre-selected), pagination beyond 200, same columns as the Documents page.
  4. Deadlines tab: **Add court date** (Calendar's `CreateDialog` with the matter pre-filled).
  5. Actions: group Ask and Assistant as the primary pair; move Pin and Edit into a secondary menu on narrow screens.
  6. Timeline: group by year, link entries to documents (exists), allow filtering by source.
  7. Hover-only Edit and Delete become visible on touch; confirm deletes (verify whether `useDeleteArgument` and `useDeleteTimelineEntry` already confirm).
- **Placement:** `pages/MatterDetailPage.tsx`, `components/matter/MatterEditors.tsx`.

### 3.8 Documents `/documents`
- **Now:** search, type and matter native selects, five-column table, privacy icon, paste-text "Add document".
- **Should be:** the firm's document library: upload real files, find by anything, act on several at once.
- **Changes:**
  1. D10: replace the dialog with a real **upload flow**: drag-and-drop or picker for multiple PDF, DOCX, TXT; required matter chosen from a searchable picker (no silent default); document type per file; private-draft option kept; per-file progress using the existing `/api/uploads/batches` API; errors per file. Keep "paste text" as a secondary tab.
  2. Sort by date, title, matter; sticky header; row selection with bulk **Open in Assistant** (attach many), **Move to matter** (if permitted), **Download**.
  3. Quick peek: row action opens the Inspector preview without leaving the list (Inspector already has document peek).
  4. Folders or library view is plan 09; keep it out of this pass but leave room for a left filter rail.
  5. D4 fix for the privacy icon with a visible text label on hover and for screen readers.
  6. Matter filter becomes a searchable combobox (D15).
- **Placement:** `pages/DocumentsPage.tsx`, new `components/documents/UploadFlow.tsx`.

### 3.9 Document workspace `/documents/:id`
- **Now:** toolbar with title, version chip, page nav, privacy, Edit; left outline or page list; reader canvas in "Parts" of five blocks when no page rendition exists ("Reader · no page rendition yet" is shown to users); right rail Versions, Info, AI (two links); global arrow-key page turning.
- **Should be:** a calm reader with search, versions and a real AI hand-off, usable on a tablet.
- **Changes:**
  1. D11: rails become drawers under `lg` (outline and versions via a bottom or side sheet) with visible toggle buttons.
  2. **Search in document** across all parts (today the browser's Ctrl+F only sees the current five blocks).
  3. Rename "Part" and hide the "no page rendition yet" message from users; show "Text view" with a link "Why no pages?" or nothing.
  4. AI tab becomes real: "Summarise", "List obligations", "Find clause…" start an Assistant conversation with this document attached (today `/chat?matter=` does not attach the document).
  5. Keyboard: do not intercept arrow keys when a menu, dialog or selection exists; keep `g`, Home, End, PageUp, PageDown.
  6. Download original, copy citation, print.
  7. "Edit" only when the document is editable and the user can edit (verify current gating).
  8. Verify the PDF viewer (`DocumentViewer.tsx`): zoom, fit width, text selection, copy, find, page jump at 375 px.
- **Placement:** `components/document-workspace/DocumentWorkspace.tsx` (split into Toolbar, Rails, Reader modules), `components/viewer/*`.

### 3.10 Document editor `/documents/:id/edit`
- **Now:** TipTap with paragraph ids, locks, autosave drafts, comments, review mode, exact (PDF) view, upload new version.
- **Should be:** same behaviour with predictable layout.
- **Changes:** replace `h-[calc(100vh-14rem)]` with flex and `dvh` (D18); save state always visible (idle, saving, saved, error); explicit conflict dialog wording; unsaved-changes guard on navigation (verify); toolbar buttons get labels or tooltips; reviewer colours come from tokens not a hex list.
- **Placement:** `pages/DocumentEditorPage.tsx`, `components/editor/*`. Only the first 260 lines were read: audit the rest before editing.

### 3.11 Clients, Client detail
- **Now:** search, table, conflict queue for deciders, client memory notes grouped by Prefers, Avoid, Terms, matters in scope.
- **Should be:** the relationship view.
- **Changes:** add "New matter for this client", edit client details (permission-gated), show open and total matters in the header, status chip tokens (no raw amber), link note source matters. First column becomes a link.
- **Placement:** `pages/ClientsPage.tsx`, `pages/ClientDetailPage.tsx`.

### 3.12 People, Person detail
- **Now:** whole directory loaded, search and practice pills, table; person page lists their matters; own expertise editable.
- **Should be:** find the right colleague.
- **Changes:** show current open-matter load (exists), office, languages and expertise; "Ask the firm who has handled X" link; keep "Edit my expertise". Add `mailto:` or copy for contact if emails are available.
- **Placement:** `pages/PeoplePage.tsx`, `pages/PersonDetailPage.tsx`.

### 3.13 Calendar `/calendar`
- **Now:** list, week and month views; scope Mine, My team, Matter, Firm; status pills; unconfirmed court-date warning; item dialog; create event or court date; ICS subscribe.
- **Should be:** reliable for court dates.
- **Changes:** default scope **Mine** (today default is Firm); matter filter becomes a combobox (D15); "Today" marker and auto-scroll in list view; keep unconfirmed warning but replace the "⚠" glyph with an icon; month grid at 375 px must switch to an agenda list; time zone shown on timed items. Verify the unread half of the file.
- **Placement:** `pages/CalendarPage.tsx`.

### 3.14 Arguments `/arguments`
- **Now:** search, kind pills with counts, master list (360 px) and detail pane.
- **Should be:** a research list that works on a phone.
- **Changes:** selection in the URL; on narrow screens, tapping an item opens the detail as a full-screen sheet (today the detail sits below a long list); show a snippet under each issue; "Ask the Firm about this argument" stays.
- **Placement:** `pages/ArgumentsPage.tsx`.

### 3.15 Settings `/settings`
- **Now:** profile, persona switcher (dev), appearance, firm, teams table, system info (retrieval engine, index version, feature keys) visible to everyone.
- **Should be:** personal preferences first; deployment details only for admins.
- **Changes:** show **System** only to administrators; add default Ask scope, answer detail level, keyboard shortcuts list, "Clear my Ask history" with confirm, sessions and sign-out; move Teams to Admin (it duplicates Admin Teams); render feature flags as readable labels.
- **Placement:** `pages/SettingsPage.tsx`.

### 3.16 Admin `/admin`
- **Now:** four tabs in local state, raw `<table>`, plain "Loading…", native inputs.
- **Should be:** an audited control panel.
- **Changes:** use `DataTable`, `Field`, `Combobox`; sections in the URL; confirm destructive actions (delete team, remove role); show who changed what last (audit view for people with `audit.read`). Read the remaining two thirds before editing.
- **Placement:** `pages/AdminPage.tsx`.

### 3.17 Entity inspector, access, restricted matters
- **Now:** right sheet peeks for matter, person, client, document; locked matter page with request-access flow.
- **Should be:** same, with consistent loading and an obvious "Open full record".
- **Changes:** replace the four `Loading…` strings with the detail skeleton; the restricted state must never confirm existence beyond what the API already allows (keep the 404 to locked-page behaviour).
- **Placement:** `components/common/Inspector.tsx`, `components/access/*`.

---

## 4. Scenario matrix (what must be checked for every changed screen)

| Scenario | What to verify |
|---|---|
| New firm, no data | Every page has a first-run empty state with the next action; no page is blank. |
| Member with read-only access | Create, edit, delete and upload controls are hidden or disabled with a reason. |
| Restricted or walled matter | 404 turns into the locked page; no title or count leaks in lists, search, Ask panel, calendar or inspector. |
| Private draft document | Lock icon with text, hidden from others' lists, not attachable by others in Chat. |
| Very long titles, long client names, long matter codes | Truncate with title text; tables do not overflow; Arabic, Hindi and Chinese text wraps. |
| 5 results, 500 results, 50,000 documents | Skeleton matches shape; pagination; no 200-item dropdowns; search is server-side. |
| Slow API, API down, 401 mid-session | Skeletons then error with retry; session end returns to sign-in without losing editor drafts. |
| Two people edit one document | Lock holder shown; read-only fallback; clear conflict dialog. |
| Upload: wrong type, 0 bytes, 100 MB, duplicate, indexing fails, user navigates away | Per-file error with reason; cancel; progress survives navigation or warns. |
| Streaming answer: user scrolls, stops, loses network, switches persona | No scroll hijack; partial answer saved; abort on persona change (exists). |
| Keyboard only | Tab order, visible focus, rows open with Enter, dialogs trap and restore focus, command palette reachable. |
| Screen reader | Page title per route, landmarks, icon buttons named, status not colour only. |
| Touch and 375 px | 44 px targets, no hover-only actions, rails become drawers, tables scroll or collapse, bottom nav does not hide content. |
| Dark mode and `prefers-reduced-motion` | Tokens only, no raw colours; animations off. |
| IME input (Hindi, Japanese) | Enter during composition does not submit. |
| Multi-tab | Live updates (SSE) refresh lists; no stale deletes. |

---

## 5. Delivery plan

Order is by risk and leverage. Each phase ends with `tsc`, `vite build`, the existing Playwright specs (`e2e/*`) and a manual pass at 1440, 1024, 768 and 375 px in light and dark. Keep every existing `data-testid`.

**In-flight work to avoid colliding with.** The working tree already has uncommitted changes to `AskPage.tsx`, `App.tsx`, `AppShell.tsx`, `ask.ts`, `types.ts`, `AskPage` e2e and backend `answers.py` (plan 19, stored answers). Do not touch those files until that work is committed or the owner confirms.

| Phase | Scope | Size |
|---|---|---|
| **P0 Safety and correctness** | D9 (upload misfile), D10 (real upload flow, no silent matter), D7 (IME), D8 (scroll), D14 (confirm clear), D13 (relabel or wire follow-up), D15 (searchable pickers) | Medium |
| **P1 Foundation** | D1 (Tailwind v3 class cleanup), D5, D6, D17 (self-host fonts), D2 and D3 (titles, breadcrumbs), D4 (`Icon` props), D18, tokens for semantic colours, `Field`, `Combobox`, `Select`, one `CitationChip`, one `Markdown`, one icon family | Medium |
| **P2 Tables and lists** | `DataTable` links, keyboard, sort, sticky header, selection; `QueryState` skeleton variants; `EmptyState` redo; URL-backed filters, tabs, pages; Matters "Mine" | Medium |
| **P3 Mobile and documents** | D11 drawers, Arguments detail sheet, Chat header on 375 px, Calendar agenda on phones, in-document search, doc AI tab that attaches the document | Medium |
| **P4 Home and shell** | New Home order, server suggestions, first-run state, command palette actions, shortcuts sheet, notifications bell backed by `MyWork`, sidebar footer | Small to medium |
| **P5 Performance** | D16 route-level lazy loading, Markdown memoisation, Material Symbols subset | Small |
| **P6 Records and admin** | Matter overview, add-document and add-court-date inside a matter, client and person actions, Settings and Admin tidy-up | Medium |
| **P7 Chat module split** | Split `ChatPage.tsx` into modules with no behaviour change; add export and timestamps | Medium |

Do not retune retrieval or the backend except where a feature above needs an endpoint (follow-up context, suggestions, notifications). Record any backend need in `04_BACKEND_GAPS.md`.

---

## 6. Decisions needed from you

1. **Ask follow-up**: make it a real follow-up (carry the previous answer to the backend) or relabel it "Ask another question"?
2. **Home**: is "Needs you" (due, comments, decisions) the right first block, or should the Ask composer stay the first thing a lawyer sees?
3. **Icons**: standardise on Material Symbols (recommended, least churn) or move to Phosphor?
4. **Upload default matter**: require the user to pick a matter every time (recommended) or default to the matter in context only?
5. **Admin-only System info in Settings**: confirm that ordinary members should not see retrieval engine and index version.
6. **Phase order**: start with P0 and P1 (recommended), or a different priority?

---

## 7. Impeccable follow-up

`PRODUCT.md` and `DESIGN.md` at the repo root level do not exist; `frontend/DESIGN.md` is a short token note. After approval, run `/impeccable init` to capture product context (users: fee earners, KM staff, partners, administrators; mode: Operate; tone: precise, calm, trustworthy), then `/impeccable document` to regenerate a full `DESIGN.md` from the shipped code. Use `/impeccable audit` and `/impeccable critique` after P1 and P3 as the check on the work.

---

## 8. Delivery status (2026-10-03)

Decisions taken (PM and design call, since the owner delegated them): follow-ups are real (backend carries the earlier
answer); Home keeps the composer first with "My work" directly below; Material Symbols stays as the one icon family;
uploads always require a matter; System info is administrator-only; P0 and P1 first.

**Done:** D1 to D18 except D5 (done), D13 (done, real follow-up), D16 (done), D17 (done). Also: MatterPicker, UploadFlow,
Confirm dialog, semantic tokens, DataTable links and keyboard, matter tab in URL, add document and court date inside a
matter, Assistant hand-off from the reader, drawers for the reader rails, shortcut list, palette actions, DetailSkeleton,
EmptyState title, question ideas from real matters, sidebar footer replaced.

**Pass 2 (2026-10-03):** Ask now renders answers with the Assistant's Markdown (lists, tables, bold) and both use one
citation chip (`components/common/citation.ts`); answer actions (copy with sources, copy link, continue in the
Assistant); find in document (`/` or the search button; `GET /api/documents/{id}/versions/{vid}/search`); Arguments detail
as a sheet on phones with the record in the URL; Calendar month becomes an agenda on phones; event delete asks first;
matter Overview rebuilt without cards (documents and deadlines at a glance, coming up, hairline sections); Home shows a
first-run state and "Needs your attention".

**Pass 3 (2026-10-03):** `Field`, `SearchPicker`, `MatterPicker`, `ClientPicker` primitives; matter dialogs (open, edit,
timeline, argument, link), the Calendar create dialog and Admin "Add a person" now have visible labels, and **a new matter no
longer defaults to the first client** (a second silent default, found while migrating); notifications bell (reads the same
data as Home); `ChatPage.tsx` split from 1,567 to 704 lines (`ThreadSources`, `EmptyThread`, `AssistantMessage`, `Composer`,
`DocumentPicker`, `MatterForUpload`, `citationText`, `chatTypes`) with no behaviour change; conversation download (Markdown)
and message times. PDF viewer read: zoom, fit width and page, resize-aware, page jump are in place; missing are download
and search inside the PDF itself.

**Pass 4 (branch `new_frontend_v2`):** server-side sorting (`sort`, `dir`) on the matters and documents lists with a
whitelist (`app/api/sorting.py`), sortable headers in `DataTable` (`aria-sort`), "My matters" filter (`mine=true`), sort,
status and mine kept in the URL; Admin people table on `DataTable` with skeletons; "Download" of the original file from the
reader (audited by the existing endpoint).

**Pass 5:** row selection in `DataTable` and `BulkBar`; Documents bulk actions (work on several in the Assistant, download
several); conversation export to Word (`GET /api/chat/sessions/{id}/export.docx`, `app/chat/export.py`) and Markdown;
find inside the PDF viewer (next or previous page with the phrase); review of `MessageParts`, `ExactView`, `ReviewPanel`:
confirm before accepting or rejecting several tracked changes at once and before deleting a comment, "Apply to Word" wording,
token colours, `dvh` heights.

**Not done yet:** `/impeccable init` and a generated `DESIGN.md` (needs a short product interview); bulk actions on other
lists (matters have none that fit yet); a count of matches inside a PDF (it jumps page to page).
