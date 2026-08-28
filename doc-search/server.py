from __future__ import annotations

import time
import urllib.parse
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from pydantic import BaseModel

from config import settings
from llm import complete
from search import retrieve

app = FastAPI(title="Doc Search", version="1.0.0")

STATIC_DIR = Path(__file__).parent / "static"


# ── models ────────────────────────────────────────────────────────────────────


class AskRequest(BaseModel):
    query: str
    k: int = 8


class Citation(BaseModel):
    file: str
    page: int
    snippet: str


class Hit(BaseModel):
    chunk_id: str
    filename: str
    page_number: int
    text: str
    rerank_score: float | None = None
    channel: str | None = None


class AskResponse(BaseModel):
    answer: str
    abstained: bool
    citations: list[dict]
    hits: list[dict]
    latency_ms: dict
    provider: str | None = None
    llm_errors: list[str] | None = None


# ── endpoints ─────────────────────────────────────────────────────────────────


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    t_total = time.perf_counter()

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        t0 = time.perf_counter()
        hits = retrieve(conn, req.query, k=req.k)
        t_retrieve = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    result = complete(req.query, hits)
    t_llm = (time.perf_counter() - t0) * 1000

    return AskResponse(
        answer=result["answer"],
        abstained=result["abstain"],
        citations=result.get("citations") or [],
        hits=[
            {
                "chunk_id": h["chunk_id"],
                "filename": h["filename"],
                "page_number": h["page_number"],
                "text": h["text"],
                "rerank_score": h.get("rerank_score"),
                "channel": h.get("channel"),
            }
            for h in hits
        ],
        latency_ms={
            "retrieve_ms": round(t_retrieve, 1),
            "llm_ms": round(t_llm, 1),
            "total_ms": round((time.perf_counter() - t_total) * 1000, 1),
        },
        provider=result.get("provider"),
        llm_errors=result.get("llm_errors"),
    )


@app.get("/doc/serve/{filename:path}")
def serve_doc(filename: str) -> StreamingResponse:
    safe_name = urllib.parse.unquote(filename)
    # prevent path traversal
    if ".." in safe_name or safe_name.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    pdf_path = Path(settings.docs_dir) / safe_name
    if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="Document not found")

    def _iter():
        with open(pdf_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(
        _iter(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ui", response_class=HTMLResponse)
@app.get("/ui/", response_class=HTMLResponse)
def ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/")
def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/ui")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
