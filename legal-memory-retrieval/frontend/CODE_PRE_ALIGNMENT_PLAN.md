# FirmOS UI alignment — match `code_pre` exactly

**Status:** plan only. Do not implement until this file is approved.  
**Baseline:** `/Users/shoaibmobassir/Desktop/Experiments/Legal_Maal /app/code_pre/frontend`  
**Target:** `legal-memory-retrieval/frontend`  
**Rule:** copy layout, spacing, and interaction from `code_pre`. Keep our live APIs and Apex Chambers brand. Do not invent a second dashboard style.

---

## 1. Why the current UI looks broken

The shell (sidebar, topbar, tokens, fonts) was ported. The **pages were redesigned**. That is the gap.

| What `code_pre` does | What we shipped instead |
|---|---|
| Editorial serif titles (`Firm Intelligence`, `All institutional knowledge begins with the matter.`) | SaaS dashboard titles (`Good morning, Counsel.`, `Matters`) |
| `AskComposer` (serif textarea, filter pills, scope select, “Try asking” rows) on Home, Ask, Knowledge, Matter | Custom card CTA + boxed textarea + debug checkbox on Ask; Home has no composer |
| Ask answer is a **3-column** layout: session list / `AIAnswer` / `AnswerContext` | Single column card with debug dump |
| Lists are a **naked** `DataTable` (hairline rows, mono ids, entity links) | Tables wrapped in `rounded-lg border bg-card p-2` plus colored bars |
| Search is a full-width bordered row + **pill filters** | Small `Input` + `<select>` |
| Matter detail: sticky **underline tabs** (Overview, Matter DNA, Documents, Timeline, People, Arguments, Precedents, Drafts, Emails, Knowledge, Audit) and a row of `Action` buttons | Radix `Tabs` with a subset of panels and a breadcrumb |
| Knowledge is a **hub of 6 cards** plus composer | A data tab of API lists |
| Vertical rhythm `space-y-8` / `space-y-12`, no extra card chrome | `space-y-6` plus nested cards, so spacing stacks and feels cramped |
| Inspector peeks entities from the same dataset the page uses | `AppShell` still looks up `@/data/mock`, while pages read the API — peek and page disagree |

Result: wine/paper colors are present, but density, hierarchy, and page logic do not match the baseline. Several surfaces also feel empty because the layout that made mock data readable was thrown away.

---

## 2. Non-negotiable layout contract

Taken from `code_pre` `AppShell`, `index.css`, and the page files. Do not restyle these while aligning pages.

**Shell**

- Sidebar 256px / collapsed 68px, paper background, wine active bar (3px), meta-label group headings.
- Topbar 52px, breadcrumbs, search chip with ⌘K, notifications, persona menu.
- Main: `max-w-[1180px] px-6 py-8 lg:px-10 lg:py-10`. Pages must **not** add a second max-width or outer card.
- Content fade on route change (`animate-fade`).

**Typography**

- Page title: `font-display` via `PageHeader` (already `text-4xl` / `sm:text-5xl`).
- Eyebrow / section labels: `.eyebrow` and `.meta-label` (11px, tracked uppercase).
- IDs: `.font-mono-id`.
- Ask textarea: `font-display text-xl`.

**Spacing**

- Home and Knowledge: `space-y-10` or `space-y-12`.
- Directory pages (matters, documents, people, clients): `space-y-8`.
- Section grids: `gap-12` on Home (2/3 + 1/3), not `gap-4` stat tiles.
- Tables: no wrapping card. Row padding comes from `DataTable` (`py-3`, hairline `border-b`).
- Matter tabs: sticky bar `-mx-6 px-6 lg:-mx-10 lg:px-10`, underline `h-0.5 bg-wine`, not a pill `TabsList`.

**Components to reuse (already in tree)**

- `PageHeader`, `Action`, `SectionLabel`, `StatusLabel`, `Hairline`, `EmptyState`, `Icon`, `MonoId`, `Chip`
- `DataTable`, `EntityLink` (`MatterLink`, `ClientLink`, `PersonLink`)
- `AskComposer`, `AIAnswer`, `AnswerContext`, `AIAssembling`
- `Inspector`, `KnowledgeGraph`
- Dialog only for create/upload, matching `code_pre` dialogs

**Do not use on aligned pages**

- Stat-card grids as the home hero
- Extra bordered sections around tables
- Radix `Tabs` where `code_pre` uses an underline button strip
- Generic “Coming soon” empty states on routes that have a full `code_pre` layout

---

## 3. Data rule (layout from baseline, rows from our API)

`code_pre` is mock-only. We keep `apiFetch` + `X-Member-Id`.

Map fields, do not fake Mason & Partners entities:

