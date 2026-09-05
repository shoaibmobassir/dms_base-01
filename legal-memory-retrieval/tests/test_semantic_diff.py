"""Tests for Multi-Level Version Diff Engine.

Verifies:
  - Lexical word-level redline tokenization (insert/delete/equal)
  - Semantic legal diff extracting additions, deletions, modifications
  - Financial shift tracking ($50,000 -> $75,000 = +$25,000)
  - Risk level categorization
"""
from __future__ import annotations

import pytest

from app.documents.diff import (
    compute_semantic_diff,
    compute_word_redline,
)


class TestMultiLevelDiff:
    def test_word_level_redline(self):
        text_v7 = "The aggregate liability of the Seller shall not exceed $50,000."
        text_v8 = "The aggregate liability of the Seller shall not exceed $75,000."

        tokens = compute_word_redline(text_v7, text_v8)
        assert any(t.token_type == "delete" and "$50,000." in t.text for t in tokens)
        assert any(t.token_type == "insert" and "$75,000." in t.text for t in tokens)
        assert any(t.token_type == "equal" and "The aggregate liability" in t.text for t in tokens)

    def test_semantic_legal_diff_financial_cap_increase(self):
        blocks_v7 = [
            {
                "block_id": "BLK-V7-01",
                "sequence": 1,
                "section_id": "8.2",
                "section_title": "Tax Indemnity",
                "page_number": 47,
                "text": "Section 8.2 Tax Indemnity. The aggregate liability of the Seller shall not exceed $50,000.",
            },
            {
                "block_id": "BLK-V7-02",
                "sequence": 2,
                "section_id": "11.1",
                "section_title": "Governing Law",
                "page_number": 52,
                "text": "Section 11.1 Governing Law. Governed by the laws of New York.",
            },
        ]

        blocks_v8 = [
            {
                "block_id": "BLK-V8-01",
                "sequence": 1,
                "section_id": "8.2",
                "section_title": "Tax Indemnity",
                "page_number": 47,
                "text": "Section 8.2 Tax Indemnity. The aggregate liability of the Seller shall not exceed $75,000.",
            },
            {
                "block_id": "BLK-V8-02",
                "sequence": 2,
                "section_id": "11.1",
                "section_title": "Governing Law",
                "page_number": 52,
                "text": "Section 11.1 Governing Law. Governed by the laws of Delaware.",
            },
            {
                "block_id": "BLK-V8-03",
                "sequence": 3,
                "section_id": "12.0",
                "section_title": "Termination",
                "page_number": 54,
                "text": "Section 12.0 Termination. Either party may terminate upon 30 days prior written notice.",
            },
        ]

        changes = compute_semantic_diff(blocks_v7, blocks_v8)
        assert len(changes) == 3

        # 1. Indemnity cap increase
        indemnity_chg = next(c for c in changes if c.section_id == "8.2")
        assert indemnity_chg.change_type == "MODIFIED"
        assert indemnity_chg.category == "indemnity"
        assert indemnity_chg.risk_level == "HIGH"
        assert indemnity_chg.risk_direction == "risk_increased"
        assert "Increased from $50,000 to $75,000" in (indemnity_chg.financial_impact or "")

        # 2. Governing law change
        gov_chg = next(c for c in changes if c.section_id == "11.1")
        assert gov_chg.change_type == "MODIFIED"
        assert gov_chg.category == "governing_law"

        # 3. New termination clause
        term_chg = next(c for c in changes if c.section_id == "12.0")
        assert term_chg.change_type == "ADDED"
        assert term_chg.category == "termination"
