"""P5.6-C5 — Theme-scoped document resolution (hierarchical routing).

Routing primitive is ``theme_key`` (from C4), not chunk-vector matter top-K.

  Query → theme resolver → ALL matters in theme(s) → documents
       → BM25 / Vector (scoped) → RRF candidates

Env:
  THEME_SCOPED_DOCUMENT_RETRIEVAL=off|on  (preferred name; default off)
  THEME_SCOPED_DOCUMENT_RESOLVE=off|on    (legacy alias)
  THEME_SCOPE_MAX_THEMES=1                (ablate 1–3)

Does not enable CE; does not change P5.6-A hard matter scope.
"""
from __future__ import annotations

import os
from typing import Any

from app.retrieval.matter_profile import (
    QueryEvidenceIntent,
    build_query_evidence_intent,
    infer_theme_keys,
)
from app.retrieval.matter_resolver import rrf_merge_matter_lists


def theme_scoped_resolve_enabled() -> bool:
    """True if theme-scoped document retrieval is enabled.

    Prefer ``THEME_SCOPED_DOCUMENT_RETRIEVAL``; accept legacy
    ``THEME_SCOPED_DOCUMENT_RESOLVE``. Either flag set to on enables.
    """
    on = {"on", "1", "true", "yes"}
    for key in ("THEME_SCOPED_DOCUMENT_RETRIEVAL", "THEME_SCOPED_DOCUMENT_RESOLVE"):
        raw = (os.environ.get(key) or "").strip().lower()
        if raw in on:
            return True
    return False


def theme_scope_max_themes(default: int = 1) -> int:
    raw = (os.environ.get("THEME_SCOPE_MAX_THEMES") or "").strip()
    if not raw:
        return default
    try:
        return max(1, min(5, int(raw)))
    except ValueError:
        return default


def resolve_theme_keys(
    question: str,
    *,
    search_text: str | None = None,
    practice_area: str | None = None,
    max_themes: int | None = None,
) -> QueryEvidenceIntent:
    intent = build_query_evidence_intent(
        question, search_text=search_text, practice_area=practice_area,
    )
    n = max_themes if max_themes is not None else theme_scope_max_themes()
    intent.theme_keys = intent.theme_keys[:n]
    return intent


def rrf_merge_doc_lists(
    ranked_lists: list[list[dict[str, Any]]],
    *,
    k: int,
    rrf_k: int = 60,
    weights: list[float] | None = None,
) -> list[dict[str, Any]]:
    """RRF over document_id ranked lists (reuse matter RRF shape)."""
    # Adapt matter RRF by mapping document_id → matter_id field name trick
    adapted = []
    for ranked in ranked_lists:
        adapted.append([
            {
                "matter_id": r["document_id"],  # rrf helper keys on matter_id
                "document_id": r["document_id"],
                "score": r.get("score", 0.0),
                **{kk: vv for kk, vv in r.items() if kk not in {"matter_id", "document_id", "score"}},
            }
            for r in ranked
        ])
    merged = rrf_merge_matter_lists(adapted, k=k, rrf_k=rrf_k, weights=weights)
    out = []
    for row in merged:
        doc_id = row.get("document_id") or row.get("matter_id")
        out.append({**row, "document_id": doc_id})
    return out


def scope_reduction_ratio(corpus_docs: int, scoped_docs: int) -> float | None:
    if not scoped_docs:
        return None
    return round(corpus_docs / scoped_docs, 2)


# Re-export for callers
__all__ = [
    "theme_scoped_resolve_enabled",
    "theme_scope_max_themes",
    "resolve_theme_keys",
    "rrf_merge_doc_lists",
    "scope_reduction_ratio",
    "infer_theme_keys",
    "QueryEvidenceIntent",
]
