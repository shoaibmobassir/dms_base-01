from __future__ import annotations

from collections import defaultdict

import psycopg
from sentence_transformers import CrossEncoder

from config import settings
from embedder import get_embedder

_reranker: CrossEncoder | None = None


def _get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder(settings.rerank_model)
    return _reranker


def keyword_search(conn: psycopg.Connection, query: str, limit: int = 40) -> list[dict]:
    rows = conn.execute(
        """
        SELECT chunk_id, filename, page_number, text,
               ts_rank_cd(tsv, plainto_tsquery('english', %s)) AS score
        FROM docs_chunks
        WHERE tsv @@ plainto_tsquery('english', %s)
        ORDER BY score DESC
        LIMIT %s
        """,
        (query, query, limit),
    ).fetchall()
    for r in rows:
        r["channel"] = "keyword"
    return rows


def vector_search(conn: psycopg.Connection, query: str, limit: int = 40) -> list[dict]:
    vec = get_embedder().encode([query])[0]
    rows = conn.execute(
        """
        SELECT chunk_id, filename, page_number, text,
               1 - (embedding <=> %s::vector) AS score
        FROM docs_chunks
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (vec, vec, limit),
    ).fetchall()
    for r in rows:
        r["channel"] = "vector"
    return rows


def _fuse(*lists: list[dict], limit: int = 60) -> list[dict]:
    scores: dict[str, float] = defaultdict(float)
    payload: dict[str, dict] = {}
    k = 60
    for results in lists:
        for rank, row in enumerate(results, start=1):
            key = row["chunk_id"]
            scores[key] += 1.0 / (k + rank)
            payload[key] = row
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    out = []
    for key, score in ranked[:limit]:
        item = dict(payload[key])
        item["fused_score"] = score
        out.append(item)
    return out


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def _rerank_hits(query: str, hits: list[dict]) -> list[dict]:
    if len(hits) <= 1:
        return hits
    model = _get_reranker()
    pairs = [(query, h["text"][:1200]) for h in hits]
    ce_raw = [float(s) for s in model.predict(pairs, batch_size=32, show_progress_bar=False)]
    fused_raw = [float(h.get("fused_score") or 0.0) for h in hits]
    ce_n = _minmax(ce_raw)
    fu_n = _minmax(fused_raw)
    alpha = settings.rerank_ce_weight
    out = []
    for hit, ce, fu, raw in zip(hits, ce_n, fu_n, ce_raw):
        item = dict(hit)
        item["ce_score"] = raw
        item["rerank_score"] = alpha * ce + (1.0 - alpha) * fu
        out.append(item)
    out.sort(key=lambda r: float(r["rerank_score"]), reverse=True)
    return out


def retrieve(conn: psycopg.Connection, query: str, k: int | None = None) -> list[dict]:
    k = k or settings.retrieve_k
    limit = settings.retrieve_limit
    kw = keyword_search(conn, query, limit=limit)
    vec = vector_search(conn, query, limit=limit)
    fused = _fuse(kw, vec, limit=limit)
    reranked = _rerank_hits(query, fused)
    return reranked[:k]
