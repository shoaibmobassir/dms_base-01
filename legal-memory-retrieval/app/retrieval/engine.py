from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.cache.redis import cache_get, cache_set
from app.observability.tracing import span
from app.config import settings
from app.db.connection import connect
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

# Channels that can run in parallel (all use only DB I/O + maybe embedding)
_PARALLEL_CHANNELS = {"keyword", "metadata", "graph"}


def parse_channels(raw: str | None) -> list[str]:
    text = raw if raw is not None else settings.retrieval_channels
    return [part.strip() for part in text.split(",") if part.strip()]


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


def _run_channel(name: str, parsed, member_id: str | None, limit: int = 50) -> list[dict]:
    """Run a single retrieval channel with its own DB connection (thread-safe).

    Reasoning: psycopg connections are not thread-safe, so each parallel channel
    gets its own connection via connect(). This is the key design decision that
    enables ThreadPoolExecutor parallelism.
    """
    search = parsed.search_text or parsed.raw
    with connect() as conn:
        with span(f"retrieval.{name}", {"intent": parsed.intent}):
            if name == "metadata":
                return metadata_search(conn, search, member_id, limit=limit, parsed=parsed)
            elif name == "graph":
                return graph_search(conn, parsed.raw, member_id, limit=limit, parsed=parsed)
            elif name == "keyword":
                return keyword_search(conn, parsed.raw, member_id, limit=limit)
            else:
                return []


def retrieve(
    conn,
    query: str,
    member_id: str | None = None,
    k: int | None = None,
    channels: list[str] | None = None,
) -> tuple[list[dict], dict[str, float]]:
    """Retrieval entry point used by API, answers, and evals.

    Delegates to the parallel fabric (engine_v2) when enabled.
    """
    if settings.use_engine_v2:
        from app.retrieval.engine_v2 import retrieve as retrieve_v2

        return retrieve_v2(conn, query, member_id=member_id, k=k, channels=channels)
    return retrieve_legacy(conn, query, member_id=member_id, k=k, channels=channels)


def retrieve_legacy(
    conn,
    query: str,
    member_id: str | None = None,
    k: int | None = None,
    channels: list[str] | None = None,
) -> tuple[list[dict], dict[str, float]]:
    """Legacy hybrid retrieval (vector after lexical). Kept for rollback/tests.

    Architecture:
      1. understand(query) — called ONCE (fixes duplicate understand() bug)
      2. Parallel phase: keyword + metadata + graph via ThreadPoolExecutor
         (each gets its own DB connection for thread safety)
      3. Vector: runs after parallel phase with pre-encoded embedding
         (needs lexical_empty flag from parallel results)
      4. Fusion + rerank

    Returns (hits, latency_ms) where latency_ms maps stage names to elapsed ms.
    """
    k = k or settings.retrieve_k
    latency: dict[str, float] = {}

    # ── Step 1: understand ONCE ──────────────────────────────────────
    t0 = time.perf_counter()
    parsed = understand(query)
    latency["understand"] = round((time.perf_counter() - t0) * 1000, 1)

    if parsed.intent == "empty" or not parsed.raw:
        return [], latency

    wanted = set(channels or parse_channels(None))

    # Cache check
    channel_list = [c for c in RUN_ORDER if c in wanted]
    cached = cache_get(query, member_id, channel_list)
    if cached is not None:
        latency["cache"] = "hit"
        return cached[:k], latency

    # ── Step 2: Parallel phase (keyword + metadata + graph) ──────────
    parallel_names = [
        name for name in RUN_ORDER
        if name in wanted
        and name in _PARALLEL_CHANNELS
        and not (name == "metadata" and parsed.intent == "graph_reasoning")
    ]

    lists: list[list[dict]] = []
    lexical: list[dict] = []
    t_parallel = time.perf_counter()

    if parallel_names:
        with ThreadPoolExecutor(max_workers=len(parallel_names)) as pool:
            futures = {
                pool.submit(_run_channel, name, parsed, member_id, 50): name
                for name in parallel_names
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    hits = future.result()
                except Exception:
                    hits = []
                latency[name] = round((time.perf_counter() - t_parallel) * 1000, 1)
                if name in {"keyword", "metadata", "graph"}:
                    lexical.extend(hits)
                lists.append(hits)

    latency["parallel_wall_ms"] = round((time.perf_counter() - t_parallel) * 1000, 1)

    # ── Step 3: Vector (after parallel, needs lexical_empty flag) ────
    if "vector" in wanted and not parsed.skip_vector:
        t_vec = time.perf_counter()
        with span("retrieval.vector", {"intent": parsed.intent}):
            vec_hits = semantic_search(conn, parsed.raw, member_id, limit=50)
        vec_hits = filter_vector_hits(vec_hits, lexical_empty=not lexical)
        latency["vector"] = round((time.perf_counter() - t_vec) * 1000, 1)
        lists.append(vec_hits)

    # ── Step 4: Fusion ───────────────────────────────────────────────
    t2 = time.perf_counter()
    with span("retrieval.fusion"):
        fused = fuse(*lists, limit=settings.rerank_candidates, weights=_weights(parsed))
    latency["fusion"] = round((time.perf_counter() - t2) * 1000, 1)

    # ── Step 5: Rerank ───────────────────────────────────────────────
    if settings.rerank_enabled and fused and not parsed.skip_rerank:
        t3 = time.perf_counter()
        with span("retrieval.rerank", {"candidates": len(fused)}):
            fused = rerank(parsed.raw, fused)
        latency["rerank"] = round((time.perf_counter() - t3) * 1000, 1)

    result = fused[:k]
    cache_set(query, member_id, channel_list, result)
    return result, latency
