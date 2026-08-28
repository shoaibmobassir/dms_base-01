"""Single source of truth for the shipped retrieval sprint."""

CURRENT_SPRINT = 8

FEATURES = {
    "vector": True,
    "rerank": True,
    "query_understanding": True,
    "graph": True,
    "llm": True,
}


def health_payload() -> dict:
    return {"status": "ok", "sprint": CURRENT_SPRINT, **FEATURES}
