import time

from fastapi import APIRouter, Depends

from app.api.schemas import AskRequest
from app.api.hits import hit_payload_highlighted
from app.answers.format import format_dms_response
from app.answers.generate import answer_question
from app.audit import events as audit
from app.auth.deps import resolve_member
from app.config import settings
from app.db.connection import connect
from app.observability.metrics import (
    ABSTENTIONS,
    REQUEST_TOTAL,
    RETRIEVAL_LATENCY,
    record_latency_breakdown,
)
from app.observability.tracing import span
from app.resilience.rate_limit import check_rate_limit

router = APIRouter(tags=["answers"])


@router.post("")
def ask_endpoint(
    body: AskRequest,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    check_rate_limit(
        f"ask:{member_id or 'anon'}",
        limit=settings.rate_limit_ask_per_minute,
        window_seconds=60.0,
    )
    REQUEST_TOTAL.labels(endpoint="ask").inc()
    t0 = time.perf_counter()
    with span("ask", {"query": body.query[:120], "member_id": member_id or ""}):
        with connect() as conn:
            result = answer_question(conn, body.query, member_id, k=body.k)
    elapsed = time.perf_counter() - t0
    RETRIEVAL_LATENCY.labels(endpoint="ask").observe(elapsed)
    latency = result.get("latency_ms", {})
    record_latency_breakdown(
        latency,
        result.get("provider", "unknown"),
        elapsed_ms=elapsed * 1000,
    )
    if result.get("abstained"):
        ABSTENTIONS.labels(reason=result.get("reason", "unknown")).inc()
    hits = result.pop("hits")
    result["hits"] = [hit_payload_highlighted(h, body.query, max_chars=380) for h in hits]

    # ── DMS portal format: add structured fields ─────────────────────
    try:
        dms = format_dms_response(body.query, result, hits, latency)
        result["key_finding"] = dms.get("key_finding", "")
        result["structured_citations"] = dms.get("structured_citations", [])
        result["sources"] = dms.get("sources", [])
        result["matchedMatters"] = dms.get("matchedMatters", [])
        result["tags"] = dms.get("tags", [])
    except Exception:
        pass  # fail gracefully — DMS fields are additive

    result["service"] = "answers"
    cited = sorted({str(c.get("document_id")) for c in result.get("sources") or [] if c.get("document_id")})
    audit.record("ask", member_id=member_id, object_type="question", detail={
        "prompt": body.query, "abstained": bool(result.get("abstained")),
        "cited_documents": cited, "provider": result.get("provider"),
    })
    return result


@router.get("/health")
def answers_health() -> dict:
    return {"service": "answers", "status": "ok"}

