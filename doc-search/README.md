# Doc Search

Parallel keyword + vector RAG over a PDF folder. Companion prototype to **LEXOS** on port 8000.

**Default port: 8001** (avoids colliding with `legal-memory-retrieval`).

## Run

```bash
cd doc-search
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # if present; else fastapi uvicorn psycopg sentence-transformers
uvicorn server:app --reload --port 8001
```

- UI: http://localhost:8001/ui  
- Architecture: http://localhost:8001/docs-ui  
- Health: http://localhost:8001/health  
- Debug: `POST /debug` with `{"query":"...","k":8}`

## Related LEXOS (port 8000)

| URL | What |
|-----|------|
| http://localhost:8000/ui | Firm DMS SPA |
| http://localhost:8000/ui/ask?debug=1 | Ask + retrieval debugger |
| http://localhost:8000/ui/architecture | Retrieval fabric docs |
| http://localhost:8000/api/retrieval/debug | Full channel debugger API |

See [ARCHITECTURE.md](ARCHITECTURE.md).
