"""Tests for exact-title metadata ranking (P5.5 exact repair)."""
from __future__ import annotations

from unittest.mock import MagicMock

from app.retrieval.planner import plan


class TestExactPlanner:
    def test_exact_metadata_dominates_bm25(self):
        parsed = MagicMock()
        parsed.intent = "exact_lookup"
        parsed.matter_ids = []
        p = plan(parsed)
        assert p.channels == ["metadata", "bm25"]
        assert p.rerank is False
        assert p.weights["metadata"] > p.weights["bm25"] * 2


class TestExactTitleSearchExists:
    def test_store_has_exact_title_mode(self):
        from app.storage.postgres import PgMetadataStore
        import inspect

        sig = inspect.signature(PgMetadataStore.search)
        assert "exact_title_mode" in sig.parameters
        assert hasattr(PgMetadataStore, "_exact_title_search")
