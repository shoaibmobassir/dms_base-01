---
name: Precentis (Harbour International Chambers knowledge base)
description: A quiet wine, ink and paper workspace for lawyers reading long documents and checking sources.
colors:
  paper: "oklch(0.985 0.003 20)"
  ink: "oklch(0.16 0.012 20)"
  wine: "oklch(0.34 0.14 2)"
  wine-soft: "oklch(0.92 0.028 7)"
  background: "oklch(0.965 0.004 20)"
  foreground: "oklch(0.19 0.012 20)"
  card: "oklch(1 0 0)"
  primary: "oklch(0.38 0.15 2)"
  primary-foreground: "oklch(0.98 0.004 20)"
  secondary: "oklch(0.91 0.008 20)"
  secondary-foreground: "oklch(0.22 0.012 20)"
  muted: "oklch(0.925 0.006 20)"
  muted-foreground: "oklch(0.48 0.02 20)"
  accent: "oklch(0.88 0.035 8)"
  accent-foreground: "oklch(0.32 0.11 2)"
  border: "oklch(0.86 0.01 20)"
  ring: "oklch(0.43 0.14 2)"
  destructive: "oklch(0.55 0.2 27)"
  success: "oklch(0.5 0.09 150)"
  success-soft: "oklch(0.95 0.035 150)"
  success-ink: "oklch(0.38 0.08 150)"
  warning: "oklch(0.62 0.13 70)"
  warning-soft: "oklch(0.96 0.045 80)"
  warning-ink: "oklch(0.42 0.1 65)"
  info: "oklch(0.45 0.1 235)"
  info-soft: "oklch(0.95 0.025 235)"
  highlight: "oklch(0.9 0.09 85 / 0.55)"
typography:
  display:
    fontFamily: "'DM Serif Display', Georgia, serif"
    fontSize: "3rem"
    fontWeight: 400
    lineHeight: 1.05
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "'DM Serif Display', Georgia, serif"
    fontSize: "1.875rem"
    fontWeight: 400
    lineHeight: 1.05
    letterSpacing: "-0.01em"
  title:
    fontFamily: "'DM Serif Display', Georgia, serif"
    fontSize: "1.25rem"
    fontWeight: 400
    letterSpacing: "-0.01em"
  body:
    fontFamily: "'Manrope Variable', Manrope, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
  label:
    fontFamily: "'Manrope Variable', Manrope, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
  mono-id:
    fontFamily: "'IBM Plex Mono', ui-monospace, SFMono-Regular, monospace"
    fontSize: "0.8em"
    fontWeight: 400
    letterSpacing: "0.01em"
    fontFeature: "'tnum'"
rounded:
  xs: "2px"
  sm: "4px"
  md: "6px"
  lg: "8px"
  full: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  page-x: "40px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
    height: "36px"
  button-outline:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: "8px 14px"
  button-outline-hover:
    backgroundColor: "{colors.secondary}"
  button-destructive:
    backgroundColor: "{colors.destructive}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.md}"
    height: "36px"
  input:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: "4px 12px"
    height: "36px"
  chip-wine:
    backgroundColor: "{colors.wine-soft}"
    textColor: "{colors.wine}"
    rounded: "{rounded.full}"
    padding: "2px 10px"
  chip-muted:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.secondary-foreground}"
    rounded: "{rounded.full}"
    padding: "2px 10px"
  empty-state:
    backgroundColor: "{colors.card}"
    textColor: "{colors.muted-foreground}"
    rounded: "{rounded.lg}"
    padding: "48px 32px"
---

# Design System: Precentis

## Overview

**Creative North Star: "The Chambers Reading Room"**

A warm paper surface, near-black ink, and one deep wine accent, set for long sessions with documents, tables and cited answers. The work is the subject: tables and passages sit on hairline rules instead of heavy cards, and chrome stays quiet so source text and citations carry the weight. A serif display face gives pages a printed-title register; a clean humanist sans does all the working UI.

Density is moderate and list-driven: 13-14px working text, 36px controls, hairline row dividers. Depth is tonal and almost flat. Dark mode keeps the same warm hue (20) and lifts wine for contrast, so it reads as the same product.

**Key Characteristics:**
- Wine, ink and paper in oklch, all warm-tinted neutrals (hue 20, chroma at or below 0.02).
- Semantic tokens are paired as solid, soft and ink so statuses stay legible in both themes.
- Hairline borders and tonal fills over shadows.
- Serif for titles only; sans for everything operational; mono for identifiers.
- Light and dark themes share one token set, switched by the `.dark` class.

