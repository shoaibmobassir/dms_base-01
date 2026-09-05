"""FastAPI server for DMS doc-search (PDF-folder RAG prototype).

Runs beside LEXOS. Default port is **8001** so it does not collide with
legal-memory-retrieval on **8000**.

Endpoints:
  POST /ask          — parallel keyword+vector retrieve + LLM answer
  POST /debug        — retrieval-only channel/latency breakdown
  GET  /health       — status + retrieval architecture flags
  GET  /docs-ui      — architecture documentation (HTML)
  GET  /architecture — architecture markdown
  GET  /doc/serve/*  — PDF streaming
  GET  /ui           — Ask UI with latency chips + channel badges
"""
from __future__ import annotations

import time
import urllib.parse
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from pydantic import BaseModel

from config import settings
from llm import complete
from search import retrieve

app = FastAPI(
    title="DMS Doc Search",
    version="2.1.0",
    description="PDF-folder parallel retrieval prototype (keyword + vector → RRF → rerank). Companion to LEXOS on :8000.",
)

STATIC_DIR = Path(__file__).parent / "static"
ARCH_PATH = Path(__file__).parent / "ARCHITECTURE.md"


# ── models ────────────────────────────────────────────────────────────────────


class AskRequest(BaseModel):
    query: str
    k: int = 8


class DebugRequest(BaseModel):
    query: str
    k: int = 8


class DocumentRef(BaseModel):
    filename: str
    page: int
    matter_id: str | None = None
    document_type: str | None = None
    tags: list[str] = []
    snippet: str = ""
    open_document_url: str | None = None


class Citation(BaseModel):
    file: str
    page: int
    snippet: str


class HitDetail(BaseModel):
    chunk_id: str
    filename: str
    page_number: int
    text: str
    matter_id: str | None = None
    document_type: str | None = None
    tags: list[str] = []
    rerank_score: float | None = None
    channel: str | None = None


class AskResponse(BaseModel):
    answer: str
    key_finding: str
    abstained: bool
    primary_document: DocumentRef | None = None
    supporting_documents: list[DocumentRef] = []
    citations: list[dict]
    hits: list[dict]
    latency_ms: dict
    provider: str | None = None
    llm_errors: list[str] | None = None


# ── helpers ───────────────────────────────────────────────────────────────────


def _build_doc_ref(doc_data: dict | None) -> dict | None:
    """Build a DocumentRef dict from LLM output or hit data."""
    if not doc_data:
        return None
    filename = doc_data.get("filename", "")
    return {
        "filename": filename,
        "page": doc_data.get("page", 1),
        "matter_id": doc_data.get("matter_id"),
        "document_type": doc_data.get("document_type"),
        "tags": doc_data.get("tags") or [],
        "snippet": doc_data.get("snippet", ""),
        "open_document_url": f"/doc/serve/{urllib.parse.quote(filename)}" if filename else None,
    }


def _hit_to_doc_ref(h: dict) -> dict:
    """Convert a retrieval hit to a DocumentRef dict."""
    filename = h.get("filename", "")
    return {
        "filename": filename,
        "page": h.get("page_number", 1),
        "matter_id": h.get("matter_id"),
        "document_type": h.get("document_type"),
        "tags": h.get("tags") if isinstance(h.get("tags"), list) else [],
        "snippet": (h.get("text") or "")[:120],
        "open_document_url": f"/doc/serve/{urllib.parse.quote(filename)}" if filename else None,
    }


def _hit_payload(h: dict) -> dict:
    return {
        "chunk_id": h.get("chunk_id", ""),
        "filename": h.get("filename", ""),
        "page_number": h.get("page_number", 0),
        "text": h.get("text", ""),
        "matter_id": h.get("matter_id"),
        "document_type": h.get("document_type"),
        "tags": h.get("tags") if isinstance(h.get("tags"), list) else [],
        "rerank_score": h.get("rerank_score"),
        "channel": h.get("channel"),
        "score": h.get("score") or h.get("rerank_score"),
    }


