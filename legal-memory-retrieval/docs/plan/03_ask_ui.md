# Feature: Ask Firm AI — Full Chat Interface

**Sprint:** 9  
**Priority:** P0  
**Mike observation (product level):** Legal AI platforms display AI answers with visible citation links so users can verify which source documents support each claim. Results feel like a research session, not a form submission.  
**Mike source used as coding basis:** NO  
**Date:** 2026-08-28

---

## Problem

The current `/ui` Ask view calls `POST /ask` and dumps the response text in a box. There is no:
- Display of which documents were cited (click-through to chunk text)
- Per-stage latency breakdown (understand → retrieve → rerank → answer)
- Abstention explanation shown to the user
- Query history within a session
- Streaming feel — it's a single response dump with no feedback while waiting
- Retrieval debug panel showing which channels fired and their scores

---

## Requirements

1. Ask input: full-width query box, persona selector, submit on Enter / click
2. While waiting: animated indicator showing which pipeline stage is running (understand → retrieve → rerank → answer)
3. Response display:
   - Answer text rendered with basic formatting (bold, line breaks)
   - `abstained: true` responses show a clear "No evidence found" message with reason
   - Citation chips below the answer: each chip shows `DOC-XXXXX`, click opens a right-pane document preview
4. Right-pane document preview: shows `title`, `matter_id`, `document_type`, `chunk text` (the retrieved snippet)
5. Per-query latency: collapsed line `Latency: understand 2ms · retrieve 190ms · rerank 88ms · total 340ms` — expand to see all stages
6. Session hit list: below each answer, a collapsible `Retrieved sources (k=10)` section showing all hits with their `rerank_score` and `channel`
7. Query history: the last 20 queries in the current browser session, shown in a left-of-input history list. Click any to re-run.
8. Retrieval debug toggle: a small `[debug]` button that reveals the full retrieval payload (intent, entities, channel weights, fused scores)

---

## Our independent design decisions

**Layout:**
```
┌─────────────────────────────────────────────────────┐
│  QUERY INPUT                                 PERSONA │
│  [Ask the firm about matters, precedents...] [MEM-01]│
│                                              [Ask ▶] │
├─────────────────────────────────────────────────────┤
│  UNDERSTANDING                                       │
│  Intent: exact_lookup · Matter: MTR-2019-00001       │
│  Channels: keyword(1.2) metadata(2.0) vector         │
├─────────────────────────────────────────────────────┤
│  ANSWER                                              │
│  [Answer text here]                                  │
│                                                      │
│  Cited: [DOC-00122] [DOC-00451]                      │
│  Latency: 340ms total  [expand]                      │
│  [▸ Retrieved sources (10)]                          │
├─────────────────────────────────────────────────────┤
│  HISTORY                                             │
│  • What happened in MTR-2021-00401?                  │
│  • Which lawyers handled arbitration matters?        │
└─────────────────────────────────────────────────────┘
```

**Citation chip:** A small pill — `DOC-00122` — clicking it fetches `GET /documents/DOC-00122` and renders the chunk text in the right inspector pane.

**Abstention display:**
- `no_evidence` → "No firm records match this query." 
- `access_or_miss` → "This matter is restricted or not found in your accessible records."

**Stage indicator:** A single line of 5 dots (understand · keyword · vector · rerank · answer) that fills left-to-right while the request is in-flight. Since the current API is not streaming, this is a simulated progress that completes when the response arrives. Actual stage latencies from the `latency_ms` field in the response fill the detail view.

**Session history:** Stored in `sessionStorage` as a JSON array `[{query, ts, result}]`. Max 20 entries, FIFO. Never persisted to disk (privacy — no chat history backend needed for Sprint 9).

---

## API dependency

`POST /ask` response must include `latency_ms` dict. Current API (Sprint 9) already returns this.  
New needed: `GET /documents/{document_id}` — returns document title, matter_id, type, and the matched chunk text.

```json
GET /documents/DOC-00122

{
  "document_id": "DOC-00122",
  "matter_id": "MTR-2019-00014",
  "title": "Share Purchase Agreement — v3",
  "document_type": "Agreement",
  "matter_code": "COR/MAC/2019/0014",
  "chunk_text": "...",
  "doc_date": "2019-11-12"
}
```

---

## Files affected

- `app/api/main.py` — add `GET /documents/{document_id}`
- `static/app.js` — rewrite the Ask view render function
- `static/styles.css` — citation chip, stage indicator, answer card styles

---

## PM Gate

**Status:** PENDING

**Pre-implementation checks:**
- [ ] Feature doc written ✓
- [ ] IP_ORIGIN_RECORD entry written
- [ ] `GET /documents/{document_id}` endpoint designed ✓
- [ ] Latency display confirmed available in Sprint 9 API response
- [ ] No new dependencies ✓
- [ ] Test plan: test that abstention UI shows for empty retrieval; test citation chip data

**Post-implementation checks:**
- [ ] Retrieval eval: no regression
- [ ] Manual test: submit query, verify citations, click DOC chip, see chunk text
- [ ] Abstention test: submit "zzz unknown query", verify correct message shown
- [ ] CHANGELOG updated
