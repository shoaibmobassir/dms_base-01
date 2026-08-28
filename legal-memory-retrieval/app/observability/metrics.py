from __future__ import annotations

from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

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

CHANNEL_LATENCY = Histogram(
    "retrieval_channel_latency_seconds",
    "Per-channel search latency",
    ["channel"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0),
)

RERANK_LATENCY = Histogram(
    "rerank_latency_seconds",
    "Cross-encoder rerank latency",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0),
)

LLM_LATENCY = Histogram(
    "llm_latency_seconds",
    "LLM answer generation latency",
    ["provider"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0),
)

CACHE_HITS = Counter("retrieval_cache_hits_total", "Redis cache hits")
CACHE_MISSES = Counter("retrieval_cache_misses_total", "Redis cache misses")

ABSTENTIONS = Counter(
    "answer_abstentions_total",
    "Answers that abstained",
    ["reason"],
)


def record_latency_breakdown(latency_ms: dict, endpoint: str) -> None:
    channels = {"keyword", "metadata", "vector", "graph"}
    for key, val in latency_ms.items():
        if key == "cache" and val == "hit":
            CACHE_HITS.inc()
            continue
        if not isinstance(val, (int, float)):
            continue
        secs = val / 1000.0
        if key in channels:
            CHANNEL_LATENCY.labels(channel=key).observe(secs)
        elif key == "rerank":
            RERANK_LATENCY.observe(secs)
        elif key == "llm":
            LLM_LATENCY.labels(provider=endpoint).observe(secs)
    if "cache" not in latency_ms:
        CACHE_MISSES.inc()


def prometheus_response() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
