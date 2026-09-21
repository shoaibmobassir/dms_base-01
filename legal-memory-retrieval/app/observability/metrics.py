from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from app.db.pool import pool_stats

REQUEST_TOTAL = Counter(
    "retrieval_requests_total",
    "Total retrieve/ask requests",
    ["endpoint"],
)

RETRIEVAL_LATENCY = Histogram(
    "retrieval_latency_seconds",
    "End-to-end retrieval latency",
    ["endpoint"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0),
)

# Bounded labels only: intent (~8) × scoped (2). No query, document, or matter ids.
QUERY_LATENCY = Histogram(
    "retrieval_query_latency_seconds",
    "Retrieval latency by analyser intent and whether matter scope resolved",
    ["intent", "scoped"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0),
)

CHANNEL_LATENCY = Histogram(
    "retrieval_channel_latency_seconds",
    "Per-channel search latency",
    ["channel"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0),
)

STAGE_LATENCY = Histogram(
    "retrieval_stage_latency_seconds",
    "Named retrieval stage latency",
    ["stage"],
    buckets=(0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0),
)

RERANK_LATENCY = Histogram(
    "rerank_latency_seconds",
    "Cross-encoder rerank latency",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0),
)

LLM_LATENCY = Histogram(
    "llm_latency_seconds",
    "LLM answer generation latency",
    ["provider"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0),
)

CACHE_HITS = Counter(
    "retrieval_cache_hits_total",
    "Cache hits by tier",
    ["tier"],
)
CACHE_MISSES = Counter(
    "retrieval_cache_misses_total",
    "Cache misses by tier",
    ["tier"],
)

MATTER_SCOPE_RESOLVED = Counter(
    "matter_scope_resolved_total",
    "Hard matter scope resolved at least one matter",
)
MATTER_SCOPE_UNSCOPED = Counter(
    "matter_scope_unscoped_total",
    "Hard matter scope fell back to an unscoped search",
)

SLOW_QUERIES = Counter(
    "retrieval_slow_queries_total",
    "Retrieve or ask calls slower than 2 seconds",
    ["intent"],
)

QUERY_CLASS = Counter(
    "retrieval_query_class_total",
    "Metric label for argument or title boilerplate; not a planner intent",
    ["query_class"],
)

POOL_WAITING = Gauge(
    "db_pool_requests_waiting",
    "DB pool requests waiting for a connection",
)

ABSTENTIONS = Counter(
    "answer_abstentions_total",
    "Answers that abstained",
    ["reason"],
)

CHAT_TURNS = Counter(
    "chat_turns_total",
    "Chat agent turns finished",
    ["outcome"],
)

CHAT_TOOL_CALLS = Counter(
    "chat_tool_calls_total",
    "Chat tool invocations",
    ["tool"],
)

CHAT_TOOL_TIMEOUTS = Counter(
    "chat_tool_timeouts_total",
    "Chat tool calls that hit the wall clock",
    ["tool"],
)

CHAT_CITATION_RESULTS = Counter(
    "chat_citation_results_total",
    "Citation verification outcomes",
    ["result"],
)

_CHANNEL_KEYS = frozenset({"keyword", "metadata", "vector", "graph", "bm25"})
_STAGE_MS = {
    "understand": "understand",
    "matter_scope_ms": "matter_scope",
    "parallel_wall_ms": "parallel_wall",
    "fusion": "fusion",
    "rerank": "rerank",
}
_SLOW_MS = 2000.0
_QUERY_CLASSES = frozenset({"argument_support", "document_title", "other"})


def observe_pool_waiting() -> None:
    waiting = pool_stats().get("requests_waiting")
    if isinstance(waiting, int):
        POOL_WAITING.set(waiting)


def record_embedding_cache(hit: bool) -> None:
    if hit:
        CACHE_HITS.labels(tier="l1").inc()
    else:
        CACHE_MISSES.labels(tier="l1").inc()


def record_latency_breakdown(
    latency_ms: dict,
    endpoint: str,
    elapsed_ms: float | None = None,
) -> None:
    observe_pool_waiting()
    intent = str(latency_ms.get("intent") or "unknown")
    scoped = "scoped" if latency_ms.get("scoped") == "scoped" else "unscoped"
    query_class = str(latency_ms.get("query_class") or "")
    if query_class in _QUERY_CLASSES:
        QUERY_CLASS.labels(query_class=query_class).inc()

    cache = latency_ms.get("cache")
    if cache == "hit":
        CACHE_HITS.labels(tier="l3").inc()
    elif "cache" not in latency_ms:
        CACHE_MISSES.labels(tier="l3").inc()

    scope = latency_ms.get("matter_scope")
    if isinstance(scope, dict):
        if int(scope.get("matter_count") or 0) > 0:
            MATTER_SCOPE_RESOLVED.inc()
        elif scope.get("fallback") == "unscoped":
            MATTER_SCOPE_UNSCOPED.inc()

    if elapsed_ms is not None and elapsed_ms > _SLOW_MS:
        SLOW_QUERIES.labels(intent=intent).inc()
        QUERY_LATENCY.labels(intent=intent, scoped=scoped).observe(elapsed_ms / 1000.0)
    elif elapsed_ms is not None:
        QUERY_LATENCY.labels(intent=intent, scoped=scoped).observe(elapsed_ms / 1000.0)

    for key, val in latency_ms.items():
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        secs = val / 1000.0
        if key in _CHANNEL_KEYS:
            CHANNEL_LATENCY.labels(channel=key).observe(secs)
        elif key in _STAGE_MS:
            STAGE_LATENCY.labels(stage=_STAGE_MS[key]).observe(secs)
            if key == "rerank":
                RERANK_LATENCY.observe(secs)
        elif key == "llm":
            LLM_LATENCY.labels(provider=endpoint).observe(secs)


def prometheus_response() -> tuple[bytes, str]:
    observe_pool_waiting()
    return generate_latest(), CONTENT_TYPE_LATEST
