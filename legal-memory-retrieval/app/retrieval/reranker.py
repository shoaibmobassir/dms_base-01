from __future__ import annotations

from collections.abc import Callable, Sequence

from sentence_transformers import CrossEncoder

from app.config import settings

_model: CrossEncoder | None = None


def _cross_encoder() -> CrossEncoder:
    global _model
    if _model is None:
        _model = CrossEncoder(settings.rerank_model)
    return _model


def _passage(row: dict) -> str:
    text = (row.get("text") or "")[:1200]
    title = row.get("title") or ""
    doc_type = row.get("document_type") or ""
    doc_id = row.get("document_id") or ""
    matter_id = row.get("matter_id") or ""
    return f"{title} [{doc_type}] {doc_id} {matter_id}\n{text}"


def _minmax(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi - lo < 1e-9:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def _predict(pairs: list[tuple[str, str]]) -> list[float]:
    scores = _cross_encoder().predict(pairs, batch_size=32, show_progress_bar=False)
    return [float(s) for s in scores]


def rerank(
    query: str,
    hits: list[dict],
    predict: Callable[[list[tuple[str, str]]], list[float]] | None = None,
    ce_weight: float | None = None,
) -> list[dict]:
    """Reorder fused candidates with a local cross-encoder, blended with RRF."""
    if len(hits) <= 1:
        return hits
    scorer = predict or _predict
    pairs = [(query, _passage(h)) for h in hits]
    ce_raw = scorer(pairs)
    fused_raw = [float(h.get("fused_score") or 0.0) for h in hits]
    ce_n = _minmax(ce_raw)
    fu_n = _minmax(fused_raw)
    alpha = settings.rerank_ce_weight if ce_weight is None else ce_weight
    out: list[dict] = []
    for hit, ce, fu, raw in zip(hits, ce_n, fu_n, ce_raw, strict=True):
        item = dict(hit)
        item["ce_score"] = raw
        item["rerank_score"] = alpha * ce + (1.0 - alpha) * fu
        out.append(item)
    out.sort(key=lambda row: float(row["rerank_score"]), reverse=True)
    return out
