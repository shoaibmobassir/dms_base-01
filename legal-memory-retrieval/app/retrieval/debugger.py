"""Retrieval debugger — diagnostic endpoint for understanding retrieval behavior.

Provides a detailed breakdown of what happened during retrieval:
  - Query understanding (intent, entities)
  - Which channels ran and why (from the planner)
  - Per-channel candidate counts and top results
  - Deduplication stats
  - Graph expansion results
  - Fusion rankings
  - Reranking impact
  - Full provenance for every result

Usage:
    POST /api/retrieval/debug
    {"query": "Find previous shareholder disputes", "member_id": "MEM-001"}

Returns:
    {
      "understanding": {...},
      "plan": {...},
      "channels": {
        "bm25": {"count": 87, "top_3": [...]},
        "vector": {"count": 100, "top_3": [...]},
        ...
      },
      "dedup": {"before": 320, "after": 192},
      "graph_expansion": {"enabled": true, "added": 63},
      "fusion": {"candidates": 192, "top_20": [...]},
      "rerank": {"input": 100, "output": 20},
      "final_results": [...],
      "latency": {...}
    }
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.db.pool import acquire
from app.embeddings.minilm import MiniLMEmbedder
from app.observability.tracing import span
from app.query.understand import understand
from app.retrieval.contracts import Candidate, RetrievalContext
from app.retrieval.engine_v2 import (
    _CHANNEL_FNS,
    _build_context,
    _deduplicate,
    _fuse_candidates,
    _get_embedder,
    _graph_expand,
    _rerank_candidates,
)
from app.retrieval.planner import plan as plan_retrieval

logger = logging.getLogger(__name__)


async def debug_retrieval(
    query: str,
    member_id: str | None = None,
    k: int = 20,
) -> dict[str, Any]:
    """Run retrieval with full diagnostic output.

    Unlike `retrieve_async`, this returns detailed per-stage breakdowns
    instead of just the final results. Used by the /api/retrieval/debug endpoint.
    """
    result: dict[str, Any] = {"query": query, "member_id": member_id}
    latency: dict[str, Any] = {}

    # ── Query Understanding ──────────────────────────────────────────────
    t0 = time.perf_counter()
    parsed = understand(query)
    latency["understand"] = round((time.perf_counter() - t0) * 1000, 1)
    result["understanding"] = parsed.to_dict()

    if parsed.intent == "empty" or not parsed.raw:
        result["latency"] = latency
        result["final_results"] = []
        return result

    # ── Retrieval Planning ───────────────────────────────────────────────
    t1 = time.perf_counter()
    retrieval_plan = plan_retrieval(parsed)
    latency["plan"] = round((time.perf_counter() - t1) * 1000, 1)
    result["plan"] = {
        "channels": retrieval_plan.channels,
        "graph_expansion": retrieval_plan.graph_expansion,
        "graph_expansion_depth": retrieval_plan.graph_expansion_depth,
        "rerank": retrieval_plan.rerank,
        "rerank_candidates": retrieval_plan.rerank_candidates,
        "final_k": retrieval_plan.final_k,
        "weights": retrieval_plan.weights,
    }

    ctx = _build_context(parsed, member_id, k)

    # ── Per-Channel Execution ────────────────────────────────────────────
    channel_debug: dict[str, dict] = {}
    all_candidates: list[Candidate] = []

    async def _run_channel_debug(name: str) -> tuple[str, list[Candidate], float]:
        t = time.perf_counter()
        fn = _CHANNEL_FNS.get(name)
        if fn is None:
            return name, [], 0.0
        try:
            results = await fn(ctx, limit=50)
        except Exception as exc:
            logger.warning("Debug channel %s failed: %s", name, exc)
            return name, [], round((time.perf_counter() - t) * 1000, 1)
        elapsed = round((time.perf_counter() - t) * 1000, 1)
        return name, results, elapsed

    t_parallel = time.perf_counter()
    tasks = [_run_channel_debug(ch) for ch in retrieval_plan.channels]
    channel_results = await asyncio.gather(*tasks)
    latency["parallel_wall_ms"] = round((time.perf_counter() - t_parallel) * 1000, 1)

    for name, candidates, elapsed in channel_results:
        latency[name] = elapsed
        all_candidates.extend(candidates)
        channel_debug[name] = {
            "count": len(candidates),
            "latency_ms": elapsed,
            "top_3": [
                {
                    "chunk_id": c.chunk_id,
                    "document_id": c.document_id,
                    "matter_id": c.matter_id,
                    "title": c.title[:80],
                    "score": round(c.raw_score, 4),
                    "text_preview": c.text[:150] + "..." if len(c.text) > 150 else c.text,
                }
                for c in sorted(candidates, key=lambda x: x.raw_score, reverse=True)[:3]
            ],
        }
    result["channels"] = channel_debug

    # ── Deduplication ────────────────────────────────────────────────────
    before_dedup = len(all_candidates)
    deduped = _deduplicate(all_candidates)
    result["dedup"] = {
        "before": before_dedup,
        "after": len(deduped),
        "removed": before_dedup - len(deduped),
    }

    # ── Graph Expansion ──────────────────────────────────────────────────
    expansion_info = {"enabled": retrieval_plan.graph_expansion, "added": 0}
    if retrieval_plan.graph_expansion and deduped:
        t_expand = time.perf_counter()
        expanded = await _graph_expand(
            deduped, member_id,
            depth=retrieval_plan.graph_expansion_depth,
        )
        expansion_info["added"] = len(expanded)
        expansion_info["latency_ms"] = round((time.perf_counter() - t_expand) * 1000, 1)
        expansion_info["expanded_matters"] = list({c.matter_id for c in expanded})[:10]
        if expanded:
            deduped.extend(expanded)
            deduped = _deduplicate(deduped)
            expansion_info["total_after_expansion"] = len(deduped)
        latency["graph_expansion"] = expansion_info.get("latency_ms", 0)
    result["graph_expansion"] = expansion_info

    # ── Fusion ───────────────────────────────────────────────────────────
    t_fusion = time.perf_counter()
    fused = _fuse_candidates(deduped, retrieval_plan.weights, limit=retrieval_plan.rerank_candidates)
    latency["fusion"] = round((time.perf_counter() - t_fusion) * 1000, 1)
    result["fusion"] = {
        "candidates": len(fused),
        "top_10": [
            {
                "rank": i + 1,
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "matter_id": c.matter_id,
                "title": c.title[:60],
                "channels": c.provenance.channels_found_in,
                "fusion_score": round(c.fusion_score or 0, 6),
                "raw_score": round(c.raw_score, 4),
            }
            for i, c in enumerate(fused[:10])
        ],
    }

    # ── Reranking ────────────────────────────────────────────────────────
    rerank_info = {"enabled": retrieval_plan.rerank, "input": len(fused), "output": 0}
    if retrieval_plan.rerank and fused:
        t_rerank = time.perf_counter()
        reranked = await _rerank_candidates(query, fused, retrieval_plan)
        rerank_info["output"] = len(reranked)
        rerank_info["latency_ms"] = round((time.perf_counter() - t_rerank) * 1000, 1)
        latency["rerank"] = rerank_info.get("latency_ms", 0)
        fused = reranked
    result["rerank"] = rerank_info

    # ── Final Results ────────────────────────────────────────────────────
    final = fused[:k]
    result["final_results"] = [
        {
            "rank": i + 1,
            "chunk_id": c.chunk_id,
            "document_id": c.document_id,
            "matter_id": c.matter_id,
            "matter_code": c.matter_code,
            "title": c.title,
            "document_type": c.document_type,
            "client_name": c.client_name,
            "court": c.court,
            "practice_area": c.practice_area,
            "text_preview": c.text[:200],
            "provenance": c.provenance.to_dict(),
            "fusion_score": c.fusion_score,
            "rerank_score": c.rerank_score,
            "raw_score": c.raw_score,
        }
        for i, c in enumerate(final)
    ]

    result["latency"] = latency
    result["summary"] = {
        "intent": parsed.intent,
        "channels_planned": retrieval_plan.channels,
        "total_raw_candidates": before_dedup,
        "unique_after_dedup": result["dedup"]["after"],
        "graph_expansion_added": expansion_info["added"],
        "fusion_candidates": result["fusion"]["candidates"],
        "rerank_output": rerank_info.get("output", 0),
        "final_count": len(final),
        "total_latency_ms": round(sum(
            v for v in latency.values() if isinstance(v, (int, float))
        ), 1),
    }

    return result
