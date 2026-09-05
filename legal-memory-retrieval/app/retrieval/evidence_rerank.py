"""P5.6-C7.5 — Cross-encoder evidence reranking (proposition ↔ passage).

Does not enable CE for document ranking. Ablation / optional path only.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence

from sentence_transformers import CrossEncoder

from app.config import settings
from app.retrieval.proposition import EvidenceSpan, Proposition

_model: CrossEncoder | None = None


def _cross_encoder() -> CrossEncoder:
    global _model
    if _model is None:
        _model = CrossEncoder(settings.rerank_model)
    return _model


def _minmax(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi - lo < 1e-9:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def evidence_passage(span: EvidenceSpan) -> str:
    """Passage text for CE — role + type + body."""
    role = span.role_family or ""
    dtype = span.document_type or ""
    title = span.title or ""
    text = (span.quoted_text or "")[:1200]
    return f"[{role}] [{dtype}] {title}\n{text}"


def proposition_query(prop: Proposition) -> str:
    return prop.retrieval_text()[:800]


def rerank_evidence(
    prop: Proposition,
    spans: list[EvidenceSpan],
    *,
    predict: Callable[[list[tuple[str, str]]], list[float]] | None = None,
    ce_weight: float = 0.85,
    limit: int | None = None,
) -> list[EvidenceSpan]:
    """Rerank evidence candidates: does this passage support the proposition?"""
    if len(spans) <= 1:
        return spans
    q = proposition_query(prop)
    pairs = [(q, evidence_passage(s)) for s in spans]
    if predict is not None:
        ce_raw = predict(pairs)
    else:
        scores = _cross_encoder().predict(pairs, batch_size=32, show_progress_bar=False)
        ce_raw = [float(s) for s in scores]
    base = [float(s.score or 0.0) for s in spans]
    ce_n = _minmax(ce_raw)
    base_n = _minmax(base)
    out: list[EvidenceSpan] = []
    for span, ce, bn in zip(spans, ce_n, base_n, strict=True):
        score = ce_weight * ce + (1.0 - ce_weight) * bn
        out.append(EvidenceSpan(**{
            **span.to_dict(),
            "score": score,
            "channel": f"{span.channel}+ce" if span.channel else "ce",
        }))
    out.sort(key=lambda s: s.score, reverse=True)
    if limit is not None:
        out = out[:limit]
    return out
