# FirmOS Design System

**Product:** FirmOS — legal intelligence workspace  
**Theme name:** Wine / Ink / Paper  
**Source of truth:** `src/styles/tokens.css`  
**Inspiration (requirements only):** Precentis product palette, Apple-minimal product UX. Mike is AGPL research-only — no source copied.

This document is the design contract for the FirmOS SPA (`/ui`). Prefer these tokens over hard-coded colours.

---

## 1. Design intent

FirmOS should feel like institutional chambers software: calm, typographic, and precise — not a SaaS dashboard.

| Pillar | Meaning |
|--------|---------|
| **Paper** | Warm near-white canvas; quiet atmosphere |
| **Ink** | Near-black for reading text and hierarchy |
| **Wine** | Deep burgundy accent — used sparingly for selection and primary action |
| **Minimal chrome** | Hairline borders, no heavy shadows, no purple gradients, no pill clusters |

Hue family sits around **oklch hue ≈ 2–20** (warm red–rose), not teal, not purple.

---

## 2. Colour schema (detailed)

All production colours are **oklch**. Hex values are approximate fallbacks for tooling and older engines.

### 2.1 Core triad

| Name | Token | OKLCH | Hex (approx.) | Role |
|------|-------|-------|---------------|------|
| **Paper** | `--paper` | `oklch(0.985 0.003 20)` | `#fdfbfb` | App canvas, sidebar surface, reading background |
| **Ink** | `--ink` | `oklch(0.16 0.012 20)` | `#1a0e0e` | Display headings, strong emphasis, ink CTAs |
| **Wine** | `--wine` | `oklch(0.34 0.14 2)` | `#670025` | Brand accent, eyebrows, active nav bar, selection |

### 2.2 Semantic UI tokens

| Token | OKLCH | Hex (approx.) | Use |
|-------|-------|---------------|-----|
| `--background` | `oklch(0.965 0.004 20)` | `#f6f2f2` | Slightly deeper paper for nested panels |
| `--foreground` | `oklch(0.19 0.012 20)` | `#1e1212` | Default body text |
| `--card` | `oklch(1 0 0)` | `#ffffff` | Pure white elevated surface (tables, sheets) |
| `--card-foreground` | `oklch(0.19 0.012 20)` | `#1e1212` | Text on cards |
| `--primary` | `oklch(0.38 0.15 2)` | `#7c043c` | Primary buttons, links of consequence |
| `--primary-foreground` | `oklch(0.98 0.004 20)` | `#faf7f7` | Text/icons on primary / wine fills |
| `--secondary` | `oklch(0.91 0.008 20)` | `#e8e2e2` | Quiet fills, hover washes |
| `--secondary-foreground` | `oklch(0.24 0.015 20)` | `#2c1c1c` | Text on secondary fills |
| `--muted` | `oklch(0.925 0.006 20)` | `#ece6e6` | Muted section backgrounds |
| `--muted-foreground` | `oklch(0.48 0.02 20)` | `#695959` | Captions, meta, placeholders |
| `--accent` | `oklch(0.88 0.035 8)` | `#e8d4d6` | Soft blush highlight |
| `--accent-foreground` | `oklch(0.32 0.11 2)` | `#5c1028` | Text on accent wash |
| `--wine-soft` | `oklch(0.92 0.028 7)` | `#f0e0e3` | Active nav wash, soft chips, avatars |
| `--destructive` | `oklch(0.55 0.2 27)` | — | Errors, destructive actions |
| `--border` | `oklch(0.86 0.01 20)` | `#ded5d5` | Hairline rules, table lines |
| `--input` | `oklch(0.86 0.01 20)` | `#ded5d5` | Field borders |
| `--ring` | `oklch(0.43 0.14 2)` | — | Focus ring (wine-leaning) |
| `--steel` | `oklch(0.58 0.015 250)` | — | Cool outline / secondary chrome |

### 2.3 Hex fallbacks (declared in tokens)

```css
--background-hex: #f6f2f2;
--foreground-hex: #1e1212;
--primary-hex:    #7c043c;
--wine-hex:       #670025;
--ink-hex:        #1a0e0e;
--paper-hex:      #fdfbfb;
--border-hex:     #ded5d5;
--muted-fg-hex:   #695959;
```

### 2.4 How to mix them (usage map)

```
Canvas          →  --paper
Body text       →  --foreground
Titles (serif)  →  --ink
Eyebrows / meta →  --wine  (uppercase, tracked)
Secondary copy  →  --muted-foreground
Hairlines       →  --border
Primary CTA     →  --primary fill + --primary-foreground text
Ink CTA         →  --ink fill + --primary-foreground text
Active nav      →  left bar --wine + wash --wine-soft
Soft chip/badge →  --wine-soft bg + --wine or --accent-foreground text
Selection       →  --wine bg + --primary-foreground text
Focus           →  --ring
Error           →  --destructive
```

### 2.5 Contrast rules

| Pairing | Intent |
|---------|--------|
| `--ink` or `--foreground` on `--paper` / `--card` | Primary reading (AA+) |
| `--primary-foreground` on `--primary` / `--wine` / `--ink` | Buttons and filled controls |
| `--muted-foreground` on `--paper` | Meta only — never for long body copy |
| Never put `--wine` as large body text on `--paper` | Too heavy; reserve for eyebrows / accents |

