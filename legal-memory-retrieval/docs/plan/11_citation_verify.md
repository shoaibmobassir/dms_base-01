# Feature: Citation Verification — Grounding and Authority Check

**Sprint:** 13  
**Priority:** P3  
**Mike observation (product level):** Legal AI platforms can verify that a citation actually exists and check whether the cited source supports the stated proposition — preventing hallucinated references from reaching clients.  
**Mike source used as coding basis:** NO  
**Date:** 2026-08-28

---

## Problem

The current citation system ensures `cited ⊆ retrieved_doc_ids` (source grounding) but does not verify:
1. Whether the cited document actually supports the specific proposition in the answer
2. Whether a cited matter outcome has been superseded by a later matter on the same issue
3. Whether a document cited from the answer actually contains the quoted text

---

## User need

A partner reviews an AI-generated position memo before sending to a client. One citation is `DOC-00789 — arbitration award in Tata vs X`. The partner needs to know: (a) does DOC-00789 actually say what the answer claims? (b) is there a newer Apex matter that changed the firm's position on this issue?

---

## Requirements

1. `POST /citations/verify` — takes an answer text + a list of `(claim, doc_id)` pairs, returns a grounding verdict per claim
2. Grounding check: the claimed text is used as a query against the specific document's chunks; if retrieval returns the chunk at rank ≤ 5 with score ≥ 0.7, the citation is SUPPORTED
3. Supersession check: retrieves newer matters in the same practice area with similar issues; if a newer matter has a different outcome, flags the citation as POSSIBLY_SUPERSEDED
4. Verification result displayed as a badge next to each citation chip in the Ask UI: `✓ Supported`, `⚠ Superseded?`, `✗ Weak`

---

## Our independent design decisions

**Grounding algorithm:**
1. For each `(claim, doc_id)` pair, call `semantic_search(conn, claim, member_id, limit=10)` filtered to `doc_id`
2. If top result score ≥ 0.70 and `document_id == doc_id` → SUPPORTED
3. If top result score < 0.50 → WEAK (citation may be misattributed)
4. Between 0.50–0.70 → PARTIAL

**Supersession algorithm:**
1. Get the source matter's practice area and outcome from the `matters` table
2. `retrieve(conn, matter.outcome + " " + issue, member_id, k=5)` with date filter `doc_date > source_doc.doc_date`
3. If any hit has a different outcome on the same issue → POSSIBLY_SUPERSEDED

**No external legal database in Sprint 13** — verification is purely against the frozen corpus. CourtListener / external case law is post-Sprint-13.

**API:**
```json
POST /citations/verify
{
  "answer": "In MTR-2021-0044, the firm succeeded on the non-compete issue...",
  "citations": [
    { "claim": "firm succeeded on the non-compete issue", "doc_id": "DOC-00789" }
  ],
  "member_id": "MEM-00001"
}

Response:
{
  "verdicts": [
    {
      "doc_id": "DOC-00789",
      "claim": "firm succeeded on the non-compete issue",
      "grounding": "SUPPORTED",
      "grounding_score": 0.81,
      "supersession": "CLEAR",
      "notes": null
    }
  ]
}
```

---

## Files affected

- `app/api/main.py` — 1 new route
- New module: `app/answers/verify.py`
- `static/app.js` — citation chip badge update post-answer

---

## PM Gate

**Status:** PENDING

- [ ] Feature doc written ✓
- [ ] Grounding algorithm uses existing retrieval stack — no new model ✓
- [ ] No external API call in Sprint 13 ✓
- [ ] Test plan: verify a known-good citation (should be SUPPORTED), verify a fabricated claim (should be WEAK)
