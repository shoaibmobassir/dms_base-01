# 01 — Page-by-page audit

For each page: **code_pre** (reference design, mock data) · **Today** (our API-wired
frontend after the production plan) · **Target** · **Verdict** · **Data** (what the API
has / needs — detail in `04_BACKEND_GAPS.md`).

Legend: ✅ keep as is · ♻️ restyle/extend · 🔀 merge · 🆕 new · ❌ stays removed

---

## Shell

### Sidebar
- **code_pre:** 256/68px collapsible, paper background, wine 3px active bar, grouped nav
  (Workspace / Intelligence / Workflows / Manage), firm switcher, trust footer.
- **Today:** same visual, pruned to 11 wired items; firm identity from API.
- **Target:** Precentis mark at top; **workspace (firm) switcher**; a **matter selector**
  (recent + pinned matters, search) because the product is matter-centric; groups:
  - *Work*: Home, Chat, Matters, Documents, Calendar, Research
  - *Knowledge*: Arguments, Clients, People
  - *Manage*: Settings (Teams moves inside)
  - Below groups: **Pinned matters**, then **Recent conversations** (last 5).
  (Decision Q7 in `00_ROADMAP.md` §5.)
  Resizable width (drag edge, 220–320px, remembered per browser).
- **Verdict:** ♻️. Deadlines is renamed **Calendar** and stays in the nav (Q7).
- **Data:** matters list (exists), chat sessions (exists).

### Topbar
- **code_pre:** breadcrumbs, search chip ⌘K, notifications bell, help, persona menu.
- **Today:** breadcrumbs (real firm), search chip, user/persona menu. Bell removed (was fake).
- **Target:** breadcrumbs `Matters / Acme Acquisition`; search chip "Search Precentis ⌘K";
  **theme toggle** (light/dark/system); user menu. Notifications return only when there
  is a real feed (deadline reminders, review requests) — P3+.
- **Verdict:** ♻️.

### Command palette / global search (⌘K)
- **code_pre:** static lists from mock (navigate, matters, docs, people).
- **Today:** server search (matters, documents, clients, people) + "Ask the Firm: …".
- **Target (spec §23–24):** two modes in one dialog:
  1. *Commands* (empty input): New chat, New matter, Upload document, Legal research,
     Open documents, Open recent matter, Settings, Toggle theme.
  2. *Search* (typing): results grouped **Matters · Documents · Conversations ·
     Authorities · Notes**, each row with type icon + secondary line; ↵ opens, ⌘↵ "Ask
     about this".
- **Verdict:** ♻️. **Data:** extend `/api/search` with conversations (own sessions only),
  notes and authorities.

### Inspector (entity peek sheet)
- **Today:** fetches matter/person/client/document on open.
- **Target:** keep for People/Clients/Matters peeks from tables. **Documents no longer
  open in the Inspector** — they open in the context panel (chat) or the viewer page.
- **Verdict:** ✅ (narrowed).

### Mobile
- **code_pre / Today:** sidebar in a sheet; no bottom nav.
- **Target (spec §29):** bottom nav Home · Matters · Chat · Documents · Profile; chat
  single column; context panel and viewer open full-screen. Tablet: 2 columns, context
  panel as drawer.
- **Verdict:** 🆕.

---

## Home — `/`
- **code_pre:** "Good morning" + Firm Intelligence title, AskComposer with examples,
  recently active matters table, knowledge snapshot counters, "product loop" card.
- **Today:** same layout; open matters, upcoming deadlines, in-scope counters from API.
  The "product loop" card was removed (decorative).
- **Target:** keep the editorial header. Composer **starts a chat** (D1) with a scope
  chip (Firm-wide / pick matter). Below, three columns of real work:
  - *Continue* — last 4 conversations (title, matter, time) → resume.
  - *Your matters* — pinned/recent matters with doc count and next deadline.
  - *Coming up* — next 5 deadlines.
  Counters shrink to one quiet line ("168 matters · 3,103 documents in your scope").
- **Verdict:** ♻️. **Data:** exists except "pinned matters" (new, per-member).

## Chat — `/chat`, `/chat/:id`, matter chat `/matters/:id/chat/:chatId`
- **code_pre:** no chat page (only Ask).
- **Today:** 2-column (history rail + thread), stop/retry/copy/rename/delete, steps
  trail, citations list, suggestions from open matters.
- **Target:** the full AI workspace — see **`02_CHAT_WORKSPACE.md`**.
- **Verdict:** ♻️ major (P1).

