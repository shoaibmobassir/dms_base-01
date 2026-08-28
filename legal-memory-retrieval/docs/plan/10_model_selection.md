# Feature: Model & Provider Selection UI

**Sprint:** 12  
**Priority:** P2  
**Mike observation (product level):** Legal AI platforms expose a settings panel where users can choose which AI provider and model powers their session — balancing capability vs cost vs data-residency requirements.  
**Mike source used as coding basis:** NO  
**Date:** 2026-08-28

---

## Problem

The current provider is hardcoded via config: `answer_provider = auto` in `Settings`. A user cannot change it without editing `.env` and restarting the server. There is no UI to switch between extractive, Groq, and Gemini, or to inspect which model is active.

---

## Requirements

1. `GET /models` — returns available providers and their status (configured / not configured)
2. `POST /models/select` — sets the active provider for the current session (stored in Redis, session-scoped)
3. Settings view in UI: shows available providers, active provider, a toggle between extractive/groq/gemini
4. A model indicator in the header: `⬢ Groq · llama3-70b` or `⬢ Extractive`
5. Per-query provider override: `POST /ask` accepts optional `provider` field — uses session default if not set

---

## Our independent design decisions

**Providers exposed:**
```json
GET /models
{
  "active": "groq",
  "providers": [
    { "id": "extractive",  "label": "Extractive (local)",   "available": true,  "notes": "No LLM, snippet-only" },
    { "id": "groq",        "label": "Groq · openai/gpt-oss-20b", "available": true,  "notes": "Requires GROQ_API_KEY" },
    { "id": "gemini",      "label": "Gemini · gemini-3.5-flash-lite", "available": false, "notes": "GEMINI_API_KEY not set" }
  ]
}
```

**Session override:** Active provider stored in Redis as `provider:{session_token}` with TTL = 86400s. Falls back to `settings.answer_provider` when key missing.

**Security:** Provider selection does not expose API keys to the client. The client sees only `available: true/false` and a model label, never the key itself.

**No "bring your own key" in Sprint 12** — that comes after auth (Sprint 12 focuses on API key auth, which ties member identity to key; BYOK is a post-auth feature).

---

## Files affected

- `app/api/main.py` — 2 new routes
- New module: `app/models/selector.py` — session-scoped provider selection via Redis
- `static/app.js` — Settings view, model indicator in header

---

## PM Gate

**Status:** PENDING

- [ ] Feature doc written ✓
- [ ] No API key exposed to client ✓
- [ ] Session storage uses existing Redis (no new infra) ✓
- [ ] Test plan: select groq, POST /ask, assert provider = "groq" in response
