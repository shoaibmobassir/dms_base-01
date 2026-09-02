from fastapi import APIRouter, Response

from app.cache.redis import cache_stats
from app.observability.metrics import prometheus_response
from app.sprint import CURRENT_SPRINT, health_payload

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    payload = health_payload()
    payload["service"] = "system"
    payload["gateway"] = "lexos"
    payload["cache"] = cache_stats()
    return payload


@router.get("/metrics")
def metrics() -> Response:
    data, content_type = prometheus_response()
    return Response(content=data, media_type=content_type)


@router.get("/info")
def system_info() -> dict:
    return {
        "service": "system",
        "sprint": CURRENT_SPRINT,
        "description": "Health, metrics, and platform metadata",
    }