# ── endpoints ─────────────────────────────────────────────────────────────────


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    t_total = time.perf_counter()

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        t0 = time.perf_counter()
        hits, search_latency = retrieve(conn, req.query, k=req.k)
        t_retrieve = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    result = complete(req.query, hits)
    t_llm = (time.perf_counter() - t0) * 1000

    primary = _build_doc_ref(result.get("primary_document"))
    if not primary and hits:
        primary = _hit_to_doc_ref(hits[0])

    supporting_raw = result.get("supporting_documents") or []
    supporting = [_build_doc_ref(d) for d in supporting_raw if d]
    if not supporting and len(hits) > 1:
        seen_files = {primary["filename"]} if primary else set()
        for h in hits[1:5]:
            fname = h.get("filename", "")
            if fname not in seen_files:
                seen_files.add(fname)
                supporting.append(_hit_to_doc_ref(h))

    combined_latency = {
        **search_latency,
        "retrieve_ms": round(t_retrieve, 1),
        "llm_ms": round(t_llm, 1),
        "total_ms": round((time.perf_counter() - t_total) * 1000, 1),
    }

    return AskResponse(
        answer=result.get("answer", ""),
        key_finding=result.get("key_finding", ""),
        abstained=result.get("abstain", False),
        primary_document=primary,
        supporting_documents=[s for s in supporting if s],
        citations=result.get("citations") or [],
        hits=[_hit_payload(h) for h in hits],
        latency_ms=combined_latency,
        provider=result.get("provider"),
        llm_errors=result.get("llm_errors"),
    )


@app.post("/debug")
def debug_retrieval(req: DebugRequest) -> dict:
    """Retrieval debugger — channel counts, latency, top hits (no LLM)."""
    t0 = time.perf_counter()
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        hits, search_latency = retrieve(conn, req.query, k=req.k)

    by_channel: dict[str, list[dict]] = {}
    for h in hits:
        ch = h.get("channel") or "fused"
        by_channel.setdefault(ch, []).append(_hit_payload(h))

    return {
        "service": "doc-search-debug",
        "query": req.query,
        "architecture": "parallel keyword + vector → RRF → cross-encoder",
        "latency_ms": {
            **search_latency,
            "total_ms": round((time.perf_counter() - t0) * 1000, 1),
        },
        "channel_counts": {ch: len(rows) for ch, rows in by_channel.items()},
        "channels": {
            ch: {
                "count": len(rows),
                "top_3": [
                    {
                        "filename": r.get("filename"),
                        "page": r.get("page_number"),
                        "score": r.get("rerank_score") or r.get("score"),
                        "snippet": (r.get("text") or "")[:160],
                    }
                    for r in rows[:3]
                ],
            }
            for ch, rows in by_channel.items()
        },
        "hits": [_hit_payload(h) for h in hits],
    }


@app.get("/doc/serve/{filename:path}")
def serve_doc(filename: str) -> StreamingResponse:
    safe_name = urllib.parse.unquote(filename)
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
    return {
        "status": "ok",
        "version": "2.1.0",
        "service": "doc-search",
        "port": settings.port,
        "parallel_retrieval": True,
        "channels": ["keyword", "vector"],
        "fusion": "rrf",
        "rerank": True,
        "related": {
            "lexos_ui": "http://localhost:8000/ui",
            "lexos_architecture": "http://localhost:8000/ui/architecture",
            "lexos_ask_debug": "http://localhost:8000/ui/ask?debug=1",
        },
    }


@app.get("/architecture", response_class=PlainTextResponse)
def architecture_markdown() -> PlainTextResponse:
    if not ARCH_PATH.exists():
        return PlainTextResponse("ARCHITECTURE.md missing", status_code=404)
    return PlainTextResponse(ARCH_PATH.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")


@app.get("/docs-ui", response_class=HTMLResponse)
def docs_ui() -> HTMLResponse:
    body = ARCH_PATH.read_text(encoding="utf-8") if ARCH_PATH.exists() else "# Missing ARCHITECTURE.md"
    # Escape for HTML <pre> — keep readable
    safe = (
        body.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Doc Search — Architecture</title>
<style>
  body {{ font-family: ui-sans-serif, system-ui, sans-serif; background:#0f1117; color:#e2e8f0; margin:0; padding:24px; }}
  a {{ color:#6c8fff; }}
  pre {{ white-space:pre-wrap; background:#1a1d27; border:1px solid #2e3148; border-radius:10px; padding:18px; line-height:1.5; }}
  .nav {{ margin-bottom:16px; display:flex; gap:12px; flex-wrap:wrap; }}
</style></head><body>
<div class="nav">
  <a href="/ui">← Ask UI</a>
  <a href="/architecture">Raw Markdown</a>
  <a href="/health">Health</a>
  <a href="http://localhost:8000/ui/architecture" target="_blank" rel="noopener">LEXOS Architecture (:8000)</a>
</div>
<pre>{safe}</pre>
</body></html>"""
    return HTMLResponse(html)


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
