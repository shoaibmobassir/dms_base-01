# LEXOS Retrieval Platform Architecture

Production-oriented parallel retrieval fabric for institutional legal memory.

## Live endpoints (port 8000)

| Endpoint | Purpose |
|----------|---------|
| `POST /api/retrieval` | Hybrid retrieve (engine v2 when `USE_ENGINE_V2=true`) |
| `POST /api/retrieval/debug` | Full per-channel debugger payload |
| `POST /api/answers` | Ask the Firm — retrieve + answer + citations |
| `GET /api/system/health` | Sprint flags, engine version, Redis |
| `GET /api/system/info` | Feature catalog + endpoint map |
| `GET /api/system/architecture` | This document |
| `GET /docs` | OpenAPI |
| `GET /ui` | LEXOS SPA |
| `GET /ui/architecture` | In-app architecture view |
| `GET /ui/ask?debug=1` | Ask view with retrieval debug expanded |

## Pipeline

```text
Query → Understanding → Retrieval Planner
  → parallel: BM25 | Vector | Metadata | Matter | Graph seeds
  → Candidate pool (ACL + dedupe + provenance)
  → Conditional graph expansion
  → Weighted RRF fusion
  → Cross-encoder rerank (conditional)
  → Context + LLM answer + citations
```

**Independent retrieval** runs concurrently. **Graph expansion** is dependent (post-pool). **Rerank / LLM** are expensive stages gated by the planner.

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

- **LEXOS** (`legal-memory-retrieval`, `:8000`) — firm corpus DMS + Ask + retrieval fabric.
- **Doc Search** (`doc-search`, default `:8001`) — PDF-folder RAG prototype with parallel keyword+vector. Do not bind both to 8000.

## Design principles

1. Parallelize independent channels  
2. Cost-aware planner  
3. Hierarchical Matter → Document → Chunk (roadmap)  
4. Graph as a second dimension, not a Neo4j hard dependency  
5. Storage behind `VectorStore` / `GraphStore` / `SearchStore`  
6. Provenance on every hit  
7. Traceable stages (`latency_ms`, OTel spans)  
8. Eval gate: `evals/retrieval_eval.py` vs `last_retrieval_run.json`  
9. Scale infrastructure only when measured  

See also: `docs/CHANGELOG.md`, `docs/NORTH_STAR.md`, `docs/plan/04_retrieval_debug_ui.md`.
