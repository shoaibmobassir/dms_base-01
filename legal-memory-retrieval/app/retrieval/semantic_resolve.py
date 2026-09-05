"""P5.6-C0 — Semantic document resolution via vector-matter routing.

Architecture (candidate generation only — not final ranking):

  Query
    → open-corpus vector (matter-deduped)
    → top-K matters
    → documents INSIDE those matters
    → BM25 + vector (scoped) + matter_scope heads
    → document candidate pool

Does not change embeddings, CE, or P5.6-A hard scope for matter_research.
Controlled by SEMANTIC_DOC_RESOLVE=c0 and SEMANTIC_MATTER_K (default 10).
"""
from __future__ import annotations

import os
from typing import Any

from app.retrieval.contracts import Candidate


def semantic_doc_resolve_mode() -> str:
    """off | c0 — semantic document resolution strategy."""
    mode = (os.environ.get("SEMANTIC_DOC_RESOLVE") or "off").strip().lower()
    if mode not in {"off", "c0"}:
        return "off"
    return mode


def semantic_matter_k(default: int = 10) -> int:
    raw = (os.environ.get("SEMANTIC_MATTER_K") or "").strip()
    if not raw:
        return default
    try:
        return max(1, min(100, int(raw)))
    except ValueError:
        return default


def should_semantic_doc_resolve(intent: str) -> bool:
    return intent == "semantic" and semantic_doc_resolve_mode() == "c0"


def rank_matters_from_vector(
    candidates: list[Candidate],
    *,
    k: int,
) -> list[dict[str, Any]]:
    """Dedupe vector hits to matters by best raw_score; return top-K matter rows."""
    best: dict[str, tuple[float, Candidate]] = {}
    for c in candidates:
        mid = c.matter_id
        if not mid:
            continue
        prev = best.get(mid)
        if prev is None or c.raw_score > prev[0]:
            best[mid] = (float(c.raw_score), c)
    ordered = sorted(best.values(), key=lambda t: t[0], reverse=True)[:k]
    return [
        {
            "matter_id": c.matter_id,
            "matter_code": c.matter_code,
            "title": c.title,
            "client_name": c.client_name,
            "score": score,
            "seed_document_id": c.document_id,
        }
        for score, c in ordered
    ]


def matter_ids_from_ranked(ranked: list[dict[str, Any]]) -> list[str]:
    return [str(r["matter_id"]) for r in ranked if r.get("matter_id")]


def routing_stats(
    ranked: list[dict[str, Any]],
    gold_matters: set[str],
    gold_docs: set[str],
    docs_in_scope: set[str] | None = None,
) -> dict[str, Any]:
    """Coverage metrics for the matter→document routing layer."""
    routed = {str(r["matter_id"]) for r in ranked}
    k = len(routed)
    gold_m_hit = routed & gold_matters
    matter_recall = (len(gold_m_hit) / len(gold_matters)) if gold_matters else 0.0
    matter_precision = (len(gold_m_hit) / k) if k else 0.0
    matter_hit = 1.0 if gold_m_hit else 0.0

    ceiling = None
    if docs_in_scope is not None and gold_docs:
        ceiling = len(docs_in_scope & gold_docs) / len(gold_docs)

    return {
        "matter_k": k,
        "matter_recall": round(matter_recall, 4),
        "matter_precision": round(matter_precision, 4),
        "matter_hit": matter_hit,
        "gold_matters_in_routed": len(gold_m_hit),
        "n_gold_matters": len(gold_matters),
        "doc_recall_ceiling": round(ceiling, 4) if ceiling is not None else None,
        "routed_matter_ids": sorted(routed),
    }
