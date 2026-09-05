"""Tests for Canonical Document AST & Block Parser.

Verifies:
  - Decomposing legal text into structured DocumentBlock items
  - Heading, clause, table, signature, and footnote detection
  - Deterministic character offsets (start_offset, end_offset)
  - SHA-256 block text hashing
"""
from __future__ import annotations

import pytest

from app.documents.canonical import (
    DocumentBlock,
    compute_block_hash,
    parse_canonical_blocks,
)


SAMPLE_SPA_TEXT = """ARTICLE VIII INDEMNIFICATION

Section 8.1 Survival of Representations. The representations and warranties of the Seller shall survive for twenty-four (24) months.

Section 8.2 Tax Indemnity. The aggregate liability of the Seller for Tax Indemnity claims under Section 8.1 shall not exceed $75,000.

| Party | Notice Address | Email |
| Seller | 100 Wall Street | legal@seller.com |
| Buyer | 200 Park Avenue | legal@buyer.com |

[1] Subject to applicable statutory survival periods under Delaware law.

IN WITNESS WHEREOF, the parties hereto have caused this Agreement to be executed as of the Effective Date."""


class TestCanonicalParser:
    def test_parse_blocks_structure(self):
        blocks = parse_canonical_blocks(
            body=SAMPLE_SPA_TEXT,
            document_id="DOC-TEST-001",
            version_id="VER-001",
        )

        assert len(blocks) == 6

        # 1. Heading
        b_head = blocks[0]
        assert b_head.block_type == "heading"
        assert b_head.section_id == "VIII"
        assert b_head.section_title == "INDEMNIFICATION"
        assert b_head.sequence == 1

        # 2. Clause 8.1
        b_clause1 = blocks[1]
        assert b_clause1.block_type == "heading" or b_clause1.block_type == "clause"
        assert b_clause1.section_id == "8.1"
        assert "Survival of Representations" in b_clause1.text

        # 3. Clause 8.2 (Tax Indemnity)
        b_clause2 = blocks[2]
        assert b_clause2.section_id == "8.2"
        assert "$75,000" in b_clause2.text

        # 4. Table
        b_table = blocks[3]
        assert b_table.block_type == "table"
        assert "100 Wall Street" in b_table.text

        # 5. Footnote
        b_footnote = blocks[4]
        assert b_footnote.block_type == "footnote"
        assert "Delaware law" in b_footnote.text

        # 6. Signature
        b_sig = blocks[5]
        assert b_sig.block_type == "signature"
        assert "IN WITNESS WHEREOF" in b_sig.text

    def test_offset_accuracy(self):
        blocks = parse_canonical_blocks(
            body=SAMPLE_SPA_TEXT,
            document_id="DOC-TEST-001",
            version_id="VER-001",
        )

        for b in blocks:
            extracted_from_raw = SAMPLE_SPA_TEXT[b.start_offset : b.end_offset]
            assert extracted_from_raw == b.text

    def test_block_hash_deterministic(self):
        text1 = "Section 8.2 Tax Indemnity. The aggregate liability shall not exceed $75,000."
        text2 = "Section 8.2 Tax Indemnity. The aggregate liability shall not exceed $75,000."
        text3 = "Section 8.2 Tax Indemnity. The aggregate liability shall not exceed $50,000."

        assert compute_block_hash(text1) == compute_block_hash(text2)
        assert compute_block_hash(text1) != compute_block_hash(text3)
        assert len(compute_block_hash(text1)) == 64

    def test_empty_document(self):
        blocks = parse_canonical_blocks("", "DOC-EMPTY", "VER-EMPTY")
        assert blocks == []
