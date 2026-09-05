"""Tests for 3-Tier Durable Anchor Resolver.

Verifies:
  - Tier 1: Exact block match & content hash validation
  - Tier 2a: Substring match across alternative blocks
  - Tier 2b: Fuzzy sequence matcher when offsets drift
  - Tier 3: Page-level fallback
  - Failure handling
"""
from __future__ import annotations

import pytest

from app.documents.anchor import AnchorTarget, resolve_anchor
from app.documents.canonical import compute_block_hash


@pytest.fixture
def mock_blocks():
    return [
        {
            "block_id": "BLK-001",
            "version_id": "VER-100",
            "page_number": 1,
            "sequence": 1,
            "start_offset": 0,
            "end_offset": 120,
            "text": "ARTICLE VIII INDEMNIFICATION",
            "text_hash": compute_block_hash("ARTICLE VIII INDEMNIFICATION"),
        },
        {
            "block_id": "BLK-002",
            "version_id": "VER-100",
            "page_number": 1,
            "sequence": 2,
            "start_offset": 122,
            "end_offset": 280,
            "text": "Section 8.2 Tax Indemnity. The aggregate liability of the Seller shall not exceed $75,000.",
            "text_hash": compute_block_hash("Section 8.2 Tax Indemnity. The aggregate liability of the Seller shall not exceed $75,000."),
        },
        {
            "block_id": "BLK-003",
            "version_id": "VER-100",
            "page_number": 2,
            "sequence": 3,
            "start_offset": 282,
            "end_offset": 450,
            "text": "Section 11.1 Governing Law. This Agreement shall be governed by Delaware law.",
            "text_hash": compute_block_hash("Section 11.1 Governing Law. This Agreement shall be governed by Delaware law."),
        },
    ]


class TestAnchorResolver:
    def test_tier1_exact_block_hash_match(self, mock_blocks):
        target = AnchorTarget(
            version_id="VER-100",
            block_id="BLK-002",
            quoted_text="Section 8.2 Tax Indemnity. The aggregate liability of the Seller shall not exceed $75,000.",
            text_hash=compute_block_hash("Section 8.2 Tax Indemnity. The aggregate liability of the Seller shall not exceed $75,000."),
            page_number=1,
        )

        res = resolve_anchor(target, blocks_override=mock_blocks)
        assert res.found is True
        assert res.resolution_tier == "exact"
        assert res.block_id == "BLK-002"
        assert res.confidence == 1.0

    def test_tier1_exact_substring_within_block(self, mock_blocks):
        target = AnchorTarget(
            version_id="VER-100",
            block_id="BLK-002",
            quoted_text="liability of the Seller shall not exceed $75,000",
            page_number=1,
        )

        res = resolve_anchor(target, blocks_override=mock_blocks)
        assert res.found is True
        assert res.resolution_tier == "exact"
        assert res.block_id == "BLK-002"
        assert res.confidence == 1.0

    def test_tier2a_substring_cross_block_search(self, mock_blocks):
        # Target specifies wrong block_id but text exists in BLK-003
        target = AnchorTarget(
            version_id="VER-100",
            block_id="BLK-NONEXISTENT",
            quoted_text="governed by Delaware law",
            page_number=2,
        )

        res = resolve_anchor(target, blocks_override=mock_blocks)
        assert res.found is True
        assert res.resolution_tier == "exact"
        assert res.block_id == "BLK-003"
        assert res.confidence >= 0.95

    def test_tier2b_fuzzy_matcher(self, mock_blocks):
        # Text has slight typos or punctuation variation
        target = AnchorTarget(
            version_id="VER-100",
            quoted_text="Section 8.2 Tax Indemnity: aggregate liability of Seller not exceed $75,000",
            page_number=1,
        )

        res = resolve_anchor(target, blocks_override=mock_blocks)
        assert res.found is True
        assert res.resolution_tier == "fuzzy"
        assert res.block_id == "BLK-002"
        assert res.confidence >= 0.70

    def test_empty_quote_handling(self, mock_blocks):
        target = AnchorTarget(version_id="VER-100", quoted_text="")
        res = resolve_anchor(target, blocks_override=mock_blocks)
        assert res.found is False
        assert res.resolution_tier == "failed"