| UI column | API field |
|---|---|
| Matter id / code | `matter_code` or `matter_id` |
| Matter name | `title` |
| Client | `client_name` / `client_id` |
| Practice | `practice_area` |
| Status | `status` (show the API string; do not invent “Needs review” if the corpus has no such value) |
| Document name | `title` |
| Document type / author / date | `document_type`, `author_name`, `doc_date` |
| Person | `name`, `role`, `office`, `member_id` |

**Inspector:** stop reading `@/data/mock` in `AppShell`. Build `EntityLookup` from `useApp()` lists (matters, documents, clients, people) plus the detail already loaded. If an id is missing, inspector shows “Not in your access scope.”

**Ask:** `AskComposer` navigates to `/ask?q=…`. `AskPage` reads `q` from the URL, calls `POST /api/answers`, maps citations into `AIAnswer`, and opens `SourceViewer` on citation click. Keep optional debug behind `?debug=1`, not as a default checkbox.

**Empty states:** use `code_pre` copy pattern (“No matters match your search within your current access scope.”) when the API returns zero rows. Do not show mock rows.

**Preview routes** (no product API): rebuild the `code_pre` page structure with live data where a nearby API exists (e.g. similar matters from `/api/matters/{id}/related` when a matter is selected; deadlines from `/api/tasks`). Where there is truly no API, render the same layout with an honest empty table — not a “Coming soon” card and not invented success metrics.

---

## 4. Page-by-page execution

Each step: open the named `code_pre` file, rebuild our page to that structure, bind the API fields above, then check spacing against the contract in §2.

### Phase A — Fix the shared frame (breaks first)

1. **`AppShell.tsx`** — remove `mock` lookup. Wire inspector to firm context.
2. **`AskComposer.tsx`** — confirm it matches `code_pre` (scope select, filter pills, serif textarea, example rows). Home and Ask must use this component, not a one-off form.
3. **`Sidebar.tsx`** — keep Chat, Projects, Activity in Workspace (product extras). Everything else stays in the `code_pre` group order. Drafts link goes to `/documents` (no fake `DOC-93821`).
4. **List chrome** — delete the `rounded-lg border bg-card p-2` wrapper around `DataTable` on directory pages.

### Phase B — Primary screens (what the user sees first)

| Our file | Match this `code_pre` file | Must include |
|---|---|---|
| `HomePage.tsx` | `pages/Home.jsx` | Title “Firm Intelligence”; greeting in eyebrow only; two `Action`s (Ask the Firm, Browse Matters); `AskComposer` with example questions from a short static list (not mock firm names); left `DataTable` of recent matters; right “Recently surfaced knowledge” counts from `GET /api/home/stats`; “The product loop” hairline block. Remove stat tiles and the “What would you like to know?” card. |
| `AskPage.tsx` | `pages/Ask.jsx` | Empty state: centered `Eyebrow` + `text-5xl` question + `AskComposer large`. With `?q=`: grid `lg:grid-cols-[220px_minmax(0,1fr)_300px]`; session history; `PageHeader` title = the question; `AIAnswer`; follow-up composer; `AnswerContext` on the right. Loading uses `AIAssembling`. |
| `MattersPage.tsx` | `pages/Matters.jsx` | Editorial title; search row + status pills; table columns Matter / Client / Practice / Lead / Team / Status / Last activity; row click → detail. Create-matter dialog only if `POST` exists; otherwise omit the button (do not toast a fake create). |
| `MatterDetailPage.tsx` | `pages/MatterDetail.jsx` | Header: client as title, matter name as subtitle, action row (Ask about this matter, Open documents, timeline, similar, handover). Sticky underline tabs. Overview uses the same two-column blocks (key facts, ask composer scoped to the matter). Documents / Timeline / People / Arguments tabs bind existing matter APIs. Tabs with no API (Emails, Drafts, Audit) use the `code_pre` empty layout, not a blank Radix panel. Matter DNA uses `KnowledgeGraph` fed by `GET /api/matters/{id}/graph` when that route returns nodes; otherwise the same graph component with the matter + its documents/people as nodes. |
| `DocumentsPage.tsx` | `pages/Documents.jsx` | Title “Documents are the firm's evidence.”; full-width search; columns Name / Type / Author / Matter / Version / Date; upload dialog calls existing ingest if present, otherwise the dialog explains ingest is unavailable (no fake stages that claim success). |
| `DocumentDetailPage.tsx` | `pages/DocumentViewer.jsx` | Same header, section list, and side meta. Body text from `GET /api/documents/{id}/text`. |
| `DocumentHistoryPage.tsx` | `pages/DocumentHistory.jsx` | Version list + diff from versions API. Same vertical timeline spacing. |
| `KnowledgePage.tsx` | `pages/Knowledge.jsx` | Hub cards + composer. Child routes `/precedents` and `/arguments` are real pages (stop redirecting them into the hub) and match `Precedents.jsx` / `ArgumentsPage.jsx`, filled from `/api/knowledge/precedents` and `/api/knowledge/arguments`. |
| `ClientsPage.tsx` + `ClientDetailPage.tsx` | `Clients.jsx` + `ClientDetail.jsx` | List table, then detail with matters for that client. |
| `PeoplePage.tsx` + `PersonDetailPage.tsx` | `People.jsx` + `PersonDetail.jsx` | Directory table, then profile sections. |
| `SettingsPage.tsx` | `Settings.jsx` | Same section stack (firm, retrieval, persona). Persona control stays wired to `X-Member-Id`. System info from `/api/system/info` fills the retrieval block; do not add a new settings API. |

