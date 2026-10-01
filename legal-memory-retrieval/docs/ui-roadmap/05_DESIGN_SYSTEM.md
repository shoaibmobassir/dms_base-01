# 05 — Design system

Base: `app/code_pre` tokens and type (already ported to `frontend/src/index.css`).
This file adds what the workspace needs: dark mode, the three-column layout, new
components, and density rules.

## 1. Identity

- Product: **Precentis** — wordmark in DM Serif Display, monogram "P" on wine square
  (replaces today's "F / FirmOS").
- Tenant: firm name from `firm_profile` in the workspace switcher.
- Voice: plain, precise, lawyerly. No exclamation marks, no "magic". Buttons say what
  happens ("Ask about 3 documents", not "Go").

## 2. Colour tokens

Light (existing, code_pre): paper `oklch(0.985 0.003 20)`, ink `0.16 0.012 20`, wine
`0.34 0.14 2`, wine-soft `0.92 0.028 7`, background `0.965`, card white, border `0.86`.

**Dark (new — code_pre has none):** keep hue 20 (warm) so it reads as the same product.

| Token | Dark value | Note |
|---|---|---|
| `--background` | `oklch(0.17 0.008 20)` | warm near-black, not pure black |
| `--paper` (sidebar) | `oklch(0.20 0.008 20)` | one step above background |
| `--card` | `oklch(0.22 0.009 20)` | |
| `--foreground` / `--ink` | `oklch(0.93 0.006 20)` | |
| `--muted-foreground` | `oklch(0.68 0.015 20)` | ≥4.5:1 on card |
| `--border` | `oklch(0.32 0.01 20)` | hairlines stay visible |
| `--wine` | `oklch(0.72 0.12 5)` | lighter wine for text/links on dark |
| `--wine-soft` | `oklch(0.30 0.06 5)` | chip/selection backgrounds |
| `--primary` | `oklch(0.62 0.15 3)` | buttons |
| Highlight (citation passage) | `oklch(0.45 0.10 75 / 0.35)` | amber wash, distinct from wine selection |

Implementation: `:root` = light, `.dark` class on `<html>`, `prefers-color-scheme`
when theme = system; stored in `localStorage` (per-browser preference). Contrast checked
with the dataviz/a11y validator before shipping.

**Semantic colours for provenance** (02 §6): matter source = wine, authority = ink
outline, user-provided = neutral grey, unverified = amber.

## 3. Typography

- Display: DM Serif Display — page titles, key finding sentence, document headings in
  Reader mode.
- UI/body: Manrope 14–16px; answers 16px / 1.75.
- Mono: IBM Plex Mono — ids, dates, citations numbers, page refs.
- Reader mode body: a book serif (Source Serif 4, OFL) at 16–17px for long documents —
  closer to how legal documents are read than a UI sans.

## 4. Layout

| Surface | Width rule |
|---|---|
| Directory pages (matters, clients, people…) | `max-w-[1180px]`, `px-6 lg:px-10`, `space-y-8` (code_pre) |
| Matter workspace | same container, sticky underline tabs (code_pre) |
| Chat workspace | full-bleed, 4 columns (02 §1), message column max 820px |
| Document viewer page | full-bleed 3 columns (outline 220 · document · rail 280) |

- Resizable panels: `react-resizable-panels` (MIT), sizes persisted per browser.
- Breakpoints: mobile <768 (bottom nav), tablet 768–1279 (drawers), desktop ≥1280.

## 5. Components

Existing (keep): `PageHeader`, `SectionLabel`, `StatusLabel`, `Hairline`, `EmptyState`,
`ErrorState`, `TableSkeleton`, `Chip`, `SearchField`, `Action`, `DataTable`,
`QueryState`, `Pager`, `Inspector`, `EntityLink`s.

New (spec §32 mapped):

| Component | Notes |
|---|---|
| `Sidebar` (resizable), `MatterSelector`, `WorkspaceSwitcher`, `BottomNav` | shell |
| `TopBar` + `ThemeToggle` | |
| `CommandPalette` / `SearchModal` | one dialog, two modes (01 Shell) |
| `ChatMessage`, `AIResponse`, `ResponseActions`, `Citation`, `CitationPreview`, `ProvenanceLine`, `StageStatus` | chat |
| `Composer`, `ContextChips`, `ContextSelector`, `AddContextMenu`, `LegalToolMenu`, `ModelSelector` | chat |
| `ContextPanel`, `SourceCard`, `AuthorityCard`, `ResearchResult` | chat/research |
| `DocumentViewer` (Reader/Page/Table modes), `DocumentOutline`, `SelectionToolbar`, `HighlightLayer` | viewer |
| `DocumentList` (multi-select + action bar), `FileUploader` (drag-drop, multi, pipeline progress), `FolderTree` | documents |
| `ComparisonViewer`, `ChangeList` | compare |
| `MatterCard`, `StatStrip`, `ActivityTimeline` | matter |
| `Modal`, `Dropdown`, `Tooltip`, `Toast` | wrap existing Radix/sonner |

Each new component gets a Playwright or Vitest render test using recorded API
responses from the seeded DB (production plan 06 rule: no hand-written fixture data).

## 6. Dependencies to add (license-audit before use)

| Package | License | Why |
|---|---|---|
| `react-markdown` + `remark-gfm` | MIT | Tables, lists, quotes in answers (today's mini renderer has no tables) |
| `pdfjs-dist` | Apache-2.0 | Page mode (P6) |
| `react-resizable-panels` | MIT | Resizable columns |
| `@tanstack/react-virtual` | MIT | Long threads, big document lists |
| Scripts only: a PDF generator for seed data (Q8) | to choose (e.g. reportlab BSD) | Acme sample PDFs |

Record each in `docs/legal/DEPENDENCY_AUDIT.md`.

## 7. Motion & feedback

- Transitions 120–180ms, opacity/translate only; no bouncing. Citation highlight pulses
  once (400ms). `prefers-reduced-motion` disables all.
- Toasts for background outcomes only (upload indexed, export ready); inline states for
  everything the user is looking at.
- Skeletons match final layout (table rows, message blocks, document paragraphs).

## 8. Accessibility

- All actions keyboard reachable; shortcuts listed in a `?` overlay.
- Citation chips are buttons with accessible names ("Source 1: Share Purchase
  Agreement, clause 12.3").
- Streaming region `aria-live="polite"`, status line `role="status"`.
- Focus returns to the originating chip when the context panel closes.
- Colour is never the only provenance signal (icon + label too).
