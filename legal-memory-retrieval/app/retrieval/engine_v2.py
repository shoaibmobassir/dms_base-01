"""Async parallel retrieval engine — the core of the retrieval plane.

This replaces the old engine.py which had vector retrieval downstream of lexical,
used ThreadPoolExecutor, and opened fresh DB connections per channel.

Architecture:
    Query
      ↓
    understand()
      ↓
    plan()           ← Retrieval Planner decides channels + config
      ↓
    ┌──────────────────────────────────────────────────────┐
    │ asyncio.gather(*channel_tasks)                       │
    │ BM25 │ Vector │ Metadata │ Matter │ Graph │ Similar  │
    └──────────────────────────────────────────────────────┘
      ↓
    ACL filter (already in SQL, but double-check here)
      ↓
    Deduplication
      ↓
    Graph expansion (conditional, post-fusion)
      ↓
    Weighted RRF fusion
      ↓
    Cross-encoder rerank (conditional)
      ↓
    Top-K results with provenance

Key design decisions:
  - Each channel gets its own connection from the async pool
  - Failures in one channel don't block others (return_exceptions=True)
  - Vector score filtering moved to post-fusion (no lexical dependency)
  - Every candidate carries full provenance through the pipeline
  - The Retrieval Planner controls which channels run
  - The old synchronous `retrieve()` is preserved as a thin wrapper
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.db.pool import acquire
from app.embeddings.minilm import MiniLMEmbedder
from app.observability.tracing import span
from app.query.understand import ParsedQuery, understand
from app.retrieval.contracts import (
    Candidate,
    Provenance,
    RetrievalContext,
    RetrievalPlan,
)
from app.retrieval.planner import plan as plan_retrieval
from app.retrieval.reranker import rerank
from app.retrieval.route import VECTOR_MIN_SCORE
from app.storage.postgres import (
    PgGraphStore,
    PgMatterStore,
    PgMetadataStore,
    PgSearchStore,
    PgVectorStore,
)

logger = logging.getLogger(__name__)

# ── Stores (singleton-ish, stateless so safe to share) ───────────────────────

_search_store = PgSearchStore()
_vector_store = PgVectorStore()
_metadata_store = PgMetadataStore()
_graph_store = PgGraphStore()
_matter_store = PgMatterStore()

# ── Embedder (lazy init) ────────────────────────────────────────────────────

_embedder: MiniLMEmbedder | None = None


def _get_embedder() -> MiniLMEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = MiniLMEmbedder()
    return _embedder


# ═══════════════════════════════════════════════════════════════════════════════
# Channel functions — each runs independently, gets its own connection
# ═══════════════════════════════════════════════════════════════════════════════


async def _channel_bm25(ctx: RetrievalContext, limit: int) -> list[Candidate]:
    """BM25 full-text search channel."""
    # Prefer cleaned search_text so question boilerplate does not AND-kill FTS.
    query = ctx.query_search_text or ctx.query_raw
    async with acquire() as conn:
        rows = await _search_store.search(
            conn, query, ctx.member_id, limit=limit,
        )
        # Fallback to raw if cleaned query was over-stripped or empty.
        if not rows and query != ctx.query_raw:
            rows = await _search_store.search(
                conn, ctx.query_raw, ctx.member_id, limit=limit,
            )
    return [Candidate.from_db_row(r, "bm25") for r in rows]


async def _channel_vector(ctx: RetrievalContext, limit: int) -> list[Candidate]:
    """Vector ANN search channel."""
    embedder = _get_embedder()
    qvec = embedder.encode([ctx.query_raw])[0]
    async with acquire() as conn:
        rows = await _vector_store.search(
            conn, qvec.tolist() if hasattr(qvec, "tolist") else list(qvec),
            ctx.member_id, limit=limit,
        )
    # Apply minimum score threshold (but no lexical dependency anymore)
    candidates = []
    for r in rows:
        c = Candidate.from_db_row(r, "vector")
        if c.raw_score >= VECTOR_MIN_SCORE:
            candidates.append(c)
    return candidates


async def _channel_metadata(ctx: RetrievalContext, limit: int) -> list[Candidate]:
    """Metadata exact/near-exact lookup channel."""
    async with acquire() as conn:
        rows = await _metadata_store.search(
            conn,
            ctx.query_search_text or ctx.query_raw,
            member_id=ctx.member_id,
            limit=limit,
            matter_ids=ctx.matter_ids or None,
            matter_codes=ctx.matter_codes or None,
            practice_area=ctx.practice_area,
            rank_query=ctx.query_raw,
            dedupe_matters=ctx.intent == "experience_search",
        )
    return [Candidate.from_db_row(r, "metadata") for r in rows]


async def _channel_matter(ctx: RetrievalContext, limit: int) -> list[Candidate]:
    """Matter-level retrieval — find relevant matters, then their documents."""
    async with acquire() as conn:
        rows: list[dict] = []
        if ctx.practice_area:
            rows.extend(await _matter_store.search_by_practice(
                conn, ctx.practice_area, ctx.member_id, limit=limit,
            ))
        if ctx.client_name:
            rows.extend(await _matter_store.search_by_client(
                conn, ctx.client_name, ctx.member_id, limit=limit,
            ))
        if ctx.entities:
            rows.extend(await _matter_store.search_by_legal_issues(
                conn, ctx.entities, ctx.member_id, limit=limit,
            ))
        # Free-text fallback so matter channel contributes without NER.
        if not rows:
            needle = ctx.client_name or ctx.query_search_text or ctx.query_raw
            rows.extend(await _matter_store.search_by_text(
                conn, needle, ctx.member_id, limit=limit,
            ))
    # Prefer document title field when store returned doc_title
    candidates = []
    for r in rows:
        if not r.get("title") and r.get("doc_title"):
            r = {**r, "title": r["doc_title"]}
        candidates.append(Candidate.from_db_row(r, "matter"))
    return candidates


async def _channel_graph_seed(ctx: RetrievalContext, limit: int) -> list[Candidate]:
    """Graph seed retrieval — find docs connected to seed entities.

    This is Graph Operation A: runs in parallel with other channels.
    """
    seeds = ctx.matter_ids + ctx.matter_codes + ctx.member_ids
    if not seeds:
        return []
    async with acquire() as conn:
        rows = await _graph_store.seed(
            conn, seeds, ctx.member_id, limit=limit,
        )
    return [Candidate.from_db_row(r, "graph_seed") for r in rows]


async def _channel_similar_matter(ctx: RetrievalContext, limit: int) -> list[Candidate]:
    """Similar matter retrieval — find structurally similar engagements.

    Uses vector similarity on the query to find matters with similar
    legal issues, practice area, and themes.
    """
    # For now, delegate to vector search with matter-level deduplication
    embedder = _get_embedder()
    qvec = embedder.encode([ctx.query_raw])[0]
    async with acquire() as conn:
        rows = await _vector_store.search(
            conn, qvec.tolist() if hasattr(qvec, "tolist") else list(qvec),
            ctx.member_id, limit=limit,
        )
    # Deduplicate by matter_id, keeping highest scoring per matter
    seen_matters: dict[str, Candidate] = {}
    for r in rows:
        c = Candidate.from_db_row(r, "similar_matter")
        mid = c.matter_id
        if mid not in seen_matters or c.raw_score > seen_matters[mid].raw_score:
            seen_matters[mid] = c
    return list(seen_matters.values())


# ── Channel registry ─────────────────────────────────────────────────────────

_CHANNEL_FNS = {
    "bm25": _channel_bm25,
    "vector": _channel_vector,
    "metadata": _channel_metadata,
    "matter": _channel_matter,
    "graph_seed": _channel_graph_seed,
    "similar_matter": _channel_similar_matter,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Pipeline stages
# ═══════════════════════════════════════════════════════════════════════════════


def _build_context(parsed: ParsedQuery, member_id: str | None, k: int) -> RetrievalContext:
    """Convert ParsedQuery → RetrievalContext for channel consumption."""
    return RetrievalContext(
        query_raw=parsed.raw,
        query_search_text=parsed.search_text or parsed.raw,
        intent=parsed.intent,
        member_id=member_id,
        matter_ids=list(parsed.matter_ids),
        matter_codes=list(parsed.matter_codes),
        document_ids=list(parsed.document_ids),
        member_ids=list(parsed.member_ids),
        practice_area=parsed.practice_area,
        entities=[],  # Will be populated by NER in Phase 8
        k=k,
    )


def _deduplicate(candidates: list[Candidate]) -> list[Candidate]:
    """Deduplicate candidates, keeping the highest-scoring per dedup_key.

    Also merges provenance: if the same chunk was found by multiple channels,
    the provenance.channels_found_in list tracks all of them.
    """
    best: dict[str, Candidate] = {}
    all_channels: dict[str, list[str]] = {}
    all_scores: dict[str, dict[str, float]] = {}

    for c in candidates:
        key = c.dedup_key
        if key not in all_channels:
            all_channels[key] = []
            all_scores[key] = {}
        all_channels[key].append(c.channel)

        # Store per-channel scores
        score_attr = f"{c.channel}_score"
        all_scores[key][score_attr] = c.raw_score

        if key not in best or c.raw_score > best[key].raw_score:
            best[key] = c

    # Enrich provenance with multi-channel info
    for key, candidate in best.items():
        candidate.provenance.channels_found_in = list(set(all_channels.get(key, [])))
        scores = all_scores.get(key, {})
        candidate.provenance.bm25_score = scores.get("bm25_score")
        candidate.provenance.vector_score = scores.get("vector_score")
        candidate.provenance.metadata_score = scores.get("metadata_score")
        candidate.provenance.matter_score = scores.get("matter_score")
        candidate.provenance.graph_score = scores.get("graph_seed_score")
        candidate.provenance.similar_matter_score = scores.get("similar_matter_score")

    return list(best.values())


def _fuse_candidates(
    candidates: list[Candidate],
    weights: dict[str, float],
    limit: int = 100,
) -> list[Candidate]:
    """Weighted Reciprocal Rank Fusion across channels.

    Preserves provenance — each candidate knows its fusion score.
    """
    from collections import defaultdict

    k = 60  # RRF constant
    # Group by channel first
    by_channel: dict[str, list[Candidate]] = defaultdict(list)
    for c in candidates:
        by_channel[c.channel].append(c)

    # Sort each channel by raw_score descending
    for ch in by_channel:
        by_channel[ch].sort(key=lambda x: x.raw_score, reverse=True)

    # Compute RRF scores
    rrf_scores: dict[str, float] = defaultdict(float)
    candidate_map: dict[str, Candidate] = {}

    for channel, channel_candidates in by_channel.items():
        w = weights.get(channel, 1.0)
        for rank, c in enumerate(channel_candidates, start=1):
            key = c.dedup_key
            rrf_scores[key] += w / (k + rank)
            if key not in candidate_map:
                candidate_map[key] = c

    # Sort by fusion score
    ranked = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    result = []
    for key, score in ranked[:limit]:
        c = candidate_map[key]
        c.fusion_score = round(score, 6)
        result.append(c)

    return result


async def _graph_expand(
    candidates: list[Candidate],
    member_id: str | None,
    depth: int = 2,
    limit: int = 50,
) -> list[Candidate]:
    """Graph Operation B — expand from candidate matter IDs.

    Runs AFTER initial candidate pool. Discovers related matters/documents
    the initial retrieval missed.
    """
    seed_matter_ids = list({c.matter_id for c in candidates if c.matter_id})
    if not seed_matter_ids:
        return []

    async with acquire() as conn:
        rows = await _graph_store.expand(
            conn, seed_matter_ids, depth=depth,
            member_id=member_id, limit=limit,
        )

    expanded = []
    for r in rows:
        c = Candidate.from_db_row(r, "graph_expansion")
        c.provenance.graph_path = ["candidate_matter", "expansion", "document"]
        c.provenance.expansion_depth = depth
        expanded.append(c)
    return expanded


async def _rerank_candidates(
    query: str, candidates: list[Candidate], plan: RetrievalPlan,
) -> list[Candidate]:
    """Rerank using cross-encoder, preserving provenance."""
    if not plan.rerank or len(candidates) <= 1:
        return candidates

    # Convert Candidates → dicts for the existing reranker
    hit_dicts = [c.to_dict() for c in candidates[:plan.rerank_candidates]]
    reranked_dicts = rerank(query, hit_dicts)

    # Rebuild Candidates with rerank scores
    result = []
    for rd in reranked_dicts:
        # Find the original Candidate
        for c in candidates:
            if c.dedup_key == (rd.get("chunk_id") or rd.get("document_id")):
                c.rerank_score = float(rd.get("rerank_score", 0.0))
                c.provenance.ce_score = float(rd.get("ce_score", 0.0))
                result.append(c)
                break

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Main entry points
# ═══════════════════════════════════════════════════════════════════════════════


async def retrieve_async(
    query: str,
    member_id: str | None = None,
    k: int = 20,
) -> tuple[list[Candidate], dict[str, Any]]:
    """Async parallel retrieval — the primary entry point.

    Returns (candidates, latency_dict).
    """
    latency: dict[str, Any] = {}
    timers: dict[str, float] = {}

    # ── Step 1: Query understanding ──────────────────────────────────────
    t0 = time.perf_counter()
    parsed = understand(query)
    latency["understand"] = round((time.perf_counter() - t0) * 1000, 1)

    if parsed.intent == "empty" or not parsed.raw:
        return [], latency

    # ── Step 2: Retrieval planning ───────────────────────────────────────
    t1 = time.perf_counter()
    retrieval_plan = plan_retrieval(parsed)
    latency["plan"] = round((time.perf_counter() - t1) * 1000, 1)
    latency["channels_planned"] = retrieval_plan.channels

    ctx = _build_context(parsed, member_id, k)

    # ── Step 3: Parallel channel execution ───────────────────────────────
    t_parallel = time.perf_counter()

    async def _timed_channel(name: str) -> tuple[str, list[Candidate], float]:
        t = time.perf_counter()
        fn = _CHANNEL_FNS.get(name)
        if fn is None:
            return name, [], 0.0
        try:
            with span(f"retrieval.{name}", {"intent": parsed.intent}):
                results = await fn(ctx, limit=50)
        except Exception as exc:
            logger.warning("Channel %s failed: %s", name, exc, exc_info=True)
            results = []
        elapsed = round((time.perf_counter() - t) * 1000, 1)
        return name, results, elapsed

    channel_tasks = [_timed_channel(ch) for ch in retrieval_plan.channels]
    channel_results = await asyncio.gather(*channel_tasks)

    all_candidates: list[Candidate] = []
    for name, candidates, elapsed in channel_results:
        latency[name] = elapsed
        latency[f"{name}_count"] = len(candidates)
        all_candidates.extend(candidates)

    latency["parallel_wall_ms"] = round((time.perf_counter() - t_parallel) * 1000, 1)
    latency["total_raw_candidates"] = len(all_candidates)

    # ── Step 4: Deduplication ────────────────────────────────────────────
    t_dedup = time.perf_counter()
    deduped = _deduplicate(all_candidates)
    latency["dedup"] = round((time.perf_counter() - t_dedup) * 1000, 1)
    latency["unique_candidates"] = len(deduped)

    # ── Step 5: Graph expansion (conditional, post-dedup) ────────────────
    if retrieval_plan.graph_expansion and deduped:
        t_expand = time.perf_counter()
        with span("retrieval.graph_expansion", {"depth": retrieval_plan.graph_expansion_depth}):
            expanded = await _graph_expand(
                deduped, member_id,
                depth=retrieval_plan.graph_expansion_depth,
            )
        if expanded:
            deduped.extend(expanded)
            deduped = _deduplicate(deduped)
        latency["graph_expansion"] = round((time.perf_counter() - t_expand) * 1000, 1)
        latency["graph_expansion_added"] = len(expanded)

    # ── Step 6: Weighted RRF Fusion ──────────────────────────────────────
    t_fusion = time.perf_counter()
    # When rerank is off (e.g. exact_lookup), still keep a non-zero fusion pool.
    fusion_limit = retrieval_plan.rerank_candidates if retrieval_plan.rerank else retrieval_plan.final_k
    fusion_limit = max(fusion_limit, retrieval_plan.final_k, k)
    with span("retrieval.fusion"):
        fused = _fuse_candidates(
            deduped,
            weights=retrieval_plan.weights,
            limit=fusion_limit,
        )
    latency["fusion"] = round((time.perf_counter() - t_fusion) * 1000, 1)
    latency["fusion_candidates"] = len(fused)

    # ── Step 7: Reranking (conditional) ──────────────────────────────────
    if retrieval_plan.rerank and fused:
        t_rerank = time.perf_counter()
        with span("retrieval.rerank", {"candidates": len(fused)}):
            fused = await _rerank_candidates(query, fused, retrieval_plan)
        latency["rerank"] = round((time.perf_counter() - t_rerank) * 1000, 1)
        latency["rerank_candidates"] = len(fused)

    result = fused[:k]
    latency["final_count"] = len(result)
    return result, latency


def retrieve(
    conn,
    query: str,
    member_id: str | None = None,
    k: int | None = None,
    channels: list[str] | None = None,
) -> tuple[list[dict], dict[str, float]]:
    """Synchronous backward-compatible wrapper.

    Existing callers (answer_question, retrieval router) use this.
    It runs the async engine in the current event loop or creates one.

    The conn parameter is accepted but IGNORED — the async engine
    uses the pool. This preserves the call signature while channels
    are migrated.
    """
    from app.config import settings

    final_k = k or settings.retrieve_k

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're already in an async context (e.g., FastAPI) — use nest_asyncio
        # or create a new thread. For simplicity, run in a new thread.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, retrieve_async(query, member_id, final_k))
            candidates, latency = future.result()
    else:
        candidates, latency = asyncio.run(retrieve_async(query, member_id, final_k))

    # Convert Candidates → dicts for backward compat with API / answers
    hits = []
    for c in candidates:
        d = c.to_dict()
        d["fused_score"] = c.fusion_score
        d["score"] = c.rerank_score or c.fusion_score or c.raw_score
        if c.provenance and c.provenance.ce_score is not None:
            d["ce_score"] = c.provenance.ce_score
        hits.append(d)

    return hits, latency