### Phase C — Rest of the IA (same files, same spacing)

Rebuild each of these to the matching `code_pre` page. Prefer live rows; otherwise the baseline empty/table layout.

| Ours | Baseline |
|---|---|
| `DeadlinesPage.tsx` | `Deadlines.jsx` — rows from `/api/tasks` |
| `TeamsPage.tsx` | `Teams.jsx` — rows from `/api/teams` |
| `DataSourcesPage.tsx` | `DataSources.jsx` — connections from `/api/sources` |
| `ActivityPage.tsx` | closest visual: `Audit.jsx` timeline, data from `/api/activity` |
| `SimilarMattersPage.tsx` | `SimilarMatters.jsx` |
| `PrecedentsPage.tsx` | `Precedents.jsx` |
| `ArgumentsPage.tsx` | `ArgumentsPage.jsx` |
| `StrategyPage.tsx` | `Strategy.jsx` |
| `ExperiencePage.tsx` | `Experience.jsx` |
| `KnowledgeGapsPage.tsx` | `KnowledgeGaps.jsx` |
| `DueDiligencePage.tsx` | `DueDiligence.jsx` |
| `TimelinesPage.tsx` | `Timelines.jsx` |
| `StaffingPage.tsx` | `Staffing.jsx` |
| `TransitionsPage.tsx` | `Transitions.jsx` |
| `KnowledgeManagementPage.tsx` | `KnowledgeManagement.jsx` |
| `AuditPage.tsx` | `Audit.jsx` |
| `PermissionsPage.tsx` | `Permissions.jsx` |

Chat and Projects stay, because they are product surfaces `code_pre` does not have. Restyle them with the same contract: `PageHeader`, `space-y-8`, `DataTable` or hairline lists, `Action` buttons, no extra dashboard cards. Chat transcript uses the Ask answer typography (`text-[17px] leading-relaxed`), not a chat-bubble theme.

### Phase D — Spacing and logic pass

After pages match structure, walk these checks. Fix only deviations.

1. No page uses both a card grid **and** a table for the same list.
2. Search inputs are full width of the content column (`flex-1` inside a bordered row), not `max-w-sm`, except where `code_pre` is narrower.
3. Filter controls are pills, not native `<select>`, except the Ask scope `<select>` inside the composer.
4. `StatusLabel` receives the raw status string. Add styles only for statuses the API actually returns (`open`, `active`, `closed`, and title case variants).
5. Entity names that have an id are `EntityLink` buttons (inspector), not plain text.
6. Ask, Home, Knowledge, and Matter overview all submit through `AskComposer`.
7. Citation click opens `SourceViewer` with `document_id` + `chunk_id`.
8. Mobile: sidebar sheet still works; matter tab strip scrolls horizontally; Ask right column hides below `lg` (same as baseline).

---

## 5. Execution order

1. Phase A (shell + composer + inspector). One PR-sized change. Build must stay green.
2. Phase B in this order: Home → Ask → Matters → Matter detail → Documents → Document detail/history → Knowledge + precedents/arguments → Clients → People → Settings.
3. Phase C, one page at a time, comparing side by side with the `code_pre` file.
4. Phase D checklist.
5. `npm run build` into `static/`. Smoke on `/ui`: Home composer, Ask with a real question and a citation, matter tab strip, document table, ⌘K, mobile nav.

Do not retune retrieval, schema, or fusion. Do not add Mike code. Do not add Emergent/PostHog.

---

## 6. Done when

- Home, Ask, Matters, Matter detail, and Documents are recognisable as the `code_pre` screens with Apex data in the rows.
- Ask empty state is the centered serif composer, not a form card.
- Tables are hairline lists, not boxed grids.
- Matter detail uses the underline tab strip and the action row.
- Inspector uses API entities, not `data/mock`.
- Spacing matches §2 on those five screens at desktop width.
- Remaining IA routes use the baseline page structure (no “Coming soon” stand-in).
