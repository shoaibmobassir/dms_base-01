import time

from fastapi import APIRouter, Depends, Response

from app.api.schemas import RetrieveRequest
from app.api.hits import hit_payload_highlighted
from app.auth.deps import resolve_member
from app.config import settings
from app.db.connection import connect
from app.observability.metrics import (
    REQUEST_TOTAL,
    RETRIEVAL_LATENCY,
    record_latency_breakdown,
)
from app.observability.tracing import span
from app.query.understand import understand
from app.retrieval.engine import retrieve
from app.sprint import CURRENT_SPRINT

router = APIRouter(tags=["retrieval"])


@router.post("")
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
    formatted_hits = [hit_payload_highlighted(h, body.query) for h in hits]
    return {
        "service": "retrieval",
        "query": body.query,
        "sprint": CURRENT_SPRINT,
        "understanding": parsed.to_dict(),
        "member_id": member_id,
        "latency_ms": latency,
        "total_hits": len(formatted_hits),
        "hits": formatted_hits,
    }


@router.post("/debug")
async def debug_endpoint(
    body: RetrieveRequest,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    """Retrieval debugger — full per-stage diagnostic breakdown.

    Returns detailed info about what each channel found, how dedup/fusion worked,
    graph expansion results, reranking impact, and complete provenance per result.
    """
    from app.retrieval.debugger import debug_retrieval

    REQUEST_TOTAL.labels(endpoint="retrieve_debug").inc()
    result = await debug_retrieval(body.query, member_id, k=body.k or 20)
    return result


@router.get("/health")
def retrieval_health() -> dict:
    from app.db.pool import pool_stats

    return {
        "service": "retrieval",
        "status": "ok",
        "pool": pool_stats(),
    }

