"""P5.6-B0 — Semantic candidate survival (diagnosis only).

Answers: is gold missing from candidate generation, fusion, or CE?

Does not change matter routing, fusion weights, or embeddings.
Mirrors the live engine path (matter_scope + fusion policy + CE protect).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.db.pool import acquire, init_pool, pool_stats
from app.query.understand import understand
from app.retrieval.contracts import Candidate
from app.retrieval.engine_v2 import (
    _CHANNEL_FNS,
    _build_context,
    _deduplicate,
    _fuse_candidates,
    _graph_expand,
    _matter_store,
    _rerank_candidates,
)
from app.retrieval.fusion_policy import (
    active_policy,
    apply_ce_protection,
    channel_limit,
    merge_plan_weights,
)
from app.retrieval.matter_scope import (
    active_matter_scope,
    adjust_fusion_weights,
    apply_channel_plan,
    scope_stats,
    should_apply_matter_scope,
)
from app.retrieval.planner import plan as plan_retrieval

logger = logging.getLogger(__name__)

STAGE_KS = (5, 10, 20, 50)


def _recall_at_k(gold: set[str], ranked: list[str], k: int) -> float:
    if not gold:
        return 0.0
    return len(set(ranked[:k]) & gold) / len(gold)


@dataclass
class ChannelSurvival:
    name: str
    n_candidates: int
    n_unique_docs: int
    gold_docs_hit: int
    gold_doc_ids: list[str]
    recall: dict[str, float] = field(default_factory=dict)
    hit: dict[str, float] = field(default_factory=dict)
    n_unique_matters: int = 0
    gold_matters_hit: int = 0
    matter_recall: dict[str, float] = field(default_factory=dict)
    matter_hit: dict[str, float] = field(default_factory=dict)


@dataclass
class QuerySurvival:
    query_id: str
    query: str
    intent: str
    n_gold_docs: int
    n_gold_matters: int
    channels_planned: list[str]
    matter_scope_mode: str
    fusion_policy: str
    channel: dict[str, ChannelSurvival] = field(default_factory=dict)
    union: ChannelSurvival | None = None
    fusion: ChannelSurvival | None = None
    ce: ChannelSurvival | None = None
    final: ChannelSurvival | None = None
    drop_stage: str = ""
    latency_ms: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _doc_ranked(candidates: list[Candidate]) -> list[str]:
    """Unique document_ids in rank order (first occurrence wins)."""
    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        did = c.document_id
        if not did or did in seen:
            continue
        seen.add(did)
        out.append(did)
    return out


def _matter_ranked(candidates: list[Candidate]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        mid = c.matter_id
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
    return out


def _survival(
    name: str,
    candidates: list[Candidate],
    gold_docs: set[str],
    gold_matters: set[str] | None = None,
) -> ChannelSurvival:
    ranked = _doc_ranked(candidates)
    hit_ids = [d for d in ranked if d in gold_docs]
    recall = {f"R@{k}": _recall_at_k(gold_docs, ranked, k) for k in STAGE_KS}
    hit = {
        f"Hit@{k}": 1.0 if set(ranked[:k]) & gold_docs else 0.0
        for k in STAGE_KS
    }
    gold_matters = gold_matters or set()
    m_ranked = _matter_ranked(candidates)
    return ChannelSurvival(
        name=name,
        n_candidates=len(candidates),
        n_unique_docs=len(ranked),
        gold_docs_hit=len(set(hit_ids)),
        gold_doc_ids=sorted(set(hit_ids)),
        recall=recall,
        hit=hit,
        n_unique_matters=len(m_ranked),
        gold_matters_hit=len(set(m_ranked) & gold_matters) if gold_matters else 0,
        matter_recall={
            f"R@{k}": _recall_at_k(gold_matters, m_ranked, k) if gold_matters else 0.0
            for k in STAGE_KS
        },
        matter_hit={
            f"Hit@{k}": (
                1.0 if gold_matters and set(m_ranked[:k]) & gold_matters else 0.0
            )
            for k in STAGE_KS
        },
    )


def _classify_drop(row: QuerySurvival) -> str:
    """Name the first stage where R@20 collapses relative to the previous."""
    stages: list[tuple[str, float | None]] = []
    if row.union:
        stages.append(("union", row.union.recall.get("R@20")))
    if row.fusion:
        stages.append(("fusion", row.fusion.recall.get("R@20")))
    if row.ce:
        stages.append(("ce", row.ce.recall.get("R@20")))
    if row.final:
        stages.append(("final", row.final.recall.get("R@20")))

    if not stages or stages[0][1] is None:
        return "no_candidates"

    union_r = stages[0][1] or 0.0
    if union_r < 0.40:
        # Check if any channel had better recall
        ch_best = 0.0
        for ch in row.channel.values():
            ch_best = max(ch_best, ch.recall.get("R@20") or 0.0)
        if ch_best < 0.40:
            return "candidate_generation"
        return "candidate_generation"

    prev = union_r
    for name, val in stages[1:]:
        cur = val or 0.0
        if prev - cur >= 0.15:
            return name
        prev = cur
    if (row.final.recall.get("R@20") if row.final else 0) and (
        (row.final.recall.get("R@20") or 0) < 0.40
    ):
        return "final_rank"
    return "survives"


async def semantic_survival_query(
    query: str,
    *,
    query_id: str = "",
    member_id: str | None = None,
    gold_docs: set[str] | None = None,
    gold_matters: set[str] | None = None,
    k: int = 20,
) -> QuerySurvival:
    """Instrument live pipeline stages for one semantic query (no policy changes)."""
    gold_docs = gold_docs or set()
    gold_matters = gold_matters or set()

    if not pool_stats().get("initialized"):
        await init_pool()

    latency: dict[str, Any] = {}
    t0 = time.perf_counter()
    parsed = understand(query)
    latency["understand"] = round((time.perf_counter() - t0) * 1000, 1)

    result = QuerySurvival(
        query_id=query_id or "Q",
        query=query,
        intent=parsed.intent,
        n_gold_docs=len(gold_docs),
        n_gold_matters=len(gold_matters),
        channels_planned=[],
        matter_scope_mode=active_matter_scope(),
        fusion_policy=active_policy().name,
        latency_ms=latency,
    )
    if parsed.intent == "empty" or not parsed.raw:
        result.drop_stage = "empty"
        return result

    retrieval_plan = plan_retrieval(parsed)
    ctx = _build_context(parsed, member_id, k)
    policy = active_policy()
    scope_mode = active_matter_scope()

    if should_apply_matter_scope(parsed.intent, scope_mode):
        needle = ctx.client_name or ctx.query_search_text or ctx.query_raw
        async with acquire() as conn:
            matters = await _matter_store.resolve_matters(
                conn, needle, ctx.member_id, limit=20,
            )
        if matters:
            ctx.matter_ids = [str(m["matter_id"]) for m in matters]
            latency["matter_scope"] = scope_stats(matters)

    planned = list(retrieval_plan.channels)
    if not policy.include_hierarchical_channel:
        planned = [c for c in planned if c != "hierarchical"]
    planned = apply_channel_plan(planned, parsed.intent, scope_mode)
    result.channels_planned = planned

    async def _run(name: str) -> tuple[str, list[Candidate], float]:
        t = time.perf_counter()
        fn = _CHANNEL_FNS.get(name)
        if fn is None:
            return name, [], 0.0
        limit = channel_limit(name, default=50, policy=policy)
        try:
            cands = await fn(ctx, limit=limit)
        except Exception as exc:
            logger.warning("survival channel %s failed: %s", name, exc)
            cands = []
        return name, cands, round((time.perf_counter() - t) * 1000, 1)

    t_par = time.perf_counter()
    channel_results = await asyncio.gather(*[_run(ch) for ch in planned])
    latency["parallel_wall_ms"] = round((time.perf_counter() - t_par) * 1000, 1)

    by_channel: dict[str, list[Candidate]] = {}
    all_cands: list[Candidate] = []
    for name, cands, elapsed in channel_results:
        by_channel[name] = cands
        latency[name] = elapsed
        all_cands.extend(cands)
        # Rank channel by raw_score for survival metrics
        ordered = sorted(cands, key=lambda c: c.raw_score, reverse=True)
        result.channel[name] = _survival(name, ordered, gold_docs, gold_matters)

    deduped = _deduplicate(all_cands)
    result.union = _survival("union", deduped, gold_docs, gold_matters)

    if retrieval_plan.graph_expansion and deduped:
        expanded = await _graph_expand(
            deduped, member_id, depth=retrieval_plan.graph_expansion_depth,
        )
        if expanded:
            by_channel["graph_expansion"] = expanded
            result.channel["graph_expansion"] = _survival(
                "graph_expansion",
                sorted(expanded, key=lambda c: c.raw_score, reverse=True),
                gold_docs,
                gold_matters,
            )
            deduped.extend(expanded)
            deduped = _deduplicate(deduped)
            result.union = _survival("union", deduped, gold_docs, gold_matters)

    fusion_limit = retrieval_plan.rerank_candidates if retrieval_plan.rerank else retrieval_plan.final_k
    fusion_limit = max(fusion_limit, retrieval_plan.final_k, k, 50)
    weights = merge_plan_weights(
        retrieval_plan.weights, policy, intent=parsed.intent,
    )
    weights = adjust_fusion_weights(weights, parsed.intent, scope_mode)
    fused = _fuse_candidates(deduped, weights=weights, limit=fusion_limit)
    result.fusion = _survival("fusion", fused, gold_docs, gold_matters)

    if retrieval_plan.rerank and fused:
        t_ce = time.perf_counter()
        reranked = await _rerank_candidates(query, fused, retrieval_plan)
        reranked = apply_ce_protection(reranked, policy)
        latency["rerank"] = round((time.perf_counter() - t_ce) * 1000, 1)
        result.ce = _survival("ce", reranked, gold_docs, gold_matters)
        result.final = _survival("final", reranked[:k], gold_docs, gold_matters)
    else:
        result.ce = _survival("ce", fused, gold_docs, gold_matters)
        result.final = _survival("final", fused[:k], gold_docs, gold_matters)

    result.drop_stage = _classify_drop(result)
    result.latency_ms = latency
    return result


def aggregate_survival(rows: list[QuerySurvival]) -> dict[str, Any]:
    """Mean R@K / Hit@K across queries for each pipeline stage."""

    def mean_stage(getter, *, matter: bool = False) -> dict[str, float]:
        recalls = {f"R@{k}": [] for k in STAGE_KS}
        hits = {f"Hit@{k}": [] for k in STAGE_KS}
        for row in rows:
            stage = getter(row)
            if stage is None:
                continue
            rec = stage.matter_recall if matter else stage.recall
            ht = stage.matter_hit if matter else stage.hit
            for k in STAGE_KS:
                recalls[f"R@{k}"].append(rec.get(f"R@{k}", 0.0))
                hits[f"Hit@{k}"].append(ht.get(f"Hit@{k}", 0.0))
        out: dict[str, float] = {}
        for key, vals in {**recalls, **hits}.items():
            out[key] = round(sum(vals) / len(vals), 4) if vals else 0.0
        return out

    channel_names = sorted({ch for r in rows for ch in r.channel})
    by_channel = {
        name: mean_stage(lambda r, n=name: r.channel.get(n))
        for name in channel_names
    }
    by_channel_matter = {
        name: mean_stage(lambda r, n=name: r.channel.get(n), matter=True)
        for name in channel_names
    }

    drop_counts: dict[str, int] = {}
    for r in rows:
        drop_counts[r.drop_stage] = drop_counts.get(r.drop_stage, 0) + 1

    table = {
        "bm25": by_channel.get("bm25", {}),
        "vector": by_channel.get("vector", {}),
        "metadata": by_channel.get("metadata", {}),
        "matter": by_channel.get("matter", {}),
        "matter_scope": by_channel.get("matter_scope", {}),
        "hierarchical": by_channel.get("hierarchical", {}),
        "graph_seed": by_channel.get("graph_seed", {}),
        "union": mean_stage(lambda r: r.union),
        "fusion": mean_stage(lambda r: r.fusion),
        "ce": mean_stage(lambda r: r.ce),
        "final": mean_stage(lambda r: r.final),
    }
    matter_table = {
        "bm25": by_channel_matter.get("bm25", {}),
        "vector": by_channel_matter.get("vector", {}),
        "matter": by_channel_matter.get("matter", {}),
        "union": mean_stage(lambda r: r.union, matter=True),
        "fusion": mean_stage(lambda r: r.fusion, matter=True),
        "ce": mean_stage(lambda r: r.ce, matter=True),
        "final": mean_stage(lambda r: r.final, matter=True),
    }

    # Outcome classification for the whole semantic set
    union_r20 = table["union"].get("R@20", 0.0)
    fusion_r20 = table["fusion"].get("R@20", 0.0)
    ce_r20 = table["ce"].get("R@20", 0.0)
    vector_r20 = table["vector"].get("R@20", 0.0)

    if union_r20 < 0.40:
        outcome = "A_candidate_generation"
        guidance = "Gold barely enters the pool — fix vector/BM25/query rep; do not touch CE."
    elif union_r20 - fusion_r20 >= 0.15:
        outcome = "B_fusion_drop"
        guidance = "Union recall is healthy; fusion is dropping gold — fix RRF/weights; do not touch CE."
    elif fusion_r20 - ce_r20 >= 0.15:
        outcome = "C_reranker_drop"
        guidance = "Legitimate CE/reranker problem — context enrichment or CE protection next."
    else:
        outcome = "D_survives_or_final_rank"
        guidance = "Pool/fusion/CE hold R@20; losses are mostly final@10 truncation or ranking within top-20."

    return {
        "n": len(rows),
        "stage_table_R@20": {k: v.get("R@20", 0.0) for k, v in table.items()},
        "stage_table_Hit@20": {k: v.get("Hit@20", 0.0) for k, v in table.items()},
        "stage_table_full": table,
        "matter_stage_table_R@20": {k: v.get("R@20", 0.0) for k, v in matter_table.items()},
        "matter_stage_table_Hit@20": {k: v.get("Hit@20", 0.0) for k, v in matter_table.items()},
        "drop_stage_counts": drop_counts,
        "vector_R@20": vector_r20,
        "union_R@20": union_r20,
        "fusion_R@20": fusion_r20,
        "ce_R@20": ce_r20,
        "outcome": outcome,
        "guidance": guidance,
    }
