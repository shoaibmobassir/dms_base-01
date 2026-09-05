"""Content hashing, simple embeddings, and durable anchor helpers."""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

from architecture_sim.models import ContentAnchor, DocumentBlock


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9$%]+", (text or "").lower())


def embed_text(text: str, dim: int = 64) -> list[float]:
    """Deterministic bag-of-tokens hash embedding (no ML deps)."""
    vec = [0.0] * dim
    toks = tokenize(text)
    if not toks:
        return vec
    for t in toks:
        h = int(hashlib.md5(t.encode()).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h // dim) % 2 == 0 else -1.0
        vec[idx] += sign
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    avgdl: float,
    df: dict[str, int],
    n_docs: int,
    k1: float = 1.2,
    b: float = 0.75,
) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    tf = Counter(doc_tokens)
    dl = len(doc_tokens)
    score = 0.0
    for qt in set(query_tokens):
        f = tf.get(qt, 0)
        if f == 0:
            continue
        n_q = df.get(qt, 0) or 1
        idf = math.log(1 + (n_docs - n_q + 0.5) / (n_q + 0.5))
        denom = f + k1 * (1 - b + b * dl / max(avgdl, 1.0))
        score += idf * (f * (k1 + 1)) / denom
    return score


def make_anchor(
    document_id: str,
    version_id: str,
    block: DocumentBlock,
    quote: str,
) -> ContentAnchor:
    """Primary anchor = block + offsets within block text."""
    start = block.text.find(quote)
    if start < 0:
        # fallback: use whole block
        start = 0
        quote = block.text[: min(120, len(block.text))]
        end = len(quote)
    else:
        end = start + len(quote)
    return ContentAnchor(
        document_id=document_id,
        version_id=version_id,
        block_id=block.block_id,
        start_offset=start,
        end_offset=end,
        quoted_text=quote,
        text_hash=sha256_text(quote),
        page=block.page_number,
        section_id=block.section_id,
    )


def resolve_anchor(
    anchor: ContentAnchor,
    blocks: list[DocumentBlock],
) -> tuple[ContentAnchor | None, float]:
    """
    Anchor fallback:
      1. block_id + offsets + hash
      2. quoted_text search
      3. nearest block by token overlap
    """
    by_id = {b.block_id: b for b in blocks}
    block = by_id.get(anchor.block_id)
    if block:
        slice_ = block.text[anchor.start_offset : anchor.end_offset]
        if sha256_text(slice_) == anchor.text_hash or slice_ == anchor.quoted_text:
            return anchor, 1.0
        if anchor.quoted_text and anchor.quoted_text in block.text:
            start = block.text.find(anchor.quoted_text)
            rebuilt = ContentAnchor(
                document_id=anchor.document_id,
                version_id=anchor.version_id,
                block_id=block.block_id,
                start_offset=start,
                end_offset=start + len(anchor.quoted_text),
                quoted_text=anchor.quoted_text,
                text_hash=sha256_text(anchor.quoted_text),
                page=block.page_number,
                section_id=block.section_id,
                bbox=anchor.bbox,
            )
            return rebuilt, 0.9

    # Secondary: search quote across blocks
    if anchor.quoted_text:
        for b in blocks:
            if anchor.quoted_text in b.text:
                start = b.text.find(anchor.quoted_text)
                rebuilt = ContentAnchor(
                    document_id=anchor.document_id,
                    version_id=anchor.version_id,
                    block_id=b.block_id,
                    start_offset=start,
                    end_offset=start + len(anchor.quoted_text),
                    quoted_text=anchor.quoted_text,
                    text_hash=sha256_text(anchor.quoted_text),
                    page=b.page_number,
                    section_id=b.section_id,
                )
                return rebuilt, 0.75

    # Tertiary: nearest token overlap
    q_toks = set(tokenize(anchor.quoted_text))
    best: DocumentBlock | None = None
    best_score = 0.0
    for b in blocks:
        bt = set(tokenize(b.text))
        if not q_toks or not bt:
            continue
        score = len(q_toks & bt) / len(q_toks)
        if score > best_score:
            best_score = score
            best = b
    if best and best_score >= 0.3:
        quote = best.text[: min(80, len(best.text))]
        rebuilt = ContentAnchor(
            document_id=anchor.document_id,
            version_id=anchor.version_id,
            block_id=best.block_id,
            start_offset=0,
            end_offset=len(quote),
            quoted_text=quote,
            text_hash=sha256_text(quote),
            page=best.page_number,
            section_id=best.section_id,
        )
        return rebuilt, 0.4 * best_score
    return None, 0.0