### 2.6 What this theme is *not*

- No purple / indigo gradients  
- No teal / copper “legal SaaS” leftovers  
- No dark-mode default (light paper is the product)  
- No neon glow, multi-layer shadows, or emoji decoration  
- No rainbow status chips — status uses quiet `--wine-soft` / `--status` language  

---

## 3. Typography

| Role | Family | Token | Typical size |
|------|--------|-------|--------------|
| Display / page titles | **DM Serif Display** | `--font-display` | `clamp(2.6rem, 4vw, 4.25rem)` — weight 400 |
| Section headings | DM Serif Display | `--font-display` | ~1.5–2rem |
| UI / body | **Manrope** | `--font-sans` | 15px body, lh 1.55 |
| Eyebrow | Manrope | — | ~0.65rem, uppercase, tracking `0.14em`, weight 800, colour `--wine` |
| Meta / labels | Manrope | — | ~0.7rem, tracking `0.06em`, weight 700 |
| IDs / codes | System mono | `--font-mono` | ~0.82em |

CDN (already in `index.html`):

- `DM Serif Display` (roman + italic)  
- `Manrope` 400–700  
- Material Symbols Outlined (`wght` 300) for icons  

---

## 4. Layout & geometry

| Token | Value | Notes |
|-------|-------|-------|
| `--nav-width` | `256px` | Persistent left rail |
| `--header-h` | `52px` | Sticky top bar |
| `--gutter` | `28px` | Main content padding rhythm |
| `--margin-desktop` | `48px` | Outer page margin |
| `--inspector-width` | `300px` | Optional right inspector |
| `--reading-column` | `680px` | Ask / prose max width |
| `--radius` | `0.25rem` | Default corners (tight, institutional) |
| `--radius-lg` | `0.5rem` | Larger sheets only |

**Shell structure**

1. Left: paper sidebar — brand, firm switcher, Workspace / Manage groups  
2. Right: sticky header (crumbs + command search + persona) + scrollable main  
3. Active nav: wine left rail + soft blush wash — **not** a filled pill  

---

## 5. Component language

### Page intro

- Eyebrow (`--wine`) → serif `h1` (`--ink`) → lede (`--muted-foreground`)  
- Optional primary button top-right  

### Directory tools

- Inline search field + optional filter + count  
- Avoid chip clouds and dense toolbars  

### Tables

- Editorial lists on `--card` / paper  
- Hairline `--border` dividers  
- Row hover: quiet `--secondary` or `--muted` wash  
- Prefer `.status` soft labels over saturated badges  

### Buttons

| Class | Fill | Text |
|-------|------|------|
| `.button-primary` | `--primary` | `--primary-foreground` |
| Ink / Ask CTA | `--ink` | `--primary-foreground` |
| `.button-secondary` | transparent / `--secondary` | `--foreground` |

### Surfaces

- Prefer open layout over nested cards  
- Cards only when they contain an interaction (composer, table sheet)  
- Drop shadow only if hierarchy fails without it (default: none)  

---

## 6. Motion (restrained)

Use motion for presence, not decoration:

1. Soft fade/slide on route content (~150–200ms)  
2. Nav active indicator transition  
3. Composer / button press feedback  

No bouncing, parallax, or continuous ambient animation.

---

## 7. Implementation checklist

- [ ] Import colours only via CSS variables from `tokens.css`  
- [ ] New UI: map to semantic tokens (`--primary`, `--muted-foreground`, …), not raw hex  
- [ ] Titles use `--font-display` + `--ink`  
- [ ] Eyebrows use `--wine` + Manrope uppercase  
- [ ] Sidebar active state = wine bar + `--wine-soft`  
- [ ] Rebuild: `cd frontend && npm run build` → serves at `/ui/`  

---

## 8. Quick reference — copy block

```css
/* FirmOS Wine / Ink / Paper — core */
--paper:              oklch(0.985 0.003 20);  /* #fdfbfb */
--ink:                oklch(0.16 0.012 20);   /* #1a0e0e */
--wine:               oklch(0.34 0.14 2);     /* #670025 */
--wine-soft:          oklch(0.92 0.028 7);
--background:         oklch(0.965 0.004 20);  /* #f6f2f2 */
--foreground:         oklch(0.19 0.012 20);   /* #1e1212 */
--primary:            oklch(0.38 0.15 2);     /* #7c043c */
--primary-foreground: oklch(0.98 0.004 20);
--muted-foreground:   oklch(0.48 0.02 20);    /* #695959 */
--border:             oklch(0.86 0.01 20);    /* #ded5d5 */
--font-sans:          'Manrope', system-ui, sans-serif;
--font-display:       'DM Serif Display', serif;
```

---

## 9. File map

| File | Purpose |
|------|---------|
| `frontend/DESIGN.md` | This design contract |
| `frontend/src/styles/tokens.css` | Token definitions |
| `frontend/src/styles/global.css` | Shell + component styles |
| `frontend/src/layout/AppShell.tsx` | Workspace shell |
| `docs/legal/IP_ORIGIN_RECORD.md` | Clean-room / inspiration notes |

When tokens change, update **this file** and `tokens.css` together.