## Colors

A restrained wine accent on warm paper neutrals, with muted green, amber and blue reserved for status. Values are in the frontmatter; they are defined once as CSS custom properties in `frontend/src/index.css` and consumed through Tailwind names.

### Primary
- **Wine** (`wine`): brand accent for active navigation, the logo tile, selection text, links on hover, "Active/Open/Live" status text, and tick boxes (`accent-color`). Lifts to a lighter wine in dark mode.
- **Primary Wine** (`primary`): slightly lighter solid for filled buttons and badges. Distinct from `wine` by lightness only; use `primary` for fills and `wine` for text and rails.
- **Wine Tint** (`wine-soft`): selection background, wine chips, citation chips.

### Secondary
- **Rose Accent** (`accent`, `accent-foreground`): hover fill for ghost and outline buttons and menu items.

### Neutral
- **Paper** (`paper`): sidebar, top bar, and mobile bottom nav surface.
- **Canvas** (`background`): page background; `card` (pure white in light) lifts content one step above it.
- **Ink** (`ink`): display headings and firm identity text. `foreground` is body copy.
- **Muted** (`muted`, `secondary`, `muted-foreground`): skeletons, neutral chips, row hover (`secondary` at 60%), secondary text.
- **Hairline** (`border`, also `input`): every divider and field stroke. `ring` is the focus color.

### Semantic
- **Success, Warning** (each with `-soft` and `-ink`), **Info** (with `-soft`): status text and tinted surfaces. `destructive` for errors and restricted states. `highlight` (amber, translucent) marks cited passages in documents and must stay distinct from wine selection.

### Named Rules
**The One Accent Rule.** Wine is the only chromatic brand color. Green, amber and blue appear only as status, never as decoration.

**The Citation Amber Rule.** Cited-passage highlighting uses `highlight`, never wine, so a citation is never confused with a selection.

**The Token Only Rule.** Surfaces read color from the CSS custom properties so both themes work. Raw rgb/hex values are not part of the system (see drift note in the report).

## Typography

**Display Font:** DM Serif Display (with Georgia, serif)
**Body Font:** Manrope Variable (with Manrope, system-ui, sans-serif)
**Label/Mono Font:** IBM Plex Mono (with ui-monospace), tabular figures

**Character:** An editorial serif title over a plain, legible sans; mono marks identifiers and counts as machine-exact.

### Hierarchy
- **Display** (400, 3rem at sm and up, 2.25rem below, 1.05): page titles on editorial pages (`PageHeader`), in ink.
- **Headline** (400, 1.875rem, 1.05): compact page titles on list and tool pages.
- **Title** (400, 1.25rem): empty-state and panel titles; brand wordmark at 1.125rem.
- **Body** (400, 0.875rem; 1rem for page subtitles): working text. Dense table and sidebar text uses 13px; 12px for hints. Keep prose to about 65ch (`max-w-md` to `max-w-2xl` blocks).
- **Label** (600, 0.75rem): button-sm, badges, status text, small controls.
- **Mono ID** (400, 0.8em, tnum): matter, client and document ids and grounding counts, in muted foreground.

### Named Rules
**The Serif Is For Titles Rule.** DM Serif Display is for page, panel and empty-state titles and the wordmark. Controls, tables and body copy are Manrope.

**The Mono Means Identifier Rule.** Anything the user might copy or quote exactly (ids, counts) uses Plex Mono with tabular figures.

## Layout

An app shell with a resizable left sidebar on paper (default width stored per user, 256px sheet on mobile), a top bar, and a centered content column of max 1180px with 24px side padding (40px at lg) and 32-40px vertical padding. Under md the sidebar becomes a sheet and a five-item bottom nav (Home, Matters, Assistant, Ask, Documents) appears.

Spacing follows Tailwind's 4px scale. Most common: gap-1/2/3 (4/8/12px) inside components, px-3 py-1/2 for controls, py-4 table rows, 48px by 32px empty states. Page headers stack to a row at md with the actions right-aligned. Sections are separated by hairlines and whitespace, not boxes.

## Elevation & Depth

Mostly flat and tonal. Layering comes from canvas, then white card, then paper chrome, with hairline borders doing the separation. Shadows are small and appear on controls and floating layers only.

