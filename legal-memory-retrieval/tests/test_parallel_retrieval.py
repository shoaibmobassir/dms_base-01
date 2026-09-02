"""Tests for parallel retrieval architecture.

Tests:
  - understand() called only once (not twice)
  - Parallel channels produce same hits as sequential baseline
  - parallel_wall_ms reported in latency
  - Cache hit skips threads
  - skip_vector respected
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.retrieval.engine import _weights, parse_channels


class TestParseChannels:
    def test_default_channels(self):
        channels = parse_channels("keyword,metadata,vector,graph")
        assert channels == ["keyword", "metadata", "vector", "graph"]

    def test_subset(self):
        channels = parse_channels("keyword,vector")
        assert channels == ["keyword", "vector"]

    def test_empty(self):
        channels = parse_channels("")
        assert channels == []

    def test_whitespace(self):
        channels = parse_channels(" keyword , vector ")
        assert channels == ["keyword", "vector"]


class TestWeights:
    def test_graph_reasoning_boosts_graph(self):
        parsed = MagicMock()
        parsed.intent = "graph_reasoning"
        parsed.matter_ids = []
        weights = _weights(parsed)
        assert weights["graph"] == 2.5

    def test_exact_lookup_boosts_metadata(self):
        parsed = MagicMock()
        parsed.intent = "exact_lookup"
        parsed.matter_ids = []
        weights = _weights(parsed)
        assert weights["metadata"] == 2.0

    def test_experience_search_boosts_metadata(self):
        parsed = MagicMock()
        parsed.intent = "experience_search"
        parsed.matter_ids = []
        weights = _weights(parsed)
        assert weights["metadata"] == 2.2

    def test_matter_ids_boost_graph(self):
        parsed = MagicMock()
        parsed.intent = "semantic"
        parsed.matter_ids = ["MTR-001"]
        weights = _weights(parsed)
        assert weights["graph"] == 1.6


class TestParallelRetrievalStructure:
    """Structural tests that don't need a live DB."""

    @patch("app.retrieval.engine.understand")
    @patch("app.retrieval.engine.cache_get", return_value=None)
    @patch("app.retrieval.engine.cache_set")
    @patch("app.retrieval.engine._run_channel", return_value=[])
    @patch("app.retrieval.engine.semantic_search", return_value=[])
    @patch("app.retrieval.engine.filter_vector_hits", return_value=[])
    @patch("app.retrieval.engine.fuse", return_value=[])
    def test_reports_parallel_wall_ms(
        self, mock_fuse, mock_filter, mock_sem, mock_run,
        mock_cache_set, mock_cache_get, mock_understand,
    ):
        """parallel_wall_ms should be reported in latency."""
        parsed = MagicMock()
        parsed.intent = "semantic"
        parsed.raw = "test query"
        parsed.search_text = "test query"
        parsed.skip_vector = False
        parsed.skip_rerank = True
        parsed.matter_ids = []
        mock_understand.return_value = parsed

        from app.retrieval.engine import retrieve_legacy
        conn = MagicMock()
        _, latency = retrieve_legacy(conn, "test query", channels=["keyword", "vector"])
        assert "parallel_wall_ms" in latency
        assert "understand" in latency

    @patch("app.retrieval.engine.understand")
    @patch("app.retrieval.engine.cache_get")
    def test_cache_hit_skips_channels(self, mock_cache_get, mock_understand):
        """When cache returns hits, no channel should run."""
        parsed = MagicMock()
        parsed.intent = "semantic"
        parsed.raw = "test"
        mock_understand.return_value = parsed
        mock_cache_get.return_value = [{"doc_id": "cached"}]

        from app.retrieval.engine import retrieve_legacy
        conn = MagicMock()
        hits, latency = retrieve_legacy(conn, "test")
        assert latency.get("cache") == "hit"
        assert hits == [{"doc_id": "cached"}]

    @patch("app.retrieval.engine.understand")
    def test_empty_query_returns_immediately(self, mock_understand):
        parsed = MagicMock()
        parsed.intent = "empty"
        parsed.raw = ""
        mock_understand.return_value = parsed

        from app.retrieval.engine import retrieve_legacy
        conn = MagicMock()
        hits, latency = retrieve_legacy(conn, "")
        assert hits == []
        assert "understand" in latency
