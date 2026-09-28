import json
import time

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.schemas import AskRequest
from app.api.hits import hit_payload_highlighted
from app.answers.format import format_dms_response
from app.km import ask_history
from app.km.answer import ask_the_firm, ask_the_firm_stream
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
logger = logging.getLogger(__name__)


@router.post("")
def ask_endpoint(
    body: AskRequest,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    _limit(member_id)
    t0 = time.perf_counter()
    scope = body.scope.model_dump() if body.scope else None
    _remember(body.query, scope, member_id)
    with span("ask", {"query": body.query[:120], "member_id": member_id or ""}):
        with connect() as conn:
            result = ask_the_firm(conn, body.query, member_id, scope)
    return _publish(result, body, scope, member_id, time.perf_counter() - t0)


@router.post("/stream")
def ask_stream_endpoint(
    body: AskRequest,
    member_id: str | None = Depends(resolve_member),
) -> StreamingResponse:
    """Server-sent events: ``evidence``, ``key_finding``, ``delta``*, then ``final``.

    ``final.result`` has exactly the shape of ``POST /api/answers``.
    """
    _limit(member_id)
    scope = body.scope.model_dump() if body.scope else None
    _remember(body.query, scope, member_id)

    def events():
        t0 = time.perf_counter()
        try:
            with connect() as conn:
                for ev in ask_the_firm_stream(conn, body.query, member_id, scope):
                    if ev["type"] == "evidence":
                        hits = ev.pop("hits") or []
                        ev["sources"] = [hit_payload_highlighted(h, body.query, max_chars=380) for h in hits[:8]]
                    elif ev["type"] == "final":
                        ev["result"] = _publish(ev["result"], body, scope, member_id, time.perf_counter() - t0)
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
        except Exception as exc:  # the stream must end with a parseable event
            yield f"data: {json.dumps({'type': 'error', 'message': type(exc).__name__})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _remember(query: str, scope: dict | None, member_id: str | None) -> None:
    """Add the question to the member's recent list; never fails the answer."""
    try:
        with connect() as conn:
            ask_history.record(conn, member_id, query, scope)
    except Exception as exc:
        logger.warning("[ask] could not save question history: %s", type(exc).__name__)


@router.get("/history")
def ask_history_list(
    limit: int = Query(30, ge=1, le=100),
    member_id: str | None = Depends(resolve_member),
) -> dict:
    """The caller's recent Ask the Firm questions, newest first."""
    with connect() as conn:
        items = ask_history.recent(conn, member_id, limit)
    return {"items": items}


@router.delete("/history/{entry_id}", status_code=204)
def ask_history_delete(entry_id: str, member_id: str | None = Depends(resolve_member)) -> None:
    with connect() as conn:
        if not ask_history.remove(conn, member_id, entry_id):
            raise HTTPException(status_code=404, detail="Question not found")


@router.delete("/history", status_code=204)
def ask_history_clear(member_id: str | None = Depends(resolve_member)) -> None:
    with connect() as conn:
        ask_history.remove(conn, member_id)


def _limit(member_id: str | None) -> None:
    check_rate_limit(
        f"ask:{member_id or 'anon'}",
        limit=settings.rate_limit_ask_per_minute,
        window_seconds=60.0,
    )
    REQUEST_TOTAL.labels(endpoint="ask").inc()


def _publish(result: dict, body: AskRequest, scope: dict | None, member_id: str | None, elapsed: float) -> dict:
    """Metrics, DMS envelope fields and audit for one Ask answer."""
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
        dms = format_dms_response(body.query, result, _cited_first(hits, result.get("citations") or []), latency)
        result["key_finding"] = result.get("key_finding") or dms.get("key_finding", "")
        result["structured_citations"] = dms.get("structured_citations", [])
        result["sources"] = dms.get("sources", [])
        result["matchedMatters"] = _matched_matters(result) or dms.get("matchedMatters", [])
        result["tags"] = dms.get("tags", [])
    except Exception:
        pass  # fail gracefully — DMS fields are additive

    result["service"] = "answers"
    cited = sorted({str(c.get("document_id")) for c in result.get("sources") or [] if c.get("document_id")})
    audit.record("ask", member_id=member_id, object_type="question", detail={
        "prompt": body.query, "scope": scope, "abstained": bool(result.get("abstained")),
        "cited_documents": cited, "provider": result.get("provider"),
    })
    return result


def _cited_first(hits: list[dict], citations: list[str]) -> list[dict]:
    """Order passages so the documents the answer cites become the sources."""
    rank = {c.upper(): i for i, c in enumerate(citations)}
    return sorted(hits, key=lambda h: rank.get(str(h.get("document_id") or "").upper(), len(rank)))


def _matched_matters(result: dict) -> list[dict]:
    """The KM panel's ranked matters in the DMS portal shape (no invented similarity score)."""
    return [
        {
            "matter_id": m["matter_id"], "matter_code": m["matter_code"], "title": m["title"],
            "client_name": m.get("client_name"), "practice_area": m.get("practice_area"),
            "document_count": m.get("document_count", 0), "relation": m.get("relation"), "why": m.get("why"),
        }
        for m in (result.get("panel") or {}).get("matters") or []
    ]


@router.get("/health")
def answers_health() -> dict:
    return {"service": "answers", "status": "ok"}

