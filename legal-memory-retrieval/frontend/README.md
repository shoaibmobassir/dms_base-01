# FirmOS frontend

Vite + React 19 + TypeScript SPA for Apex Chambers firm memory.

## Design

Wine / Ink / Paper institutional UI (see `DESIGN.md`). Shell and IA baseline from the independent FirmOS prototype at `app/code_pre`; data from live LMR APIs (`X-Member-Id` persona).

## Develop

```bash
# API (repo root of legal-memory-retrieval)
uvicorn app.api.main:app --reload --port 8000

# UI
cd frontend
npm install
npm run dev   # http://127.0.0.1:5173/ui/  (proxies /api → :8000)
```

## Build for FastAPI `/ui`

```bash
cd frontend && npm run build
```

Writes `index.html` + hashed assets into `../static/` (`emptyOutDir: false` preserves non-SPA static files).

## Routes

- **Workspace:** `/`, `/ask`, `/chat`, `/matters`, `/matters/:id`, `/projects`, `/projects/:id`, `/documents`, `/documents/:id`, `/documents/:id/history`, `/clients`, `/clients/:id`, `/people`, `/people/:id`, `/teams`, `/activity`, `/deadlines`, `/data-sources`, `/settings`
- **Intelligence & Workflows (incorporated from `code_pre`):** `/strategy`, `/experience`, `/similar-matters`, `/precedents`, `/arguments`, `/staffing`, `/timelines`, `/due-diligence`, `/knowledge-gaps`, `/transitions`, `/knowledge-management`, `/audit`, `/settings/permissions`
