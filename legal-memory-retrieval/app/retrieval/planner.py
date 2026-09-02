"""Retrieval Planner — cost-aware, query-adaptive channel selection.

Given a ParsedQuery, the planner decides:
  - Which retrieval channels to run
  - Whether to do graph expansion (post-fusion)
  - Whether to rerank
  - How many candidates to keep at each stage
  - Per-channel fusion weights

This is a first-class component, not buried inside the engine.
The engine simply executes whatever plan the planner produces.

Design rationale:
  An exact lookup (MTR-2024-112) shouldn't run vector search and a cross-encoder.
  A broad research question shouldn't skip vector or graph.
  A "what have we done for Client X?" shouldn't waste compute on BM25.

  The planner makes these decisions explicitly so they're testable,
  tunable, and visible in observability traces.
"""
from __future__ import annotations

from app.query.understand import ParsedQuery
from app.retrieval.contracts import RetrievalPlan


def plan(parsed: ParsedQuery) -> RetrievalPlan:
    """Produce a retrieval execution plan based on query understanding.

    The engine calls this once per request, then executes the plan.
    """
    intent = parsed.intent

    # ── Exact lookup: matter ID or doc ID ─────────────────────────────────
    if intent == "exact_lookup":
        return RetrievalPlan(
            channels=["metadata", "bm25"],
            graph_expansion=False,
            rerank=False,
            # Fusion pool size (rerank disabled; must be > 0 or exact lookups return empty)
            rerank_candidates=50,
            final_k=20,
            weights={
                "metadata": 2.0,
                "bm25": 1.0,
            },
        )

    # ── Experience search: "which lawyers have experience in..." ─────────
    if intent == "experience_search":
        return RetrievalPlan(
            channels=["metadata", "matter", "graph_seed"],
            graph_expansion=False,
            rerank=True,
            rerank_candidates=50,
            final_k=20,
            weights={
                "metadata": 2.2,
                "matter": 1.5,
                "graph_seed": 1.3,
            },
        )

    # ── Graph reasoning: "find matters related to X with different client" ─
    if intent == "graph_reasoning":
        return RetrievalPlan(
            channels=["graph_seed", "vector", "bm25"],
            graph_expansion=True,
            graph_expansion_depth=2,
            rerank=True,
            rerank_candidates=100,
            final_k=20,
            weights={
                "graph_seed": 2.5,
                "vector": 0.8,
                "bm25": 0.4,
            },
        )

    # ── Cross-document: "what was our position regarding..." ─────────────
    if intent == "cross_document":
        return RetrievalPlan(
            channels=["bm25", "vector", "metadata", "matter", "graph_seed"],
            graph_expansion=True,
            graph_expansion_depth=1,
            rerank=True,
            rerank_candidates=100,
            final_k=20,
            weights={
                "bm25": 1.4,
                "vector": 1.1,
                "metadata": 1.3,
                "matter": 1.0,
                "graph_seed": 0.4,
            },
        )

    # ── Similar matter: "have we previously handled..." ──────────────────
    if intent in {"similar_matter", "semantic"}:
        return RetrievalPlan(
            channels=["vector", "matter", "graph_seed", "bm25"],
            graph_expansion=True,
            graph_expansion_depth=2,
            rerank=True,
            rerank_candidates=100,
            final_k=20,
            weights={
                "vector": 1.3,
                "matter": 1.2,
                "graph_seed": 1.0,
                "bm25": 0.8,
            },
        )

    # ── Matter research (default): broad legal research ──────────────────
    # intent == "matter_research" or anything else
    return RetrievalPlan(
        channels=["bm25", "vector", "metadata", "matter", "graph_seed"],
        graph_expansion=bool(parsed.matter_ids),
        graph_expansion_depth=2,
        rerank=True,
        rerank_candidates=100,
        final_k=20,
        weights={
            "bm25": 1.2,
            "vector": 0.75,
            "metadata": 1.5,
            "matter": 1.3,
            "graph_seed": 0.9,
        },
    )
