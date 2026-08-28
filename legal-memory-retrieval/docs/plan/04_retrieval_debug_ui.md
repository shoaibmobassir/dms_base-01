# Feature: Retrieval Debug Panel

**Sprint:** 9  
**Priority:** P1  
**Date:** 2026-08-28

---

## Problem

Improving retrieval requires understanding what happens at each stage. Currently there is no way to see — without hitting the API directly — which channels fired for a query, what intent was parsed, what the channel weights were, and where documents scored. This makes tuning slow.

---

## Requirements

1. A collapsible debug panel at the bottom of the Ask view (default collapsed for end users, expanded for dev)
2. Shows the `understanding` payload: intent, entities extracted, practice area, flags (skip_vector, skip_rerank, dedupe_matters)
3. Shows per-channel hit counts and top-3 hits per channel with raw scores
4. Shows fusion weights used for this query (from intent-adaptive weighting)
5. Shows pre-rerank vs post-rerank ordering for the top 5 results
6. A URL-based toggle: `?debug=1` opens the panel automatically

---

## Our independent design decisions

**Debug panel layout:**
```
▸ Debug — keyword: 18 hits · metadata: 12 hits · vector: 31 hits · graph: 0 hits
  Intent: exact_lookup · skip_vector: false · skip_rerank: false
  Weights: metadata×2.0 keyword×1.2 vector×0.75 graph×0.9
  Top hits before rerank:          Top hits after rerank:
  1. DOC-00122  fused: 0.0213       1. DOC-00122  rerank: 0.87
  2. DOC-00451  fused: 0.0198       2. DOC-00451  rerank: 0.82
```

**Implementation:** The `POST /retrieve` response already returns `understanding`. We need to add `channel_counts` and `pre_rerank_top5` to the `/retrieve` response (optional, only when `?debug=true` query param is passed to the route).

---

## API change

Add optional `debug: bool = False` to `RetrieveRequest`. When true, return:
```json
{
  "debug": {
    "channel_counts": { "keyword": 18, "metadata": 12, "vector": 31, "graph": 0 },
    "weights_used": { "keyword": 1.2, "metadata": 2.0, "vector": 0.75, "graph": 0.9 },
    "pre_rerank_top5": [ ... ],
    "latency_ms": { ... }
  }
}
```

---

## Files affected

- `app/api/main.py` — add debug field to retrieve endpoint
- `app/retrieval/engine.py` — return debug metadata when requested
- `static/app.js` — render debug panel when `?debug=1` in URL

---

## PM Gate

**Status:** PENDING

- [ ] Feature doc written ✓
- [ ] API change scoped (non-breaking — optional field) ✓
- [ ] No eval regression risk ✓
- [ ] Test: retrieve with `debug=true`, assert `channel_counts` present
