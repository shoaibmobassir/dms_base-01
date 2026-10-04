# Precentis Retrieval Platform Architecture

Production-oriented parallel retrieval fabric for institutional legal memory.

> **Scope of this doc:** the hybrid retrieval fabric (`POST /api/retrieval`) and its planner / channels / fusion defaults.  
> Full platform map (Ask, Assistant, firm write layer, SPA): [`SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md).  
> Ask the Firm deep dive: [`ASK_THE_FIRM_ARCHITECTURE.md`](ASK_THE_FIRM_ARCHITECTURE.md).  
> Assistant deep dive: [`ASSISTANT_ARCHITECTURE.md`](ASSISTANT_ARCHITECTURE.md).

## Live endpoints (port 8000)

| Endpoint | Purpose |
|----------|---------|
| `POST /api/retrieval` | Hybrid retrieve — **hits only** (no answer LLM); engine v2 when `USE_ENGINE_V2=true` |
| `POST /api/retrieval/debug` | Full per-channel debugger payload |
| `POST /api/answers` | Ask the Firm — retrieve + answer + citations (sync) |
| `POST /api/answers/stream` | Ask the Firm — SSE (`evidence` → deltas → `verifying` → `final`) |
| `GET /api/answers/saved/{id}` | Reopen a stored Ask answer by id |
| `GET /api/answers/saved?q=` | Lookup stored Ask answer by question + scope |
| `GET /api/answers/history` | Recent Ask answers (reopen keys) |
| `POST /api/chat/sessions/{id}/messages` | Assistant — multi-round tool agent (SSE) |
| `GET /api/system/health` | Sprint flags, engine version, Redis |
| `GET /api/system/info` | Feature catalog + endpoint map |
| `GET /api/system/architecture` | This document |
| `GET /docs` | OpenAPI |
| `GET /ui` | LEXOS SPA |
| `GET /ui/architecture` | In-app architecture view |
| `GET /ui/ask?debug=1` | Ask view with retrieval debug expanded |

## Pipeline

**Retrieval API** (`POST /api/retrieval`) stops at ranked hits. The LLM answer stage lives on **Ask** (`/api/answers`) and Assistant tools (`ask_firm`, `search_firm_records`), not on the retrieval endpoint.

```text
Query → Understanding → Retrieval Planner
  → parallel: BM25 | Vector | Metadata | Matter | Graph seeds | Hierarchical (when planned)
  → Candidate pool (ACL + dedupe + provenance)
  → Conditional graph expansion
  → Weighted RRF fusion
  → Cross-encoder rerank (conditional)
  → top-k hits (+ debug provenance)
```

Ask / Assistant then (separately): pack evidence → LLM → citation validate → optional claim grounding.

**Independent retrieval** runs concurrently. **Graph expansion** is dependent (post-pool). **Rerank / LLM** are expensive stages gated by the planner (rerank) or by the Ask/Assistant product path (LLM).

## Production defaults

| Setting | Default | Role |
|---------|---------|------|
| `USE_ENGINE_V2` / `use_engine_v2` | `true` | Parallel async pipeline (`engine_v2.py`) |
| `FUSION_POLICY` | `p55_repair_ce_protect` | RRF weights + CE protection |
| `MATTER_SCOPE` | `hard` | Matter narrows the candidate universe (P5.6-A) |
| Embeddings | MiniLM 384-d | Local `app/embeddings` — do not swap provider without re-embed |

Do not retune global fusion without a typed ablation + `evals/retrieval_eval.py` gate.

## Engine v2 vs legacy

| | Legacy | Engine v2 (default) |
|---|---|---|
| Fan-out | keyword + metadata + graph, then vector | All independent channels including vector |
| Planner | Intent weight tweaks only | First-class `RetrievalPlan` |
| Graph | Single SQL channel | Seed (parallel) + expand (conditional) |
| Candidates | Loose dicts | `Candidate` + provenance |
| Flag | `USE_ENGINE_V2=false` | `USE_ENGINE_V2=true` |

## ACL invariant

Every channel filters permissions in SQL before ranking. Graph expansion is ACL-aware. Cache keys include member / permission / knowledge / index versions.

## Related systems

- **LEXOS** (`legal-memory-retrieval`, `:8000`) — firm corpus DMS + Ask + Assistant + retrieval fabric.
- **Doc Search** (`doc-search`, default `:8001`) — PDF-folder RAG prototype with parallel keyword+vector. Do not bind both to 8000.

## Design principles

1. Parallelize independent channels  
2. Cost-aware planner  
3. Hierarchical Matter → Document → Chunk (planner channel when selected)  
4. Graph as a second dimension, not a Neo4j hard dependency  
5. Storage behind `VectorStore` / `GraphStore` / `SearchStore`  
6. Provenance on every hit  
7. Traceable stages (`latency_ms`, OTel spans)  
8. Eval gate: `evals/retrieval_eval.py` vs `last_retrieval_run.json`  
9. Scale infrastructure only when measured  

See also: `docs/SYSTEM_ARCHITECTURE.md`, `docs/CHANGELOG.md`, `docs/NORTH_STAR.md`, `docs/plan/04_retrieval_debug_ui.md`, `docs/plan/19_ask_docket_and_stored_answers.md`.
