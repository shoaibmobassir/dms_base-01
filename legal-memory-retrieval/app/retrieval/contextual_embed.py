"""P5.6-C5.5 — Contextual document embeddings (chunk-level first).

C5.5.1–C5.5.5: contextualize each chunk with document identity, then
aggregate chunk similarity → document candidates inside theme scope.

Does not change production ``chunks.embedding``, fusion, CE, or GraphRAG.
Optional column: ``chunks.embedding_ctx`` (populated by scripts/embed_contextual.py).
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Literal

AggMethod = Literal["max", "top3_mean", "top5_mean"]

CTX_EMBED_VERSION = "ctx_chunk_v1"


def format_contextual_chunk(
    *,
    title: str | None,
    document_type: str | None,
    section_title: str | None = None,
    section_path: str | None = None,
    folder_path: str | None = None,
    chunk_text: str,
    max_chars: int = 1800,
) -> str:
    """Build contextualized embedding input for one chunk.

    Keeps document identity explicit so MiniLM sees more than raw body text.
    """
    parts: list[str] = []
    t = (title or "").strip()
    if t:
        parts.append(f"[DOCUMENT TITLE]\n{t}")
    dtype = (document_type or "").strip()
    if dtype:
        parts.append(f"[DOCUMENT TYPE]\n{dtype}")
    path = (section_path or folder_path or "").strip()
    if path:
        parts.append(f"[SECTION PATH]\n{path}")
    sec = (section_title or "").strip()
    if sec:
        parts.append(f"[SECTION]\n{sec}")
    body = (chunk_text or "").strip()
    if len(body) > max_chars:
        body = body[:max_chars].rsplit(" ", 1)[0] + "…"
    parts.append(f"[TEXT]\n{body}")
    return "\n\n".join(parts)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def aggregate_chunk_scores(
    chunk_rows: list[dict[str, Any]],
    *,
    method: AggMethod,
    score_key: str = "score",
    doc_key: str = "document_id",
) -> list[dict[str, Any]]:
    """Collapse chunk hits to document candidates.

    Each input row must include document_id and a similarity ``score``.
    Preserves best-chunk provenance on the winning document row.
    """
    by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in chunk_rows:
        did = row.get(doc_key)
        if not did:
            continue
        by_doc[str(did)].append(row)

    k = {"max": 1, "top3_mean": 3, "top5_mean": 5}[method]
    out: list[dict[str, Any]] = []
    for doc_id, rows in by_doc.items():
        ranked = sorted(rows, key=lambda r: float(r.get(score_key) or 0), reverse=True)
        top = ranked[:k]
        scores = [float(r.get(score_key) or 0) for r in top]
        doc_score = scores[0] if method == "max" else _mean(scores)
        best = ranked[0]
        out.append({
            "document_id": doc_id,
            "matter_id": best.get("matter_id"),
            "title": best.get("title"),
            "document_type": best.get("document_type"),
            "score": doc_score,
            "agg_method": method,
            "n_chunks_used": len(top),
            "best_chunk_id": best.get("chunk_id"),
            "best_chunk_score": float(best.get(score_key) or 0),
            "best_chunk_index": best.get("chunk_index"),
            "section_title": best.get("section_title"),
            "folder_path": best.get("folder_path") or best.get("doc_folder_path"),
            "channel": f"ctx_chunk_{method}",
        })
    out.sort(key=lambda r: r["score"], reverse=True)
    return out


@dataclass
class GoldRepDiagnostic:
    document_id: str
    in_theme: bool
    has_embedding: bool
    best_chunk_id: str | None = None
    best_chunk_score: float | None = None
    document_rank: int | None = None
    document_score: float | None = None
    top1_nongold_score: float | None = None
    margin_vs_top1: float | None = None
    document_type: str | None = None


def gold_vs_nongold_margins(
    gold: set[str],
    doc_ranked: list[dict[str, Any]],
    gold_chunk_best: dict[str, dict[str, Any]],
) -> list[GoldRepDiagnostic]:
    """Compare gold document scores to the top non-gold document."""
    ranks = {r["document_id"]: i + 1 for i, r in enumerate(doc_ranked)}
    scores = {r["document_id"]: float(r["score"]) for r in doc_ranked}
    top_nongold = next((r for r in doc_ranked if r["document_id"] not in gold), None)
    top1 = float(top_nongold["score"]) if top_nongold else None

    rows: list[GoldRepDiagnostic] = []
    for gid in sorted(gold):
        ch = gold_chunk_best.get(gid)
        gscore = scores.get(gid)
        margin = None
        if gscore is not None and top1 is not None:
            margin = round(gscore - top1, 4)
        rows.append(GoldRepDiagnostic(
            document_id=gid,
            in_theme=True,  # caller filters
            has_embedding=ch is not None or gid in scores,
            best_chunk_id=(ch or {}).get("chunk_id"),
            best_chunk_score=(None if ch is None else float(ch.get("score") or 0)),
            document_rank=ranks.get(gid),
            document_score=gscore,
            top1_nongold_score=top1,
            margin_vs_top1=margin,
            document_type=None,
        ))
    types = {r["document_id"]: r.get("document_type") for r in doc_ranked}
    for row in rows:
        if row.document_id in types and types[row.document_id]:
            row.document_type = types[row.document_id]
        elif gold_chunk_best.get(row.document_id):
            row.document_type = gold_chunk_best[row.document_id].get("document_type")
    return rows


def type_stratified_top(
    doc_ranked: list[dict[str, Any]],
    gold: set[str],
    *,
    k: int = 20,
) -> dict[str, Any]:
    """How often each document_type appears in top-k; EL/ICA gold recall slice."""
    top = doc_ranked[:k]
    freq: dict[str, int] = defaultdict(int)
    for r in top:
        freq[str(r.get("document_type") or "unknown")] += 1
    gold_in_top = [r for r in top if r["document_id"] in gold]
    return {
        f"top{k}_type_freq": dict(sorted(freq.items(), key=lambda x: -x[1])),
        f"gold_in_top{k}": len(gold_in_top),
        f"gold_types_in_top{k}": [
            {"document_id": r["document_id"], "document_type": r.get("document_type")}
            for r in gold_in_top
        ],
        "research_memo_in_topk": freq.get("Research Memo", 0),
        "engagement_letter_in_topk": freq.get("Engagement Letter", 0),
        "ica_in_topk": freq.get("Initial Case Assessment", 0),
    }


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    idx = (len(xs) - 1) * p
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return xs[lo]
    return xs[lo] * (hi - idx) + xs[hi] * (idx - lo)


__all__ = [
    "CTX_EMBED_VERSION",
    "AggMethod",
    "format_contextual_chunk",
    "aggregate_chunk_scores",
    "GoldRepDiagnostic",
    "gold_vs_nongold_margins",
    "type_stratified_top",
    "percentile",
]
