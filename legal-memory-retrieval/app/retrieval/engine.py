from __future__ import annotations

import time

from app.cache.redis import cache_get, cache_set
from app.observability.tracing import span
from app.config import settings
from app.query.understand import understand
from app.retrieval.fusion import fuse
from app.retrieval.graph import graph_search
from app.retrieval.keyword import keyword_search
from app.retrieval.metadata import metadata_search
from app.retrieval.reranker import rerank
from app.retrieval.route import CHANNEL_WEIGHTS, filter_vector_hits
from app.retrieval.semantic import semantic_search

CHANNELS = {
    "keyword": keyword_search,
    "metadata": metadata_search,
    "vector": semantic_search,
    "graph": graph_search,
}

RUN_ORDER = ("keyword", "metadata", "vector", "graph")


def parse_channels(raw: str | None) -> list[str]:
    text = raw if raw is not None else settings.retrieval_channels
    return [part.strip() for part in text.split(",") if part.strip()]


parse_channels = parse_channels  # eval import name


def _weights(parsed) -> dict[str, float]:
    weights = dict(CHANNEL_WEIGHTS)
    if parsed.intent == "graph_reasoning":
        weights["graph"] = 2.5
        weights["metadata"] = 0.2
        weights["keyword"] = 0.4
    elif parsed.intent == "cross_document":
        weights["keyword"] = 1.4
        weights["vector"] = 1.1
        weights["metadata"] = 1.3
        weights["graph"] = 0.4
    elif parsed.intent in {"exact_lookup", "matter_research"}:
        weights["metadata"] = 2.0
    elif parsed.intent == "experience_search":
        weights["metadata"] = 2.2
        weights["graph"] = 1.3
        weights["vector"] = 0.5
    if parsed.matter_ids and parsed.intent not in {"graph_reasoning", "cross_document"}:
        weights["graph"] = 1.6
    return weights


def retrieve(
    conn,
    query: str,
    member_id: str | None = None,
    k: int | None = None,
    channels: list[str] | None = None,
) -> tuple[list[dict], dict[str, float]]:
    """Return (hits, latency_ms) where latency_ms maps stage names to elapsed ms."""
    k = k or settings.retrieve_k
    latency: dict[str, float] = {}

    t0 = time.perf_counter()
    parsed = understand(query)
    latency["understand"] = round((time.perf_counter() - t0) * 1000, 1)

    if parsed.intent == "empty" or not parsed.raw:
        return [], latency

    wanted = set(channels or parse_channels(None))
    search = parsed.search_text or parsed.raw

    # Cache check — keyed per (query, member_id, channels, index_version)
    channel_list = [c for c in RUN_ORDER if c in wanted]
    cached = cache_get(query, member_id, channel_list)
    if cached is not None:
        latency["cache"] = "hit"
        return cached[:k], latency

    lists: list[list[dict]] = []
    lexical: list[dict] = []
    for name in RUN_ORDER:
        if name not in wanted:
            continue
        if name == "metadata" and parsed.intent == "graph_reasoning":
            continue
        if name == "vector" and parsed.skip_vector:
            continue
        fn = CHANNELS[name]
        t1 = time.perf_counter()
        with span(f"retrieval.{name}", {"intent": parsed.intent}):
            if name == "metadata":
                hits = fn(conn, search, member_id, limit=50, parsed=parsed)
            elif name == "graph":
                hits = fn(conn, parsed.raw, member_id, limit=50, parsed=parsed)
            elif name == "vector":
                hits = fn(conn, parsed.raw, member_id, limit=50)
            elif name == "keyword":
                hits = fn(conn, parsed.raw, member_id, limit=50)
            else:
                hits = fn(conn, search, member_id, limit=50)
        latency[name] = round((time.perf_counter() - t1) * 1000, 1)
        if name == "vector":
            hits = filter_vector_hits(hits, lexical_empty=not lexical)
        elif name in {"keyword", "metadata", "graph"}:
            lexical.extend(hits)
        lists.append(hits)

    t2 = time.perf_counter()
    with span("retrieval.fusion"):
        fused = fuse(*lists, limit=settings.rerank_candidates, weights=_weights(parsed))
    latency["fusion"] = round((time.perf_counter() - t2) * 1000, 1)

    if settings.rerank_enabled and fused and not parsed.skip_rerank:
        t3 = time.perf_counter()
        with span("retrieval.rerank", {"candidates": len(fused)}):
            fused = rerank(parsed.raw, fused)
        latency["rerank"] = round((time.perf_counter() - t3) * 1000, 1)

    result = fused[:k]
    cache_set(query, member_id, channel_list, result)
    return result, latency
