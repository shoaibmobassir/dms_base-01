"""P5.4 diagnosis — stage-by-stage ranks without changing fusion policy.

Records per-candidate channel ranks/scores, RRF rank, hierarchical channel
contribution, reranker rank, and final rank so we can answer:

  At which stage does a relevant result get pushed down?

No weight or planner changes live here — observation only.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from app.db.pool import init_pool, pool_stats
from app.query.understand import understand
from app.retrieval.contracts import Candidate
from app.retrieval.engine_v2 import (
    _CHANNEL_FNS,
    _build_context,
    _deduplicate,
    _fuse_candidates,
    _graph_expand,
    _rerank_candidates,
)
from app.retrieval.planner import plan as plan_retrieval

logger = logging.getLogger(__name__)

CHANNEL_RANK_KEYS = (
    "bm25",
    "vector",
    "metadata",
    "matter",
    "hierarchical",
    "graph_seed",
    "similar_matter",
    "graph_expansion",
)


@dataclass
class StageRow:
    """One candidate row for diagnostic CSV / analysis."""

    query_id: str
    query_type: str
    query: str
    intent: str
    candidate_id: str
    document_id: str
    matter_id: str
    chunk_id: str
    retrieved_by: str

    bm25_rank: int | None = None
    vector_rank: int | None = None
    metadata_rank: int | None = None
    matter_rank: int | None = None
    hierarchical_rank: int | None = None
    graph_seed_rank: int | None = None
    similar_matter_rank: int | None = None
    graph_expansion_rank: int | None = None

    bm25_score: float | None = None
    vector_score: float | None = None
    metadata_score: float | None = None
    matter_score: float | None = None
    hierarchical_score: float | None = None
    graph_seed_score: float | None = None
    similar_matter_score: float | None = None
    graph_expansion_score: float | None = None

    rrf_score: float | None = None
    rrf_rank: int | None = None
    reranker_score: float | None = None
    reranker_rank: int | None = None
    final_score: float | None = None
    final_rank: int | None = None

    is_relevant: int = 0
    relevance_grade: int = 0
    gold_kind: str = ""  # document | matter | none

    # Hierarchy-internal stage signals (from hierarchical channel metadata)
    matter_stage_score: float | None = None
    doc_stage_score: float | None = None
    hierarchy_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DiagnoseResult:
    query_id: str
    query: str
    query_type: str
    intent: str
    plan_channels: list[str]
    plan_weights: dict[str, float]
    rows: list[StageRow] = field(default_factory=list)
    latency_ms: dict[str, Any] = field(default_factory=dict)
    channel_counts: dict[str, int] = field(default_factory=dict)


def _rank_map(candidates: list[Candidate]) -> dict[str, int]:
    """1-based ranks by raw_score descending within a channel list."""
    ordered = sorted(candidates, key=lambda c: c.raw_score, reverse=True)
    return {c.dedup_key: i for i, c in enumerate(ordered, start=1)}


def _score_map(candidates: list[Candidate]) -> dict[str, float]:
    return {c.dedup_key: float(c.raw_score) for c in candidates}


def assign_stage_ranks(
    *,
    query_id: str,
    query: str,
    query_type: str,
    intent: str,
    by_channel: dict[str, list[Candidate]],
    fused: list[Candidate],
    reranked: list[Candidate] | None,
    final: list[Candidate],
    gold_docs: set[str],
    gold_matters: set[str],
) -> list[StageRow]:
    """Build StageRows from pipeline artifacts (pure; easy to unit-test)."""
    channel_ranks: dict[str, dict[str, int]] = {
        ch: _rank_map(cands) for ch, cands in by_channel.items()
    }
    channel_scores: dict[str, dict[str, float]] = {
        ch: _score_map(cands) for ch, cands in by_channel.items()
    }

    rrf_ranks = {c.dedup_key: i for i, c in enumerate(fused, start=1)}
    rerank_list = reranked if reranked is not None else fused
    rerank_ranks = {c.dedup_key: i for i, c in enumerate(rerank_list, start=1)}
    final_ranks = {c.dedup_key: i for i, c in enumerate(final, start=1)}

    # Union of all candidates seen through fusion (broadest useful set)
    pool: dict[str, Candidate] = {}
    for cands in by_channel.values():
        for c in cands:
            pool.setdefault(c.dedup_key, c)
    for c in fused:
        pool[c.dedup_key] = c

    rows: list[StageRow] = []
    for key, c in pool.items():
        retrieved = sorted({
            ch for ch, cmap in channel_ranks.items() if key in cmap
        } | set(c.provenance.channels_found_in or ([c.channel] if c.channel else [])))

        if gold_docs:
            relevant = 1 if c.document_id in gold_docs else 0
            gold_kind = "document"
        elif gold_matters:
            relevant = 1 if c.matter_id in gold_matters else 0
            gold_kind = "matter"
        else:
            relevant = 0
            gold_kind = "none"

        meta = c.metadata or {}
        row = StageRow(
            query_id=query_id,
            query_type=query_type,
            query=query,
            intent=intent,
            candidate_id=key,
            document_id=c.document_id,
            matter_id=c.matter_id,
            chunk_id=c.chunk_id,
            retrieved_by="|".join(retrieved),
            rrf_score=c.fusion_score,
            rrf_rank=rrf_ranks.get(key),
            reranker_score=c.rerank_score,
            reranker_rank=rerank_ranks.get(key),
            final_score=c.rerank_score or c.fusion_score or c.raw_score,
            final_rank=final_ranks.get(key),
            is_relevant=relevant,
            relevance_grade=relevant,
            gold_kind=gold_kind,
            matter_stage_score=_float_or_none(meta.get("matter_stage_score")),
            doc_stage_score=_float_or_none(meta.get("doc_stage_score")),
            hierarchy_label=str(meta.get("hierarchy") or ""),
        )
        for ch in CHANNEL_RANK_KEYS:
            setattr(row, f"{ch}_rank", channel_ranks.get(ch, {}).get(key))
            setattr(row, f"{ch}_score", channel_scores.get(ch, {}).get(key))
        # Prefer provenance scores when present (post-dedup merge)
        if c.provenance.bm25_score is not None:
            row.bm25_score = c.provenance.bm25_score
        if c.provenance.vector_score is not None:
            row.vector_score = c.provenance.vector_score
        if c.provenance.metadata_score is not None:
            row.metadata_score = c.provenance.metadata_score
        if c.provenance.matter_score is not None:
            row.matter_score = c.provenance.matter_score
        if c.provenance.hierarchical_score is not None:
            row.hierarchical_score = c.provenance.hierarchical_score
        if c.provenance.graph_score is not None:
            row.graph_seed_score = c.provenance.graph_score
        if c.provenance.similar_matter_score is not None:
            row.similar_matter_score = c.provenance.similar_matter_score
        rows.append(row)

    # Prefer rows that made it further in the pipeline when sorting
    rows.sort(key=lambda r: (r.final_rank or 10_000, r.rrf_rank or 10_000))
    return rows


def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def diagnose_query(
    query: str,
    *,
    query_id: str = "",
    query_type: str = "",
    member_id: str | None = None,
    k: int = 20,
    gold_docs: set[str] | None = None,
    gold_matters: set[str] | None = None,
) -> DiagnoseResult:
    """Run the live engine pipeline and attach stage ranks (no policy changes)."""
    if not pool_stats().get("initialized"):
        await init_pool()

    latency: dict[str, Any] = {}
    t0 = time.perf_counter()
    parsed = understand(query)
    latency["understand"] = round((time.perf_counter() - t0) * 1000, 1)

    empty = DiagnoseResult(
        query_id=query_id or "Q",
        query=query,
        query_type=query_type,
        intent=parsed.intent,
        plan_channels=[],
        plan_weights={},
        latency_ms=latency,
    )
    if parsed.intent == "empty" or not parsed.raw:
        return empty

    retrieval_plan = plan_retrieval(parsed)
    ctx = _build_context(parsed, member_id, k)

    async def _run(name: str) -> tuple[str, list[Candidate], float]:
        t = time.perf_counter()
        fn = _CHANNEL_FNS.get(name)
        if fn is None:
            return name, [], 0.0
        try:
            results = await fn(ctx, limit=50)
        except Exception as exc:
            logger.warning("diagnose channel %s failed: %s", name, exc)
            results = []
        return name, results, round((time.perf_counter() - t) * 1000, 1)

    t_par = time.perf_counter()
    channel_results = await asyncio.gather(*[_run(ch) for ch in retrieval_plan.channels])
    latency["parallel_wall_ms"] = round((time.perf_counter() - t_par) * 1000, 1)

    by_channel: dict[str, list[Candidate]] = {}
    all_candidates: list[Candidate] = []
    channel_counts: dict[str, int] = {}
    for name, candidates, elapsed in channel_results:
        by_channel[name] = candidates
        channel_counts[name] = len(candidates)
        latency[name] = elapsed
        all_candidates.extend(candidates)

    deduped = _deduplicate(all_candidates)

    if retrieval_plan.graph_expansion and deduped:
        expanded = await _graph_expand(
            deduped, member_id, depth=retrieval_plan.graph_expansion_depth,
        )
        if expanded:
            by_channel["graph_expansion"] = expanded
            channel_counts["graph_expansion"] = len(expanded)
            deduped.extend(expanded)
            deduped = _deduplicate(deduped)

    fusion_limit = retrieval_plan.rerank_candidates if retrieval_plan.rerank else retrieval_plan.final_k
    fusion_limit = max(fusion_limit, retrieval_plan.final_k, k, 50)
    fused = _fuse_candidates(deduped, weights=retrieval_plan.weights, limit=fusion_limit)

    fused_snapshot = list(fused)
    reranked: list[Candidate] | None = None
    # Keep a wide ranked list for diagnosis; still report returned top-k separately.
    diagnose_pool = max(k, 50)
    if retrieval_plan.rerank and fused:
        reranked = await _rerank_candidates(query, fused, retrieval_plan)
        final = reranked[:diagnose_pool]
    else:
        final = fused[:diagnose_pool]

    rows = assign_stage_ranks(
        query_id=query_id or "Q",
        query=query,
        query_type=query_type,
        intent=parsed.intent,
        by_channel=by_channel,
        fused=fused_snapshot,
        reranked=reranked,
        final=final,
        gold_docs=gold_docs or set(),
        gold_matters=gold_matters or set(),
    )

    return DiagnoseResult(
        query_id=query_id or "Q",
        query=query,
        query_type=query_type,
        intent=parsed.intent,
        plan_channels=list(retrieval_plan.channels),
        plan_weights=dict(retrieval_plan.weights),
        rows=rows,
        latency_ms=latency,
        channel_counts=channel_counts,
    )


def summarize_rows(rows: list[StageRow]) -> dict[str, Any]:
    """Aggregate diagnostics: channel contribution + stage-drop signals."""
    relevant = [r for r in rows if r.is_relevant]
    finals = [r for r in rows if r.final_rank is not None]

    # Channel co-occurrence among relevant candidates
    combo = Counter()
    for r in relevant:
        key = r.retrieved_by or "none"
        combo[key] += 1

    # Relevant best channel ranks vs final
    drops: list[dict[str, Any]] = []
    for r in relevant:
        channel_best = None
        for ch in CHANNEL_RANK_KEYS:
            rk = getattr(r, f"{ch}_rank")
            if rk is not None and (channel_best is None or rk < channel_best):
                channel_best = rk
        if channel_best is None:
            continue
        final_r = r.final_rank
        rrf_r = r.rrf_rank
        rrk = r.reranker_rank
        # Only flag when a channel had the doc near the top but final did not.
        if channel_best > 10:
            continue
        if final_r is not None and final_r <= 10:
            continue

        # Classify the first stage that pushed it out of top-10.
        if rrf_r is None or rrf_r > 10:
            stage = "fusion_or_hierarchy_channel"
        elif r.reranker_score is not None and (rrk is None or rrk > 10):
            stage = "reranker"
        else:
            stage = "final_topk_cutoff"

        drops.append({
            "query_id": r.query_id,
            "document_id": r.document_id,
            "best_channel_rank": channel_best,
            "rrf_rank": rrf_r,
            "reranker_rank": rrk,
            "final_rank": final_r,
            "retrieved_by": r.retrieved_by,
            "drop_stage": stage,
            "hierarchical_rank": r.hierarchical_rank,
            "hierarchical_score": r.hierarchical_score,
        })

    drop_stages = Counter(d["drop_stage"] for d in drops)

    # Relevant@K among final ranks
    def relevant_at(k: int) -> float:
        docs = {r.document_id for r in finals if r.final_rank and r.final_rank <= k and r.is_relevant}
        # This is query-agnostic aggregate — caller should prefer per-query metrics
        return float(len(docs))

    hier_relevant = [r for r in relevant if r.hierarchical_rank is not None]
    hier_only_relevant = [
        r for r in relevant
        if r.hierarchical_rank is not None
        and not any(
            getattr(r, f"{ch}_rank") is not None
            for ch in CHANNEL_RANK_KEYS
            if ch != "hierarchical"
        )
    ]

    return {
        "n_rows": len(rows),
        "n_relevant_rows": len(relevant),
        "n_final_rows": len(finals),
        "relevant_channel_combos": dict(combo.most_common(30)),
        "relevant_drop_count": len(drops),
        "relevant_drop_stages": dict(drop_stages),
        "relevant_drops_sample": drops[:50],
        "hierarchical_touched_relevant": len(hier_relevant),
        "hierarchical_only_relevant": len(hier_only_relevant),
        "final_relevant_doc_count_proxy": relevant_at(10),
    }


def per_query_ranking_stats(rows: list[StageRow]) -> dict[str, float]:
    """Hit@K / MRR style stats for one query's diagnostic rows (final ranks)."""
    gold_docs = {r.document_id for r in rows if r.is_relevant and r.gold_kind == "document"}
    gold_matters = {r.matter_id for r in rows if r.is_relevant and r.gold_kind == "matter"}
    finals = sorted(
        [r for r in rows if r.final_rank is not None],
        key=lambda r: r.final_rank or 9999,
    )
    if gold_docs:
        ranked = list(dict.fromkeys(r.document_id for r in finals))
        gold = gold_docs
    elif gold_matters:
        ranked = list(dict.fromkeys(r.matter_id for r in finals))
        gold = gold_matters
    else:
        return {"hit@10": 0.0, "mrr": 0.0, "relevant@1": 0.0, "relevant@5": 0.0, "relevant@10": 0.0}

    def hit(k: int) -> float:
        return 1.0 if set(ranked[:k]) & gold else 0.0

    mrr_v = 0.0
    for i, item in enumerate(ranked, start=1):
        if item in gold:
            mrr_v = 1.0 / i
            break

    return {
        "hit@10": hit(10),
        "mrr": mrr_v,
        "relevant@1": hit(1),
        "relevant@5": hit(5),
        "relevant@10": hit(10),
        "gold_size": float(len(gold)),
    }
