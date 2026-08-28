from __future__ import annotations

import math


def recall_at_k(relevant: set[str], ranked: list[str], k: int) -> float:
    if not relevant:
        return 1.0 if not ranked[:k] else 0.0
    hit = set(ranked[:k]) & relevant
    return len(hit) / len(relevant)


def mrr(relevant: set[str], ranked: list[str]) -> float:
    if not relevant:
        return 1.0 if not ranked else 0.0
    for i, item in enumerate(ranked, start=1):
        if item in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(relevant: set[str], ranked: list[str], k: int) -> float:
    dcg = 0.0
    for i, item in enumerate(ranked[:k], start=1):
        rel = 1.0 if item in relevant else 0.0
        dcg += rel / math.log2(i + 1)
    ideal_hits = min(k, len(relevant))
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    if idcg == 0:
        return 1.0 if dcg == 0 else 0.0
    return dcg / idcg
