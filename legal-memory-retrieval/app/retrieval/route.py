from __future__ import annotations

import re

MATTER_ID_RE = re.compile(r"\bMTR-\d{4}-\d+\b", re.I)
MATTER_CODE_RE = re.compile(r"\b[A-Z]{3}/[A-Z]{3}/\d{4}/\d{4}\b")
EXACT_HINT_RE = re.compile(
    r"\b(matter code|what happened in|document id|doc-\d+)\b",
    re.I,
)

CHANNEL_WEIGHTS = {
    "metadata": 1.5,
    "keyword": 1.2,
    "vector": 0.75,
    "graph": 0.9,
}

# Cosine on L2-normalized MiniLM. Below this, drop the ANN hit.
VECTOR_MIN_SCORE = 0.42
# If FTS+metadata are empty, only keep vector if the top hit is at least this confident.
VECTOR_ABSTAIN_SCORE = 0.50


def is_exact_lookup(query: str) -> bool:
    return bool(MATTER_ID_RE.search(query) or MATTER_CODE_RE.search(query) or EXACT_HINT_RE.search(query))


def filter_vector_hits(hits: list[dict], lexical_empty: bool) -> list[dict]:
    kept = [h for h in hits if float(h.get("score") or 0) >= VECTOR_MIN_SCORE]
    if lexical_empty:
        kept = [h for h in kept if float(h.get("score") or 0) >= VECTOR_ABSTAIN_SCORE]
    return kept
