from pathlib import Path

from fastapi import APIRouter, Response
from fastapi.responses import PlainTextResponse

from app.cache.redis import cache_stats
from app.config import settings
from app.observability.metrics import prometheus_response
from app.sprint import CURRENT_SPRINT, FEATURES, health_payload

router = APIRouter(tags=["system"])

_DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"


@router.get("/health")
def health() -> dict:
    payload = health_payload()
    payload["service"] = "system"
    payload["gateway"] = "lexos"
    payload["cache"] = cache_stats()
    payload["use_engine_v2"] = settings.use_engine_v2
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
        "description": "LEXOS legal institutional memory — parallel retrieval fabric",
        "retrieval_engine": "v2" if settings.use_engine_v2 else "legacy",
        "use_engine_v2": settings.use_engine_v2,
        "features": FEATURES,
        "endpoints": {
            "retrieve": "POST /api/retrieval",
            "retrieve_debug": "POST /api/retrieval/debug",
            "ask": "POST /api/answers",
            "architecture": "GET /api/system/architecture",
            "openapi": "/docs",
            "ui": "/ui",
            "ui_architecture": "/ui/architecture",
        },
        "index_version": settings.index_version,
        "embedding_version": settings.embedding_version,
        "knowledge_version": settings.knowledge_version,
    }


@router.get("/architecture")
def architecture_doc() -> PlainTextResponse:
    """Serve the retrieval-platform architecture markdown for the UI docs view."""
    path = _DOCS_DIR / "ARCHITECTURE.md"
    if not path.exists():
        return PlainTextResponse("Architecture documentation not found.", status_code=404)
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")
