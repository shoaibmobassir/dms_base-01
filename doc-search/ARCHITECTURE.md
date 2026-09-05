# Doc Search — Architecture

PDF-folder RAG companion to **LEXOS** (`legal-memory-retrieval` on port **8000**).

## Ports

| App | Port | Role |
|-----|------|------|
| LEXOS | **8000** | Firm corpus DMS + parallel retrieval fabric (engine v2) |
| Doc Search | **8001** (default) | PDF directory ingest + keyword/vector RAG UI |

Do not bind both services to 8000.

## Pipeline

```text
Query
  ├─ keyword_search (Postgres FTS)     ─┐
  └─ vector_search (MiniLM + pgvector) ─┼─ ThreadPoolExecutor
                                         ▼
                                    RRF fusion
                                         ▼
                                  Cross-encoder rerank
                                         ▼
                                   LLM / extractive answer
```

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/ask` | Retrieve + answer + latency breakdown |
| `POST` | `/debug` | Retrieval-only channel debug (no LLM) |
| `GET` | `/health` | Status + related LEXOS links |
| `GET` | `/docs-ui` | This architecture (HTML) |
| `GET` | `/architecture` | This architecture (Markdown) |
| `GET` | `/ui` | Ask UI with PDF viewer |
| `GET` | `/doc/serve/{filename}` | Inline PDF |

## Architecture simulator (`architecture_sim/`)

Production-architecture **simulator** (not another RAG demo). Demonstrates:

- Immutable `Document` → `Version` → blocks/chunks (PDF is one representation)
- Folder-preserving parallel ingest + object-store URIs
- Content anchors (block + offsets + quote hash), not PDF coordinates
- Hierarchical retrieval (matter → document → chunk) + BM25/vector/RRF
- Review Engine Map → Reduce → Verify → `Finding` + bidirectional annotations
- Version lexical + semantic diff; version-keyed cache; OTel-style traces

```bash
cd doc-search
python scripts/run_architecture_sim.py --docs 50 --pages 20
pytest tests/test_architecture_sim_e2e.py -q
```

## Relation to LEXOS engine v2

Doc Search is a **simpler two-channel** prototype (keyword + vector).  
LEXOS adds planner, metadata, matter, graph seed/expand, provenance, ACL, and Ask Firm UI at:

- http://localhost:8000/ui  
- http://localhost:8000/ui/ask?debug=1  
- http://localhost:8000/ui/architecture  

## Quick start

```bash
cd doc-search
source .venv/bin/activate   # or create one
uvicorn server:app --reload --port 8001
```

Open http://localhost:8001/ui and http://localhost:8001/docs-ui.
