# FirmOS design — Wine / Ink / Paper

FirmOS uses an editorial legal-workspace palette tuned for long reading sessions and restrained hierarchy.

## Tokens

| Token | Role |
|-------|------|
| **Paper** (`--paper`) | Sidebar and top bar surfaces — slightly warm off-white |
| **Ink** (`--ink`) | Display headings and firm identity text |
| **Wine** (`--wine`, `--wine-soft`) | Primary brand accent, active nav, citations, CTAs |
| **Background / foreground** | Main canvas and body copy |

Supporting UI tokens (`card`, `muted`, `border`, `secondary`) stay neutral so documents and tables remain the focus.

## Typography

- **DM Serif Display** — page titles and ask composer prompts (`font-display`)
- **Manrope** — UI and body (`font-sans`)
- **IBM Plex Mono** — IDs and grounding counts (`font-mono-id`)
- **Material Symbols Outlined** — navigation and affordances (light weight)

## Motion

Short `animate-rise` / `animate-fade` on page entry; disabled when `prefers-reduced-motion` is set.

## Components

Hairline borders instead of heavy cards; wine left-rail on active sidebar items; citation chips in `wine-soft` with hover to full wine.
