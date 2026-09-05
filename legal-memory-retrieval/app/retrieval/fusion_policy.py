"""P5.5 fusion / ranking policies — candidate gen vs ranking separation.

Hierarchy / matter / graph expand the candidate universe.
Lexical + metadata + vector evidence dominate rank-based fusion.
Cross-encoder orders evidence but cannot erase strong structured/lexical hits.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FusionPolicy:
    """Named, ablatable ranking policy (no LLM / embedding changes)."""

    name: str
    # Per-channel RRF weights (0 = channel may still retrieve but does not rank)
    weights: dict[str, float] = field(default_factory=dict)
    # Candidate-generation budgets (FIND, not rank)
    channel_limits: dict[str, int] = field(default_factory=dict)
    # After CE: blend CE with fusion + lexical/metadata protection
    ce_protection: bool = False
    ce_weight: float = 0.45
    fusion_weight: float = 0.30
    lexical_protect_weight: float = 0.25
    # Planner still includes hierarchical channel for recall when True
    include_hierarchical_channel: bool = True


# Generous generation budgets (P5.5 candidate generation)
_GEN = {
    "bm25": 100,
    "vector": 100,
    "metadata": 100,
    "matter": 50,
    "hierarchical": 50,
    "graph_seed": 50,
    "similar_matter": 50,
}

# Pre-P5.5 / P5.3-ish weights (for ablation reference only)
_P53_WEIGHTS = {
    "bm25": 1.2,
    "vector": 0.75,
    "metadata": 1.5,
    "matter": 1.3,
    "hierarchical": 1.2,
    "graph_seed": 0.9,
    "similar_matter": 0.8,
}

# Repair default: demoted hierarchy/graph/matter; keep gen budgets tight (wide gen hurt Hit@10)
_REPAIR_WEIGHTS = {
    "bm25": 1.0,
    "vector": 1.0,
    "metadata": 1.2,
    "matter": 0.5,
    "hierarchical": 0.0,  # discover via cascade; do not RRF-rank on hierarchy alone
    "graph_seed": 0.3,
    "similar_matter": 0.4,
    "graph_expansion": 0.25,
}

_TIGHT = {k: 50 for k in _GEN}

POLICIES: dict[str, FusionPolicy] = {
    "p53": FusionPolicy(
        name="p53",
        weights=dict(_P53_WEIGHTS),
        channel_limits={k: 50 for k in _GEN},
        ce_protection=False,
        include_hierarchical_channel=True,
    ),
    "no_hierarchy_rank": FusionPolicy(
        name="no_hierarchy_rank",
        weights={**_P53_WEIGHTS, "hierarchical": 0.0},
        channel_limits={k: 50 for k in _GEN},
        ce_protection=False,
        include_hierarchical_channel=True,
    ),
    "rrf_equal": FusionPolicy(
        name="rrf_equal",
        weights={
            "bm25": 1.0,
            "vector": 1.0,
            "metadata": 1.0,
            "matter": 1.0,
            "hierarchical": 1.0,
            "graph_seed": 1.0,
            "similar_matter": 1.0,
            "graph_expansion": 1.0,
        },
        channel_limits=dict(_TIGHT),
        ce_protection=False,
        include_hierarchical_channel=True,
    ),
    # Default production repair (P5.5.1–5.5.3)
    "p55_repair": FusionPolicy(
        name="p55_repair",
        weights=dict(_REPAIR_WEIGHTS),
        channel_limits=dict(_TIGHT),
        ce_protection=False,
        include_hierarchical_channel=True,
    ),
    "p55_wide_gen": FusionPolicy(
        name="p55_wide_gen",
        weights=dict(_REPAIR_WEIGHTS),
        channel_limits=dict(_GEN),
        ce_protection=False,
        include_hierarchical_channel=True,
    ),
    "p55_no_hier_channel": FusionPolicy(
        name="p55_no_hier_channel",
        weights=dict(_REPAIR_WEIGHTS),
        channel_limits=dict(_TIGHT),
        ce_protection=False,
        include_hierarchical_channel=False,
    ),
    "p55_repair_ce_protect": FusionPolicy(
        name="p55_repair_ce_protect",
        weights=dict(_REPAIR_WEIGHTS),
        channel_limits=dict(_TIGHT),
        ce_protection=True,
        include_hierarchical_channel=True,
    ),
    "graph_demote": FusionPolicy(
        name="graph_demote",
        weights={
            **_REPAIR_WEIGHTS,
            "hierarchical": 0.25,
            "graph_seed": 0.3,
            "matter": 0.5,
        },
        channel_limits=dict(_TIGHT),
        ce_protection=False,
        include_hierarchical_channel=True,
    ),
}


def active_policy() -> FusionPolicy:
    """Select policy via FUSION_POLICY env (default: frozen CE-protect baseline)."""
    name = (os.environ.get("FUSION_POLICY") or "p55_repair_ce_protect").strip()
    return POLICIES.get(name, POLICIES["p55_repair_ce_protect"])


def merge_plan_weights(
    base: dict[str, float],
    policy: FusionPolicy | None = None,
    *,
    intent: str | None = None,
) -> dict[str, float]:
    """Overlay policy weights onto planner intent weights for enabled channels."""
    pol = policy or active_policy()
    # Exact lookups are precision-first — keep planner metadata dominance.
    if intent == "exact_lookup":
        return dict(base)
    out = dict(base)
    for ch in list(out.keys()):
        if ch in pol.weights:
            out[ch] = pol.weights[ch]
    # Graph-reasoning queries still need graph as a primary recall+rank signal.
    if intent == "graph_reasoning":
        out["graph_seed"] = max(float(out.get("graph_seed", 0.0)), 1.8)
        out["vector"] = max(float(out.get("vector", 0.0)), 1.0)
        out["bm25"] = max(float(out.get("bm25", 0.0)), 0.6)
    return out


def channel_limit(channel: str, default: int = 50, policy: FusionPolicy | None = None) -> int:
    pol = policy or active_policy()
    return int(pol.channel_limits.get(channel, default))


def apply_ce_protection(candidates: list[Any], policy: FusionPolicy | None = None) -> list[Any]:
    """Evidence-aware blend: CE + fusion + lexical/metadata protection lane."""
    pol = policy or active_policy()
    if not pol.ce_protection or len(candidates) <= 1:
        return candidates

    ces = [float(c.rerank_score or c.provenance.ce_score or 0.0) for c in candidates]
    fuses = [float(c.fusion_score or 0.0) for c in candidates]
    ce_min, ce_max = min(ces), max(ces)
    fu_min, fu_max = min(fuses), max(fuses)

    def norm(v: float, lo: float, hi: float) -> float:
        if hi <= lo:
            return 0.0
        return (v - lo) / (hi - lo)

    protect = {"bm25", "metadata"}
    scored: list[tuple[float, Any]] = []
    for c, ce, fu in zip(candidates, ces, fuses):
        channels = set(c.provenance.channels_found_in or [])
        if c.channel:
            channels.add(c.channel)
        lex = 1.0 if channels & protect else 0.0
        final = (
            pol.ce_weight * norm(ce, ce_min, ce_max)
            + pol.fusion_weight * norm(fu, fu_min, fu_max)
            + pol.lexical_protect_weight * lex
        )
        if c.provenance.ce_score is None and c.rerank_score is not None:
            c.provenance.ce_score = float(c.rerank_score)
        c.rerank_score = round(final, 6)
        scored.append((final, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored]


def policy_to_dict(policy: FusionPolicy | None = None) -> dict[str, Any]:
    pol = policy or active_policy()
    return {
        "name": pol.name,
        "weights": dict(pol.weights),
        "channel_limits": dict(pol.channel_limits),
        "ce_protection": pol.ce_protection,
        "ce_weight": pol.ce_weight,
        "fusion_weight": pol.fusion_weight,
        "lexical_protect_weight": pol.lexical_protect_weight,
    }
