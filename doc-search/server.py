"""FastAPI server for DMS doc-search.

Reasoning:
  The /ask endpoint now returns DMS-portal-style responses with:
  - key_finding: executive summary
  - primary_document: strongest match with matter_id, tags, document_type
  - supporting_documents: additional matches
  - Per-channel latency breakdown from parallel retrieval

  Port changed from 8001 → 8000 as requested.
  Retrieval returns (hits, latency) tuple from the parallelized search.
"""
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

app = FastAPI(title="DMS Doc Search", version="2.0.0")

STATIC_DIR = Path(__file__).parent / "static"


# ── models ────────────────────────────────────────────────────────────────────


class AskRequest(BaseModel):
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

    # Build primary_document from LLM output or from top hit
    primary = _build_doc_ref(result.get("primary_document"))
    if not primary and hits:
        primary = _hit_to_doc_ref(hits[0])

    # Build supporting_documents from LLM output or from remaining hits
    supporting_raw = result.get("supporting_documents") or []
    supporting = [_build_doc_ref(d) for d in supporting_raw if d]
    if not supporting and len(hits) > 1:
        # Deduplicate by filename
        seen_files = {primary["filename"]} if primary else set()
        for h in hits[1:5]:
            fname = h.get("filename", "")
            if fname not in seen_files:
                seen_files.add(fname)
                supporting.append(_hit_to_doc_ref(h))

    # Merge latency from parallel search + LLM
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
        hits=[
            {
                "chunk_id": h.get("chunk_id", ""),
                "filename": h.get("filename", ""),
                "page_number": h.get("page_number", 0),
                "text": h.get("text", ""),
                "matter_id": h.get("matter_id"),
                "document_type": h.get("document_type"),
                "tags": h.get("tags") if isinstance(h.get("tags"), list) else [],
                "rerank_score": h.get("rerank_score"),
                "channel": h.get("channel"),
            }
            for h in hits
        ],
        latency_ms=combined_latency,
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
    return {"status": "ok", "version": "2.0.0"}


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
