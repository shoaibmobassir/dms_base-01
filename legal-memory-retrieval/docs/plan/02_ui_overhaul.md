# Feature: UI Overhaul — Professional Minimalist Design System

**Sprint:** 9  
**Priority:** P0  
**Mike observation (product level):** Legal AI platforms use clean, dark-capable interfaces with clear hierarchy, consistent spacing, and typography that reads as professional — no decorative chrome.  
**Mike source used as coding basis:** NO  
**Date:** 2026-08-28

---

## Problem

The current LEXOS UI has the right structure (sidebar, workspace, right pane) but several quality issues:
- Emoji icons in navigation and buttons (`⚖️`, `📁`, `👥`, etc.) feel unprofessional in a legal context
- `firm_core_data.js` (82,753 lines) is embedded in the page load — every view is reading from a static snapshot instead of live API data
- No consistent design token system — colours and spacing are inline or inconsistently applied
- The command palette (⌘K) searches only static data, not the live `/retrieve` endpoint
- Font rendering inconsistent across views

---

## Requirements

1. Replace emoji icons with clean text symbols or SVG line icons (no Lucide CDN — inline SVG strings only, keeping zero external dependencies)
2. Establish a CSS design token layer: `--color-*`, `--space-*`, `--radius-*`, `--font-*` variables
3. Remove `firm_core_data.js` as a page-load dependency — wire each view to its own API endpoint instead
4. Add five new REST endpoints to `app/api/main.py` to serve the data views need:
   - `GET /members` — returns list of members (id, name, role, office, practice_areas)
   - `GET /clients` — returns list of clients (id, name, industry, size)
   - `GET /matters` — returns paginated matters (id, matter_code, title, client_name, practice_area, status)
   - `GET /matters/{matter_id}` — full matter detail
   - `GET /documents` — paginated document list (id, title, doc_type, matter_id, doc_date)
5. Command palette (⌘K) sends text input to `POST /retrieve` and renders hits inline
6. No external CDN dependencies — all assets self-hosted

---

## Our independent design decisions

**Token system:**
```css
:root {
  --c-bg:          #0a0a0a;      /* near-black canvas */
  --c-surface-1:   #111111;      /* primary surface */
  --c-surface-2:   #181818;      /* elevated card */
  --c-border:      #242424;      /* subtle divider */
  --c-text-1:      #f0f0f0;      /* primary text */
  --c-text-2:      #888888;      /* secondary / label */
  --c-text-3:      #555555;      /* placeholder / disabled */
  --c-accent:      #e8c97e;      /* warm gold — legal identity */
  --c-accent-dim:  rgba(232,201,126,0.12);
  --c-danger:      #e05252;
  --c-ok:          #52c97e;
  --font-mono:     'SF Mono', 'JetBrains Mono', ui-monospace, monospace;
  --font-sans:     -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;
  --radius-sm:     4px;
  --radius-md:     8px;
  --space-xs:      4px;
  --space-sm:      8px;
  --space-md:      16px;
  --space-lg:      24px;
  --space-xl:      40px;
}
```

**Icon strategy:** Replace all emoji with 2-character monogram squares or minimal SVG paths. No icon fonts. No external icon libraries.

**Light theme:** Inverts the palette — `--c-bg: #f8f8f6`, surfaces white/near-white, accent same gold.

**Typography:** System font stack. Headings in `-apple-system` weight 600. Body 14px / line-height 1.6. Monospace for IDs, codes, and scores.

---

## API endpoints — data shapes

### `GET /members`
```json
[
  { "member_id": "MEM-00001", "name": "Aryan Maharaj", "role": "Lead Partner", "office": "Mumbai", "practice_areas": ["M&A", "Regulatory"] }
]
```

### `GET /matters`
Query params: `q` (search), `practice` (filter), `limit` (default 50), `offset` (default 0)
```json
{
  "total": 1000,
  "items": [
    { "matter_id": "MTR-2019-00001", "matter_code": "...", "title": "...", "client_name": "...", "practice_area": "M&A", "status": "Closed" }
  ]
}
```

### `GET /matters/{matter_id}`
Returns full matter including related documents (first 20), team members, and arguments.

### `GET /clients`
```json
[{ "client_id": "CLI-00055", "name": "...", "industry": "...", "size": "..." }]
```

### `GET /documents`
Query params: `matter_id`, `doc_type`, `limit`, `offset`

---

## Files affected

- `app/api/main.py` — add 5 new GET endpoints
- `static/styles.css` — full rewrite with token system
- `static/app.js` — replace firm_core_data reads with fetch() calls, fix command palette
- `static/index.html` — remove firm_core_data.js script tag

---

## What changes visually

| Before | After |
|---|---|
| Emoji nav icons | Clean text labels with monospace prefix |
| Static data from JS bundle | Live data from API |
| ⌘K searches static list | ⌘K calls POST /retrieve |
| Inconsistent spacing | Token-driven spacing |
| 82k line JS on every page load | ~2k line app.js, data loaded per view |

---

## PM Gate

**Status:** PENDING

**Pre-implementation checks:**
- [ ] Feature doc written ✓
- [ ] IP_ORIGIN_RECORD entry (Mike-inspired at product level)
- [ ] 5 new API endpoints designed and documented ✓
- [ ] Token system defined ✓
- [ ] No new dependencies introduced ✓
- [ ] Test plan: add `test_browse_endpoints.py` covering the 5 new GETs

**Post-implementation checks:**
- [ ] Retrieval eval: no regression
- [ ] Manual UI test: all 5 views load with live data
- [ ] CHANGELOG updated