## Ask the Firm — `/ask`
- **code_pre:** 3 columns: session list · answer (serif first paragraph, citation chips,
  feedback pills, "how this answer was assembled") · context (matters, people, timeline,
  grounding).
- **Today:** same 3 columns with real `/api/answers`; fake feedback and fake trace removed.
- **Target:** 🔀 **merged into Chat** (D1). What survives from Ask into the chat response:
  the serif lead sentence (key finding), the "Based on …" provenance line, and the
  right-hand context column (becomes the Sources tab). `/ask?q=…` → creates a firm-scope
  chat and sends `q`.
- **Verdict:** 🔀 (Q1).

## Matters — `/matters`
- **code_pre:** title "All institutional knowledge begins with the matter.", **Create
  matter** dialog, search + status pills, table with lead partner, team, last activity.
- **Today:** search + Open/Closed pills, server pagination, restricted marker. No create.
- **Target:** add **Lead partner** and **Last activity** columns (both derivable), a
  **card/table toggle** (MatterCard from spec §32 for the pinned/recent view), practice
  filter, and **Create matter** (real endpoint; confidentiality choice sets
  `permissions.restricted` + team). Row action "Open workspace".
- **Verdict:** ♻️. **Data:** lead = `matter_members` role Lead (exists); last activity =
  max(doc date, chat updated, audit event) (new aggregate); create matter (new).

## Matter workspace — `/matters/:id`
- **code_pre:** "Matter Intelligence" header, 5 action buttons, 11 underline tabs
  (Overview, Matter DNA, Documents, Timeline, People, Arguments, Precedents, Drafts,
  Emails, Knowledge, Audit). Overview = AI summary + key issues + recent activity +
  parties + team + important dates.
- **Today:** 7 tabs with real data (Overview facts/issues/parties/team, Documents,
  Timeline, Deadlines, People, Arguments, Related).