### Shadow Vocabulary
- **Hairline** (`box-shadow: 0 1px 0 0 rgb(0 0 0 / 0.05)`, `shadow-2xs`): flat separators.
- **Control** (`0 1px 2px 0 rgb(0 0 0 / 0.05)`, `shadow-xs`; Tailwind `shadow-sm` on outline, secondary, input): buttons and inputs.
- **Floating** (Tailwind `shadow-md` to `shadow-xl`): menus, dialogs, sheets and popovers.
- **Active rail** (`inset 3px 0 0 var(--wine)`): active row marker.

### Named Rules
**The Flat Page Rule.** Page content, tables and record panels carry no shadow; only controls and floating layers do. All shadows are soft blur; none are hard offset.

## Shapes

Gently curved: 0.5rem base radius (`--radius`), derived as lg 8px, md 6px, sm 4px, plus a 2px xs. Controls and inputs use md (6px); panels, empty states and cards use lg (8px); chips, status dots and scrollbar thumbs are fully round. Empty states use a dashed hairline border. Active navigation is marked by a 3px rounded wine rail at the left edge.

## Components

### Buttons
- **Shape:** md radius (6px), 36px tall by default, 32px small, 40px large, 36px square icon.
- **Primary:** `primary` fill, `primary-foreground` text, 14px medium; hover at 90% opacity. The in-page `Action` helper does the same at semibold with a 0.98 press scale.
- **Outline / Secondary / Ghost / Link:** outline is a hairline border on card with `secondary` hover; ghost fills `accent` on hover; link is primary text with underline on hover. Destructive uses `destructive` fill.
- **Focus:** 2px `ring` outline at 2px offset globally; shadcn controls also draw a 1px ring. Disabled drops to 50% opacity.

### Chips and Badges
- **Chip:** fully round, 2px by 10px, 12px medium; tones muted (`secondary`), wine (`wine-soft` with wine text), accent. Citation chips use the wine tone and go full wine on hover.
- **Badge:** md radius, 12px semibold, variants default, secondary, destructive, outline.
- **Status label:** a small dot plus 12px semibold text, colored wine (active), success, warning, destructive or muted by state.

### Cards / Containers
- **Corner Style:** lg (8px).
- **Background:** `card` on `background`, bordered with `border`; no shadow.
- **Internal Padding:** 32px by 48px for state panels; tables use bare hairline rows.

### Inputs / Fields
- **Style:** 36px high, md radius, hairline `input` stroke, transparent or card fill, 14px text with muted placeholder. `SearchField` adds a leading search icon.
- **Focus:** ring color on a 1px ring. **Disabled:** 50% opacity, not-allowed cursor.

### Navigation
- Sidebar on `paper`: logo tile (wine, serif initial), firm identity line, grouped items with muted icons that turn wine when active, plus the left wine rail. Item hints use Plex Mono. The sidebar is collapsible and resizable. Mobile uses a sheet and a bottom nav on paper.

### Data Table
- Hairline row dividers, 16px vertical row padding, muted column headers with sort icons, row hover `secondary` at 60%, keyboard-focusable rows, wine `accent-color` checkboxes for selection with a bulk action bar.

### Icons
- Material Symbols Outlined at weight 300, 20px default (14-18px inline, 28px in empty states), in muted foreground by default, decorative unless labelled.

### Document Page (signature)
- The editor shows documents as Word-like pages: Times New Roman or Georgia 15px at 1.6 line height on a page canvas. Content in a document page follows document conventions rather than the app type scale.

## Do's and Don'ts

### Do:
- **Do** read all colors from the semantic tokens so light and dark both work.
- **Do** use `primary` for fills and `wine` for text, rails and selection.
- **Do** pair statuses as solid, soft and ink (success, warning, info).
- **Do** use DM Serif Display for titles only and Plex Mono with tabular figures for ids.
- **Do** separate with hairlines (`border`) and keep page content flat.
- **Do** respect reduced motion: entry animations are 180-220ms fade or 6px rise and are disabled under `prefers-reduced-motion`.

### Don't:
- **Don't** introduce a second chromatic brand color; green, amber and blue are status only.
- **Don't** use wine for cited-passage highlights; use `highlight`.
- **Don't** put shadows on page content or use hard offset shadows.
- **Don't** set UI controls, table cells or body copy in the display serif.
- **Don't** use raw rgb/hex colors in new surfaces.
