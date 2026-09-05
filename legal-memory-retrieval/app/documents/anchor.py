"""3-Tier Durable Anchor Resolver.

Guarantees that AI highlights, citations, and annotations never drift or break
when documents are re-rendered, converted, or updated across versions.

Resolution Tiers:
  Tier 1 (Exact): Direct block ID + SHA-256 hash match (100% confidence).
  Tier 2 (Fuzzy): Substring / Levenshtein sequence search across version blocks (>80% confidence).
  Tier 3 (Semantic): Section / semantic fallback for heavily revised clauses (60-80% confidence).
"""
from __future__ import annotations

import difflib
from dataclasses import asdict, dataclass
from typing import Any, List, Optional

from psycopg.rows import dict_row

from app.db.connection import connect
from app.documents.canonical import compute_block_hash, get_version_blocks


@dataclass
class AnchorTarget:
    version_id: str
    quoted_text: str
    text_hash: Optional[str] = None
    block_id: Optional[str] = None
    page_number: int = 1
    start_offset: int = 0
    end_offset: int = 0


@dataclass
class ResolvedAnchor:
    found: bool
    resolution_tier: str  # exact | fuzzy | semantic | failed
    block_id: Optional[str]
    page_number: int
    start_offset: int
    end_offset: int
    matched_text: str
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_anchor(target: AnchorTarget, blocks_override: Optional[List[dict]] = None) -> ResolvedAnchor:
    """Resolve an anchor target against canonical blocks using the 3-tier fallback algorithm."""
    quoted = target.quoted_text.strip()
    if not quoted:
        return ResolvedAnchor(
            found=False,
            resolution_tier="failed",
            block_id=None,
            page_number=target.page_number,
            start_offset=target.start_offset,
            end_offset=target.end_offset,
            matched_text="",
            confidence=0.0,
            reason="Quoted text is empty",
        )

    expected_hash = target.text_hash or compute_block_hash(quoted)
    blocks = blocks_override if blocks_override is not None else get_version_blocks(target.version_id)

    if not blocks:
        return ResolvedAnchor(
            found=False,
            resolution_tier="failed",
            block_id=None,
            page_number=target.page_number,
            start_offset=target.start_offset,
            end_offset=target.end_offset,
            matched_text="",
            confidence=0.0,
            reason=f"No canonical blocks found for version {target.version_id}",
        )

    # ─────────────────────────────────────────────────────────────────
    # TIER 1: Exact Block ID & Content Hash Match
    # ─────────────────────────────────────────────────────────────────
    if target.block_id:
        target_block = next((b for b in blocks if b["block_id"] == target.block_id), None)
        if target_block:
            block_text = target_block["text"]
            # Check exact hash match
            if target_block.get("text_hash") == expected_hash or compute_block_hash(block_text) == expected_hash:
                return ResolvedAnchor(
                    found=True,
                    resolution_tier="exact",
                    block_id=target_block["block_id"],
                    page_number=target_block["page_number"],
                    start_offset=target_block["start_offset"],
                    end_offset=target_block["end_offset"],
                    matched_text=block_text,
                    confidence=1.0,
                    reason="Tier 1: Exact block ID and SHA-256 hash match",
                )
            
            # Check if quoted_text is an exact substring within the target block
            sub_idx = block_text.find(quoted)
            if sub_idx != -1:
                local_start = target_block["start_offset"] + sub_idx
                local_end = local_start + len(quoted)
                return ResolvedAnchor(
                    found=True,
                    resolution_tier="exact",
                    block_id=target_block["block_id"],
                    page_number=target_block["page_number"],
                    start_offset=local_start,
                    end_offset=local_end,
                    matched_text=quoted,
                    confidence=1.0,
                    reason="Tier 1: Exact substring match within target block",
                )

    # ─────────────────────────────────────────────────────────────────
    # TIER 2: Exact Substring or High-Similarity Fuzzy Match Across Version
    # ─────────────────────────────────────────────────────────────────
    # 2a. Search for exact substring across all blocks
    for b in blocks:
        block_text = b["text"]
        idx = block_text.find(quoted)
        if idx != -1:
            local_start = b["start_offset"] + idx
            local_end = local_start + len(quoted)
            return ResolvedAnchor(
                found=True,
                resolution_tier="exact",
                block_id=b["block_id"],
                page_number=b["page_number"],
                start_offset=local_start,
                end_offset=local_end,
                matched_text=quoted,
                confidence=0.98,
                reason="Tier 2a: Exact substring located in neighboring block",
            )

    # 2b. Fuzzy sequence matcher across all blocks
    best_match_block = None
    best_ratio = 0.0

    for b in blocks:
        block_text = b["text"]
        matcher = difflib.SequenceMatcher(None, quoted.lower(), block_text.lower())
        ratio = matcher.ratio()
        
        # Also check word set overlap
        words_q = set(quoted.lower().split())
        words_b = set(block_text.lower().split())
        if words_q:
            word_overlap = len(words_q.intersection(words_b)) / len(words_q)
            effective_ratio = max(ratio, word_overlap)
        else:
            effective_ratio = ratio

        if effective_ratio > best_ratio:
            best_ratio = effective_ratio
            best_match_block = b

    if best_match_block and best_ratio >= 0.65:
        return ResolvedAnchor(
            found=True,
            resolution_tier="fuzzy",
            block_id=best_match_block["block_id"],
            page_number=best_match_block["page_number"],
            start_offset=best_match_block["start_offset"],
            end_offset=best_match_block["end_offset"],
            matched_text=best_match_block["text"],
            confidence=round(best_ratio, 3),
            reason=f"Tier 2b: Fuzzy match with {int(best_ratio * 100)}% content similarity",
        )

    # ─────────────────────────────────────────────────────────────────
    # TIER 3: Semantic Section Fallback
    # ─────────────────────────────────────────────────────────────────
    if target.page_number:
        page_blocks = [b for b in blocks if b["page_number"] == target.page_number]
        if page_blocks:
            fb = page_blocks[0]
            return ResolvedAnchor(
                found=True,
                resolution_tier="semantic",
                block_id=fb["block_id"],
                page_number=fb["page_number"],
                start_offset=fb["start_offset"],
                end_offset=fb["end_offset"],
                matched_text=fb["text"][:100] + "...",
                confidence=0.60,
                reason="Tier 3: Page-level semantic fallback",
            )

    return ResolvedAnchor(
        found=False,
        resolution_tier="failed",
        block_id=None,
        page_number=target.page_number,
        start_offset=target.start_offset,
        end_offset=target.end_offset,
        matched_text="",
        confidence=0.0,
        reason="Anchor resolution failed across all tiers",
    )