- **Target (spec §16):** header = matter title, client, code, status, restricted badge,
  primary **Open AI workspace**. Stat strip: *24 Documents · 8 Conversations · 12
  Authorities · 5 Deadlines · 3 Drafts* (each links to its tab). Tabs:
  1. **Overview** — summary (generated once, cached, cited — not an unsourced blurb),
     key issues, parties, team, important dates, recent activity (D6).
  2. **Chat** — the workspace embedded with this matter as context; conversation list
     filtered to the matter.
  3. **Documents** — the Documents table scoped to the matter (folders, multi-select).
  4. **Research** — saved research answers and authorities for the matter.
  5. **Drafts** — generated drafts + versioned working documents (draft evolution).
  6. **Timeline** — chronology from dated documents + deadlines + key events; each item
     opens its source.
  7. **Notes** — matter notes (new).
  People, Arguments and Related move into Overview side cards (they're short lists).
  code_pre's Matter DNA graph, Precedents, Emails, Audit tabs stay out until data exists.
- **Verdict:** ♻️ major (P3).

## Documents — `/documents`
- **code_pre:** table (name, type, author, matter, version, date) + upload dialog with
  source chips and a pipeline strip (Processing → Extracting → Indexing → Available).
- **Today:** server search/paging, text-paste ingest dialog.
- **Target (spec §17–18):**
  - Columns: **Document · Type · Matter · Updated · Pages · Status** (Status = ingest
    pipeline state: Processing / Indexed / Analyzed / Failed).
  - Toolbar: search, sort, filter (type, matter, author, date), **Upload** (drag-drop,
    multi-file, real progress from upload batches), **New folder** (matter scope).
  - **Multi-select** with a sticky action bar: "3 documents selected · 142 pages ·
    [Ask AI] Compare · Summarize · Find differences · Find conflicting clauses · Create
    timeline · Extract obligations". Ask AI opens chat with these as context.
  - Row click → viewer; hover → quick-look.
- **Verdict:** ♻️ major (P3). **Data:** upload batches exist; pages & status fields new.

## Document viewer — `/documents/:id`
- **code_pre:** 3 columns: section nav · rendered document with active section highlight ·
  matter, people, related docs, AI findings, precedent card.
- **Today:** chunk-based reader with chunk highlight, matter/forum sidebar, version count.
- **Target:** see **`03_DOCUMENT_VIEWER.md`**: section outline, reader/PDF modes,
  in-document search, zoom, page nav, download, full screen, selection toolbar, right
  rail with *Ask about this document*, findings (from review engine, not mock), notes,
  versions.
- **Verdict:** ♻️ major (P2/P6).

## Draft evolution — `/documents/:id/history`
- **code_pre:** version timeline with who/when/event, detail card with what/why/tags,
  added/removed/modified diff list.
- **Today:** version list + raw text diff `<pre>`.
- **Target:** code_pre layout with real fields (`document_versions.author_name`,
  `change_summary`, `version_status`), redline rendering of the semantic diff (same
  component as Compare, 03 §5).
- **Verdict:** ♻️ (P5).

## Compare — `/documents/compare?a=&b=` 🆕
- Spec §19. Side-by-side redline with change navigation, accept/reject/comment, export.
  See 03 §5. **Verdict:** 🆕 (P5).

## Research — `/research` 🆕 (authorities cited in firm documents, plus web research)
- Spec §20–21. Search box, filters (jurisdiction, court, date, practice, authority type,
  status), result cards (case, court·year, holding summary, key passage, Open authority),
  AI research answers with the four-way provenance split. See 02 §9 and D8.
- **Verdict:** 🆕 (P7), scope depends on Q3.

## Clients — `/clients`, `/clients/:id`
- **code_pre:** detail = Preferences (each "observed across N matters · last …"),
  communication style, recurring issues, historical matters, relationship card,
  institutional history timeline.
- **Today:** notes grouped Prefers/Avoid/Terms with source matter; matters table.
- **Target:** code_pre layout backed by data: preferences with *observed across N
  matters* (count notes by normalised text / tag), recurring issues = top legal issues
  across the client's matters (from `matters.legal_issues`), relationship = first
  matter date, lead partners (from matter teams), history = matters by year. "Ask about
  this client" starts a client-scoped chat.
- **Verdict:** ♻️ (P8). **Data:** aggregates only (new small endpoint).

## People — `/people`, `/people/:id`
- **code_pre:** detail = bio, experience stat grid, matters, drafting patterns, practice
  areas, industries, courts, experience timeline.
- **Today:** header, matters-in-scope table.
- **Target:** stat grid (matters by practice, documents authored, arguments), courts
  appeared before (from matters.court), matters table, timeline by year. No invented
  "bio" or "drafting patterns" unless a field exists (drop those).
- **Verdict:** ♻️ (P8). **Data:** aggregates (new endpoint, ACL-filtered counts).

## Arguments — `/arguments`
- **code_pre:** list with won/unclear counts; detail with success grid, prerequisites,
  authorities, counterarguments, matters, lawyers, formulation.
- **Today:** list + detail (issue, position, argument, outcome, matter).
- **Target:** group identical/similar issues across matters so "used in N matters ·
  outcomes" is real (group by normalised issue); authorities = citations extracted from
  the argument's supporting documents; drop prerequisites/counterarguments unless stored.
- **Verdict:** ♻️ (P8).

## Deadlines — `/deadlines`
- **code_pre:** simple dated list linked to matters.
- **Today:** table with status filter, overdue highlighting, owner, forum.
- **Target:** renamed **Calendar**, `/calendar` (with `/deadlines` redirecting). List and month
  views, filter by matter, kind and owner, and "My deadlines". Also shown on the Home widget and
  in the matter Timeline (Q7).
- **Verdict:** ✅/♻️ small.

## Teams — `/teams`
- **code_pre:** named team cards with members.
- **Today:** practice-area table (lawyers, open matters).
- **Target:** becomes Settings → Teams (Q7); `/teams` redirects there. One card per practice with member links.
- **Verdict:** ♻️ small.

## Settings — `/settings`
- **code_pre:** Profile, Firm, Appearance, Notifications, AI (toggles), Permissions, Data
  sources, Audit, Integrations — mostly static.
- **Today:** Profile (+ dev persona), Firm, System — all real.
- **Target:** add **Appearance** (theme: light/dark/system — real, stored per browser),
  **AI preferences** that the server actually honours (default scope, default model),
  **Teams** (from Teams page), **API keys** (admin: issue/revoke — replaces
  `scripts/issue_keys.py` for day-to-day use). Integrations/Data sources only when the
  sync feature flag is on.
- **Verdict:** ♻️ (P8).

## Sign-in
- **Today:** API-key form (production plan 07 flags cookie/SSO as remaining).
- **Target:** Precentis-branded sign-in; SSO/OIDC button once login work lands.

## Pages that stay removed ❌
Projects, global Activity, global Audit, Strategy, Due Diligence, Knowledge Gaps,
Knowledge Management, Experience, Staffing, Transitions, Knowledge hub, Precedents,
Permissions page, Similar Matters (lives as "Related" in matter), Timelines (lives in
matter), Data Sources (until sync is enabled). Each can return only with a data model;
the most likely to return is **Precedents** once drafts/clauses are stored (P4/P5).
