from __future__ import annotations

from collections import defaultdict


def fuse(*lists: list[dict], limit: int = 100, weights: dict[str, float] | None = None) -> list[dict]:
    """Weighted reciprocal rank fusion across channels."""
    scores: dict[str, float] = defaultdict(float)
    payload: dict[str, dict] = {}
    k = 60
    for results in lists:
        for rank, row in enumerate(results, start=1):
            key = row.get("chunk_id") or row["document_id"]
            channel = row.get("channel") or "keyword"
            w = 1.0
            if weights:
                w = weights.get(channel, 1.0)
            scores[key] += w / (k + rank)
            payload[key] = row
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    out = []
    for key, score in ranked[:limit]:
        item = dict(payload[key])
        item["fused_score"] = score
        out.append(item)
    return out
