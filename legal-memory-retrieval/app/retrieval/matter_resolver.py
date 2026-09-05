"""P5.6-C1 — Evidence-oriented matter resolver (holder-matter focus).

Discovers matters likely to *contain* answering documents, not merely
theme-adjacent matters. Diagnosis-only until holder coverage clears a gate.

Components (abatable):
  lexical_or  — OR-style FTS over matter metadata fields (weighted)
  structured  — deterministic query expansion (concepts / practice / terms)
  vector      — open-corpus chunk vector → matter-deduped ranks
  hybrid_rrf  — RRF merge of lexical + vector matter lists

Env (optional; eval harness sets explicitly):
  MATTER_RESOLVER=off|lexical|vector|hybrid
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from app.retrieval.contracts import Candidate
from app.retrieval.semantic_resolve import rank_matters_from_vector


_STOP = frozenset({
    "a", "an", "the", "and", "or", "of", "on", "in", "for", "to", "with",
    "we", "have", "had", "has", "been", "being", "is", "are", "was", "were",
    "do", "does", "did", "done", "what", "which", "who", "whom", "whose",
    "this", "that", "these", "those", "as", "by", "from", "at", "into",
    "about", "over", "under", "between", "our", "their", "its", "it",
})

# Controlled legal expansions for semantic themes (deterministic; not an LLM).
_CONCEPT_EXPAND: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"insider|upsi|price.?sensitive|scn", re.I),
     ("insider trading", "unpublished price sensitive", "UPSI", "SCN", "SEBI")),
    (re.compile(r"non-?compete|restraint of trade|post-employment", re.I),
     ("non-compete", "restraint of trade", "post-employment", "restrictive covenant")),
    (re.compile(r"title diligence|family settlement|unregistered", re.I),
     ("title diligence", "family settlement", "unregistered", "real estate")),
    (re.compile(r"transfer pricing|intra-?group|management fee", re.I),
     ("transfer pricing", "intra-group", "management fees", "tax")),
    (re.compile(r"terminat|quality failure|supply.?contract", re.I),
     ("termination", "supply contract", "quality failure", "breach")),
    (re.compile(r"joint venture|deadlock|shotgun|50:50|50\s*:\s*50", re.I),
     ("joint venture", "deadlock", "shotgun", "shareholders agreement")),
    (re.compile(r"natural disaster|force majeure|contractual performance", re.I),
     ("natural disaster", "force majeure", "contractual performance", "impossibility")),
)


@dataclass
class MatterQueryRep:
    """Structured retrieval representation (no LLM)."""

    original: str
    search_text: str
    practice_area: str | None = None
    terms: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)

    def lexical_terms(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for t in self.phrases + self.concepts + self.terms:
            key = t.lower().strip()
            if len(key) < 2 or key in seen:
                continue
            seen.add(key)
            out.append(t.strip())
        return out

    def vector_text(self) -> str:
        """Text to embed: original + concepts (keep original dominant)."""
        parts = [self.original]
        if self.concepts:
            parts.append(" ".join(self.concepts[:8]))
        if self.practice_area:
            parts.append(self.practice_area)
        return " ".join(parts)


def build_matter_query_rep(
    raw: str,
    *,
    search_text: str | None = None,
    practice_area: str | None = None,
) -> MatterQueryRep:
    text = (search_text or raw or "").strip()
    concepts: list[str] = []
    for pattern, exps in _CONCEPT_EXPAND:
        if pattern.search(raw) or pattern.search(text):
            concepts.extend(exps)

    # Tokens + simple bigrams from cleaned search text
    tokens = [
        t for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9:/-]{1,}", text)
        if t.lower() not in _STOP and not t.isdigit()
    ]
    phrases: list[str] = []
    for a, b in zip(tokens, tokens[1:]):
        phrases.append(f"{a} {b}")
    # Prefer longer distinctive tokens
    terms = sorted(set(tokens), key=lambda t: (-len(t), t.lower()))[:24]

    return MatterQueryRep(
        original=raw,
        search_text=text,
        practice_area=practice_area,
        terms=terms,
        concepts=list(dict.fromkeys(concepts)),
        phrases=phrases[:12],
    )


def to_or_tsquery(terms: list[str], *, max_terms: int = 16) -> str | None:
    """Build a safe OR tsquery string from terms/phrases."""
    parts: list[str] = []
    for term in terms[:max_terms]:
        words = re.findall(r"[A-Za-z0-9]+", term.lower())
        words = [w for w in words if w not in _STOP and len(w) > 1]
        if not words:
            continue
        if len(words) == 1:
            parts.append(words[0])
        else:
            # phrase as AND within OR branch: word1 & word2
            parts.append("(" + " & ".join(words[:4]) + ")")
    if not parts:
        return None
    return " | ".join(parts)


def rrf_merge_matter_lists(
    ranked_lists: list[list[dict[str, Any]]],
    *,
    k: int,
    rrf_k: int = 60,
    weights: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Weighted RRF over matter_id ranked lists."""
    weights = weights or [1.0] * len(ranked_lists)
    scores: dict[str, float] = {}
    best_row: dict[str, dict[str, Any]] = {}
    for w, ranked in zip(weights, ranked_lists):
        for i, row in enumerate(ranked):
            mid = str(row["matter_id"])
            scores[mid] = scores.get(mid, 0.0) + float(w) / (rrf_k + i + 1)
            if mid not in best_row or float(row.get("score") or 0) > float(
                best_row[mid].get("score") or 0
            ):
                best_row[mid] = row
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]
    out: list[dict[str, Any]] = []
    for mid, sc in ordered:
        row = dict(best_row[mid])
        row["rrf_score"] = sc
        row["matter_id"] = mid
        out.append(row)
    return out


def holder_coverage(
    ranked: list[dict[str, Any]],
    holder_matters: set[str],
    *,
    k: int | None = None,
) -> dict[str, Any]:
    """HolderMatterCoverage@K — the C1 gate metric."""
    if k is not None:
        ranked = ranked[:k]
    routed = {str(r["matter_id"]) for r in ranked}
    hit = routed & holder_matters
    n_h = len(holder_matters)
    coverage = (len(hit) / n_h) if n_h else 0.0
    return {
        "k": len(ranked),
        "n_holders": n_h,
        "holders_found": len(hit),
        "holder_coverage": round(coverage, 4),
        "holder_hit": 1.0 if hit else 0.0,
        "holder_precision": round(len(hit) / len(routed), 4) if routed else 0.0,
        "found_ids": sorted(hit),
        "missing_ids": sorted(holder_matters - hit),
    }


def min_k_for_coverage(
    ranked: list[dict[str, Any]],
    holder_matters: set[str],
    *,
    target: float = 0.9,
    max_k: int = 200,
) -> int | None:
    """Smallest K with HolderCoverage@K >= target; None if unreachable."""
    if not holder_matters:
        return 0
    found: set[str] = set()
    for i, row in enumerate(ranked[:max_k], start=1):
        mid = str(row["matter_id"])
        if mid in holder_matters:
            found.add(mid)
        if len(found) / len(holder_matters) >= target:
            return i
    return None


def active_matter_resolver() -> str:
    mode = (os.environ.get("MATTER_RESOLVER") or "off").strip().lower()
    if mode not in {"off", "lexical", "vector", "hybrid"}:
        return "off"
    return mode


def vector_matters_from_candidates(
    candidates: list[Candidate],
    *,
    k: int,
) -> list[dict[str, Any]]:
    return rank_matters_from_vector(candidates, k=k)
