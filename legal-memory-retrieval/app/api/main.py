from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.answers.generate import answer_question
from app.auth.deps import resolve_member
from app.cache.redis import cache_stats
from app.db.connection import connect
from app.observability.metrics import (
    ABSTENTIONS,
    REQUEST_TOTAL,
    RETRIEVAL_LATENCY,
    prometheus_response,
    record_latency_breakdown,
)
from app.observability.tracing import setup_tracing, span
from app.query.understand import understand
from app.retrieval.engine import retrieve
from app.sprint import CURRENT_SPRINT, health_payload

import os
import time


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_tracing()
    yield


app = FastAPI(title="Legal memory retrieval", version="0.5.0", lifespan=lifespan)

# Serve frontend if static dir exists
_static_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static")
if os.path.isdir(_static_dir):
    app.mount("/ui", StaticFiles(directory=_static_dir, html=True), name="static")


class RetrieveRequest(BaseModel):
    query: str
    k: int = 20


class AskRequest(BaseModel):
    query: str
    k: int = 10


def _hit_payload(hit: dict) -> dict:
    return {
        "document_id": hit["document_id"],
        "matter_id": hit["matter_id"],
        "title": hit["title"],
        "document_type": hit["document_type"],
        "chunk_id": hit.get("chunk_id"),
        "score": hit.get("rerank_score", hit.get("fused_score")),
        "channel": hit.get("channel"),
        "snippet": (hit.get("text") or "")[:300],
    }


@app.get("/")
def root() -> dict:
    return {
        "service": "legal-memory-retrieval",
        "sprint": CURRENT_SPRINT,
        "docs": "/docs",
        "health": "/health",
        "retrieve": "POST /retrieve",
        "ask": "POST /ask",
        "ui": "/ui",
        "metrics": "GET /metrics",
    }


@app.get("/health")
def health() -> dict:
    payload = health_payload()
    payload["cache"] = cache_stats()
    return payload


@app.get("/metrics")
def metrics() -> Response:
    data, content_type = prometheus_response()
    return Response(content=data, media_type=content_type)


@app.post("/retrieve")
def retrieve_endpoint(
    body: RetrieveRequest,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    REQUEST_TOTAL.labels(endpoint="retrieve").inc()
    t0 = time.perf_counter()
    with span("retrieve", {"query": body.query[:120], "member_id": member_id or ""}):
        parsed = understand(body.query)
        with connect() as conn:
            hits, latency = retrieve(conn, body.query, member_id, k=body.k)
    elapsed = time.perf_counter() - t0
    RETRIEVAL_LATENCY.labels(endpoint="retrieve").observe(elapsed)
    record_latency_breakdown(latency, "retrieve")
    return {
        "query": body.query,
        "sprint": CURRENT_SPRINT,
        "understanding": parsed.to_dict(),
        "member_id": member_id,
        "latency_ms": latency,
        "hits": [_hit_payload(h) for h in hits],
    }


@app.post("/ask")
def ask_endpoint(
    body: AskRequest,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    REQUEST_TOTAL.labels(endpoint="ask").inc()
    t0 = time.perf_counter()
    with span("ask", {"query": body.query[:120], "member_id": member_id or ""}):
        with connect() as conn:
            result = answer_question(conn, body.query, member_id, k=body.k)
    elapsed = time.perf_counter() - t0
    RETRIEVAL_LATENCY.labels(endpoint="ask").observe(elapsed)
    latency = result.get("latency_ms", {})
    record_latency_breakdown(latency, result.get("provider", "unknown"))
    if result.get("abstained"):
        ABSTENTIONS.labels(reason=result.get("reason", "unknown")).inc()
    hits = result.pop("hits")
    result["hits"] = [_hit_payload(h) for h in hits]
    return result
