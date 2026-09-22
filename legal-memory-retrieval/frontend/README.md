# FirmOS Frontend

Vite + React + TypeScript UI for Legal Memory Retrieval.

## Design

Visual system: **FirmOS Wine / Ink / Paper** — see [`DESIGN.md`](./DESIGN.md).
Tokens live in `src/styles/tokens.css`.

Legacy vanilla SPA archived at `../static/_legacy/`.

## Develop

```bash
# API on :8000
cd .. && uvicorn app.api.main:app --reload --port 8000

# UI on :5173 (proxies /api → :8000)
cd frontend && npm run dev
# open http://127.0.0.1:5173/ui/
```

## Production build (served by FastAPI at `/ui`)

```bash
npm run build
# writes to ../static/index.html + ../static/assets/
```

Word taskpane (`../static/word-taskpane.html`) is preserved across builds.
