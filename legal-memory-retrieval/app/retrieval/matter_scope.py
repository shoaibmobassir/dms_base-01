"""P5.6 matter scope — hierarchy decides WHERE to search, not final relevance.

Modes (MATTER_SCOPE env):
  off   — P5.5 baseline (matter channel may still score in fusion)
  score — matter as fusion score (boost matter RRF weight; no hard filter)
  hard  — resolve candidate matters, then scope BM25/vector/metadata to them
  hier  — hard scope + hierarchical Matter→Doc→Chunk within those matters

Optional MATTER_SCOPE_CHANNELS (comma list) restricts channels for scoped intents
(used by ablation D vs E).
"""
from __future__ import annotations

import os
from typing import Any


# Intents where matter is a hard WHERE filter (P5.6-A track).
# similar_matter / semantic stay open-corpus for tracks 6.2–6.3.
HARD_SCOPE_INTENTS = frozenset({
    "matter_research",
    "experience_search",
})

SCORE_BOOST_INTENTS = frozenset({
    "matter_research",
    "similar_matter",
    "semantic",
    "experience_search",
})

VALID_MODES = frozenset({"off", "score", "hard", "hier"})


def active_matter_scope() -> str:
    # Default hard: resolve matters → scope BM25/vector; matter_scope heads (not matter-as-score).
    # Override with MATTER_SCOPE=off to freeze pure P5.5 behavior.
    mode = (os.environ.get("MATTER_SCOPE") or "hard").strip().lower()
    if mode not in VALID_MODES:
        return "hard"
    return mode


def should_apply_matter_scope(intent: str, mode: str | None = None) -> bool:
    """True when we resolve matters and hard-filter retrieval to them."""
    m = mode or active_matter_scope()
    return m in {"hard", "hier"} and intent in HARD_SCOPE_INTENTS


def should_boost_matter_score(intent: str, mode: str | None = None) -> bool:
    m = mode or active_matter_scope()
    return m == "score" and intent in SCORE_BOOST_INTENTS


def channel_override(mode: str | None = None) -> list[str] | None:
    """Optional channel whitelist for scoped intents (ablation D vs E)."""
    raw = (os.environ.get("MATTER_SCOPE_CHANNELS") or "").strip()
    if not raw:
        return None
    m = mode or active_matter_scope()
    if m not in {"hard", "hier"}:
        return None
    return [c.strip() for c in raw.split(",") if c.strip()]


def apply_channel_plan(
    planned: list[str],
    intent: str,
    mode: str | None = None,
) -> list[str]:
    m = mode or active_matter_scope()
    channels = list(planned)
    if should_apply_matter_scope(intent, m):
        # Inject scoped document heads; drop generic matter-as-score channel.
        channels = [c for c in channels if c != "matter"]
        if "matter_scope" not in channels:
            channels.append("matter_scope")
    if m == "hier" and intent in HARD_SCOPE_INTENTS and "hierarchical" not in channels:
        channels.append("hierarchical")
    override = channel_override(m)
    if override and should_apply_matter_scope(intent, m):
        allowed = set(override) | {"matter_scope"}
        filtered = [c for c in channels if c in allowed]
        # Always keep matter_scope under hard/hier unless override is hier-only experiment
        if "matter_scope" not in filtered and "hierarchical" not in (override or []):
            filtered.append("matter_scope")
        if "hierarchical" in (override or []) and set(override) == {"hierarchical"}:
            # Ablation D: hierarchical only
            return ["hierarchical"]
        return filtered if filtered else list(allowed)
    return channels


def adjust_fusion_weights(
    weights: dict[str, float],
    intent: str,
    mode: str | None = None,
) -> dict[str, float]:
    """Under hard/hier: demote matter-as-score; promote scoped document heads."""
    m = mode or active_matter_scope()
    out = dict(weights)
    if should_apply_matter_scope(intent, m):
        out["matter"] = 0.0
        # Document heads from resolved matters — scope evidence, not generic matter score
        out["matter_scope"] = max(float(out.get("matter_scope") or 0.0), 1.2)
    elif should_boost_matter_score(intent, m):
        out["matter"] = max(float(out.get("matter") or 0.0), 1.5)
    return out


def scope_filters(matter_ids: list[str], intent: str, mode: str | None = None) -> dict[str, Any] | None:
    if should_apply_matter_scope(intent, mode) and matter_ids:
        return {"matter_ids": list(matter_ids)}
    return None


def scope_stats(matters: list[dict[str, Any]], corpus_documents: int | None = None) -> dict[str, Any]:
    doc_universe = sum(int(m.get("document_count") or 0) for m in matters)
    stats: dict[str, Any] = {
        "matter_count": len(matters),
        "document_universe": doc_universe,
        "matter_ids": [m["matter_id"] for m in matters],
        "top_matters": [
            {
                "matter_id": m["matter_id"],
                "title": m.get("title"),
                "client_name": m.get("client_name"),
                "score": float(m.get("score") or 0.0),
                "document_count": int(m.get("document_count") or 0),
            }
            for m in matters[:8]
        ],
    }
    if corpus_documents and doc_universe > 0:
        stats["candidate_reduction_ratio"] = round(corpus_documents / doc_universe, 2)
    return stats
