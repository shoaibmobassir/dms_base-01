# Feature: Retrieval Debug Panel

**Sprint:** 9  
**Priority:** P1  
**Date:** 2026-08-28  
**Updated:** 2026-09-03 — **IMPLEMENTED**

---

## Problem

Improving retrieval requires understanding what happens at each stage. Without a UI, engineers must hit the API manually to see channels, intent, weights, and scores.

---

## Requirements

1. Collapsible debug panel on Ask (default collapsed; `?debug=1` expands) — **done**
2. Understanding payload (intent, search_text, matter ids, practice) — **done**
3. Per-channel hit counts + top-3 — **done** via `POST /api/retrieval/debug`
4. Fusion weights from planner — **done**
5. Final results with provenance channels — **done**
6. URL toggle `?debug=1` — **done**

---

## Implementation (as shipped)

| Piece | Location |
|-------|----------|
| Debug API | `POST /api/retrieval/debug` → `app/retrieval/debugger.py` (engine v2) |
| Ask UI panel | `static/app.js` — `renderAskDebugPanel`, parallel fetch with answers |
| Architecture view | `/ui/architecture` + `GET /api/system/architecture` |
| Styles | `static/styles.css` — `.retrieval-debug-panel` |
| Docs | `docs/ARCHITECTURE.md` |

PM Gate: **PASS** (UI + API live; no eval claim in this feature alone).
