# LEXOS — Master Feature Roadmap

**System:** Apex Chambers Legal Institutional Memory & DMS  
**Current sprint:** 8 (answers + citations + abstention — complete)  
**Port:** 8000 (live, serving `/ui`, `/retrieve`, `/ask`, `/health`, `/metrics`)  
**Corpus:** Frozen at v2 — 38,232 docs, 1,000 matters, 500 clients, 100 members

---

## IP Rule

All features below are independently designed from requirements.  
Mike (AGPLv3) is product research only — no source, schema, SQL, or UI may be copied.  
Every feature with Mike inspiration is logged in `docs/legal/IP_ORIGIN_RECORD.md` before implementation begins.

---

## Current State (Sprint 8 baseline)

| Layer | Status |
|---|---|
| Postgres + FTS + metadata | Done |
| pgvector MiniLM-384 | Done |
| Hybrid RRF + routing | Done |
| Cross-encoder rerank | Done |
| Query understanding | Done |
| SQL matter graph | Done |
| Answer engine + citations + abstention | Done |
| Redis retrieval cache | Live (hits: 12, misses: 40) |
| Prometheus metrics | Live at `/metrics` |
| Static UI (LEXOS SPA) | Live at `/ui` |
| API key auth | Planned (Sprint 12) |

**Retrieval scores (n=445):** Recall@10 0.5885 · Hit@10 0.9238 · MRR 0.6906 · nDCG 0.5543

---

## Roadmap — Feature Docs

Each doc defines the problem, requirements, our independent design, and the PM gate before implementation begins.

| Doc | Feature | Sprint | Priority |
|---|---|---|---|
| `01_pm_agent.md` | PM Agent — task validation & missing-link detection | Ongoing | P0 |
| `02_ui_overhaul.md` | UI overhaul — professional minimalist design system | Sprint 9 | P0 |
| `03_ask_ui.md` | Ask Firm AI — full chat interface with citation display | Sprint 9 | P0 |
| `04_retrieval_debug_ui.md` | Retrieval debug panel — pipeline transparency | Sprint 9 | P1 |
| `05_chat_history.md` | Conversation history — persistent session log | Sprint 10 | P1 |
| `06_workflows.md` | Legal workflows — reusable structured AI tasks | Sprint 10 | P1 |
| `07_tabular_review.md` | Tabular review — bulk extraction into table | Sprint 11 | P2 |
| `08_document_review.md` | Document review — clause-level edit suggestions | Sprint 11 | P2 |
| `09_library_folders.md` | Document library & folders — firm precedent vault | Sprint 12 | P2 |
| `10_model_selection.md` | Model & provider selection UI | Sprint 12 | P2 |
| `11_citation_verify.md` | Citation verification — grounding + authority check | Sprint 13 | P3 |
| `12_audit.md` | Current state audit — gaps, broken links, dead code | Now | P0 |
| `13_document_intelligence_version_control.md` | Doc intelligence + immutable VC + Review Engine (phased) | Sprint 10+ | P0 |

---

## Sprint gate rule

A sprint ships only if:
1. `python evals/retrieval_eval.py` does not regress vs `evals/last_retrieval_run.json`
2. PM agent checklist in `01_pm_agent.md` passes
3. `IP_ORIGIN_RECORD.md` updated for any Mike-inspired feature

---

## What we do NOT build (yet)

- Kafka, Neo4j, OpenSearch, agents
- Word add-in
- Supabase Auth / RLS
- Tamper-evident exports
- CourtListener integration

Add when measurements justify.
