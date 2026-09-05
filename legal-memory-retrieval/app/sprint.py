"""Single source of truth for the shipped retrieval sprint."""

from app.config import settings

CURRENT_SPRINT = 9

FEATURES = {
    "vector": True,
    "rerank": True,
    "query_understanding": True,
    "graph": True,
    "llm": True,
    "engine_v2": bool(settings.use_engine_v2),
    "parallel_retrieval": True,
    "retrieval_planner": True,
    "graph_expansion": True,
    "redis_cache": bool(settings.redis_url),
}


def health_payload() -> dict:
    return {
        "status": "ok",
        "sprint": CURRENT_SPRINT,
        "retrieval_engine": "v2" if settings.use_engine_v2 else "legacy",
        **FEATURES,
    }
