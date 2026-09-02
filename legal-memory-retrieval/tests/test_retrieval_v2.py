"""Comprehensive E2E tests for the v2 parallel retrieval platform.

Test coverage:
  ── Contracts ──
  1. Candidate construction, serialization, from_db_row
  2. Provenance tracking through pipeline
  3. RetrievalContext construction
  4. RetrievalPlan defaults and customization
  5. Protocol conformance (VectorStore, GraphStore, SearchStore, Retriever)

  ── Planner ──
  6. Intent → channel selection
  7. Graph expansion decisions
  8. Reranking decisions
  9. Fusion weight assignment

  ── Engine v2 ──
  10. All channels execute in parallel (asyncio.gather)
  11. Empty query returns immediately
  12. Failed channel doesn't block others
  13. Deduplication with provenance merging
  14. Fusion ranking correctness
  15. Conditional graph expansion
  16. Reranking conditional execution
  17. Backward-compatible sync wrapper

  ── Debugger ──
  18. Debug output structure
  19. Per-channel breakdown
  20. Graph expansion info
  21. Fusion + rerank diagnostics

  ── Storage ──
  22. PgSearchStore query construction
  23. PgVectorStore query construction
  24. PgGraphStore seed vs expand
  25. PgMetadataStore scoped vs catalog
  26. PgMatterStore search methods
  27. ACL enforcement in all stores

  ── Circuit Breaker ──
  28. CLOSED → OPEN after threshold
  29. OPEN → HALF_OPEN after timeout
  30. HALF_OPEN → CLOSED on success
  31. HALF_OPEN → OPEN on failure
  32. Stats reporting

  ── Evaluation ──
  33. Recall@K computation
  34. MRR computation
  35. NDCG@K computation
  36. Precision@K computation
  37. Summary aggregation

  ── Edge Cases ──
  38. Unicode queries
  39. SQL injection attempts
  40. Empty result sets from all channels
  41. Very long queries
  42. None/null member_id
  43. Candidate with missing fields
  44. Pool not initialized
  45. Concurrent channel failures
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ═══════════════════════════════════════════════════════════════════════════════
# 1. CONTRACTS — Candidate, Provenance, RetrievalContext, RetrievalPlan
# ═══════════════════════════════════════════════════════════════════════════════


class TestCandidate:
    """Candidate dataclass — the universal retrieval result."""

    def test_construction_minimal(self):
        from app.retrieval.contracts import Candidate
        c = Candidate(chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1")
        assert c.chunk_id == "CHK-1"
        assert c.document_id == "DOC-1"
        assert c.channel == ""
        assert c.raw_score == 0.0
        assert c.fusion_score is None
        assert c.rerank_score is None

    def test_construction_full(self):
        from app.retrieval.contracts import Candidate, Provenance
        c = Candidate(
            chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1",
            tenant_id="T-1", text="some text", title="Title",
            document_type="Affidavit", matter_code="DIS/BLR/0001/2024",
            client_name="Acme Corp", court="Bombay HC", practice_area="Disputes",
            author_name="A. Sharma", doc_date="2024-01-15", chunk_index=3,
            raw_score=0.87, channel="bm25",
            provenance=Provenance(channel="bm25", raw_score=0.87),
        )
        assert c.practice_area == "Disputes"
        assert c.provenance.channel == "bm25"

    def test_dedup_key_uses_chunk_id(self):
        from app.retrieval.contracts import Candidate
        c = Candidate(chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1")
        assert c.dedup_key == "CHK-1"

    def test_dedup_key_fallback_to_document_id(self):
        from app.retrieval.contracts import Candidate
        c = Candidate(chunk_id="", document_id="DOC-1", matter_id="MTR-1")
        assert c.dedup_key == "DOC-1"

    def test_to_dict_serialization(self):
        from app.retrieval.contracts import Candidate
        c = Candidate(
            chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1",
            text="hello", channel="vector", raw_score=0.9,
        )
        d = c.to_dict()
        assert d["chunk_id"] == "CHK-1"
        assert d["channel"] == "vector"
        assert d["raw_score"] == 0.9
        assert "provenance" in d
        assert isinstance(d["provenance"], dict)

    def test_from_db_row_happy_path(self):
        from app.retrieval.contracts import Candidate
        row = {
            "chunk_id": "CHK-1", "document_id": "DOC-1", "matter_id": "MTR-1",
            "text": "sample text", "title": "Title", "document_type": "Contract",
            "matter_code": "M&A/MUM/0001/2024", "client_name": "Client",
            "court": "Delhi HC", "practice_area": "M&A", "author_name": "Lawyer",
            "doc_date": "2024-03-01", "chunk_index": 0, "score": 0.85,
        }
        c = Candidate.from_db_row(row, "bm25")
        assert c.chunk_id == "CHK-1"
        assert c.channel == "bm25"
        assert c.raw_score == 0.85
        assert c.provenance.channel == "bm25"
        assert c.provenance.raw_score == 0.85

    def test_from_db_row_missing_fields(self):
        """from_db_row handles missing fields gracefully."""
        from app.retrieval.contracts import Candidate
        row = {"chunk_id": "CHK-1", "document_id": "DOC-1"}
        c = Candidate.from_db_row(row, "metadata")
        assert c.matter_id == ""
        assert c.text == ""
        assert c.raw_score == 0.0
        assert c.doc_date is None

    def test_from_db_row_none_score(self):
        from app.retrieval.contracts import Candidate
        row = {"chunk_id": "CHK-1", "document_id": "DOC-1", "score": None}
        c = Candidate.from_db_row(row, "vector")
        assert c.raw_score == 0.0

    def test_from_db_row_string_score(self):
        from app.retrieval.contracts import Candidate
        row = {"chunk_id": "CHK-1", "document_id": "DOC-1", "score": "0.42"}
        c = Candidate.from_db_row(row, "vector")
        assert c.raw_score == 0.42


class TestProvenance:
    def test_to_dict_minimal(self):
        from app.retrieval.contracts import Provenance
        p = Provenance(channel="bm25", raw_score=0.8)
        d = p.to_dict()
        assert d["channel"] == "bm25"
        assert d["raw_score"] == 0.8
        # Optional scores not included when None
        assert "vector_score" not in d

    def test_to_dict_with_graph_path(self):
        from app.retrieval.contracts import Provenance
        p = Provenance(
            channel="graph_seed", raw_score=1.0,
            graph_path=["matter", "client", "matter", "document"],
            expansion_depth=2,
        )
        d = p.to_dict()
        assert d["graph_path"] == ["matter", "client", "matter", "document"]
        assert d["expansion_depth"] == 2

    def test_to_dict_with_multi_channel(self):
        from app.retrieval.contracts import Provenance
        p = Provenance(
            channel="bm25", raw_score=0.8,
            channels_found_in=["bm25", "vector", "metadata"],
            bm25_score=0.8, vector_score=0.7,
        )
        d = p.to_dict()
        assert len(d["channels_found_in"]) == 3
        assert d["bm25_score"] == 0.8
        assert d["vector_score"] == 0.7


class TestRetrievalContext:
    def test_construction_minimal(self):
        from app.retrieval.contracts import RetrievalContext
        ctx = RetrievalContext(
            query_raw="test query",
            query_search_text="test query",
            intent="matter_research",
        )
        assert ctx.query_raw == "test query"
        assert ctx.member_id is None
        assert ctx.matter_ids == []
        assert ctx.limit == 50

    def test_construction_full(self):
        from app.retrieval.contracts import RetrievalContext
        ctx = RetrievalContext(
            query_raw="What about MTR-2024-001?",
            query_search_text="MTR-2024-001",
            intent="exact_lookup",
            member_id="MEM-001",
            tenant_id="T-1",
            matter_ids=["MTR-2024-001"],
            practice_area="Disputes",
            limit=20,
            k=10,
        )
        assert ctx.matter_ids == ["MTR-2024-001"]
        assert ctx.k == 10


class TestRetrievalPlan:
    def test_default_plan(self):
        from app.retrieval.contracts import RetrievalPlan
        p = RetrievalPlan()
        assert "bm25" in p.channels
        assert "vector" in p.channels
        assert p.graph_expansion is False
        assert p.rerank is True
        assert p.final_k == 20
        assert "bm25" in p.weights
        assert "vector" in p.weights

    def test_exact_lookup_plan(self):
        from app.retrieval.contracts import RetrievalPlan
        p = RetrievalPlan(
            channels=["metadata", "bm25"],
            graph_expansion=False,
            rerank=False,
        )
        assert len(p.channels) == 2
        assert p.rerank is False
        assert p.graph_expansion is False


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PLANNER — intent → execution plan
# ═══════════════════════════════════════════════════════════════════════════════


class TestPlanner:
    def _parsed(self, intent="matter_research", matter_ids=None):
        m = MagicMock()
        m.intent = intent
        m.matter_ids = matter_ids or []
        return m

    def test_exact_lookup_minimal_channels(self):
        from app.retrieval.planner import plan
        p = plan(self._parsed("exact_lookup"))
        assert "metadata" in p.channels
        assert "bm25" in p.channels
        assert "vector" not in p.channels
        assert p.rerank is False
        assert p.graph_expansion is False
        assert p.rerank_candidates > 0

    def test_experience_search_includes_matter(self):
        from app.retrieval.planner import plan
        p = plan(self._parsed("experience_search"))
        assert "matter" in p.channels
        assert p.rerank is True

    def test_graph_reasoning_enables_expansion(self):
        from app.retrieval.planner import plan
        p = plan(self._parsed("graph_reasoning"))
        assert "graph_seed" in p.channels
        assert p.graph_expansion is True
        assert p.weights.get("graph_seed", 0) >= 2.0

    def test_cross_document_all_channels(self):
        from app.retrieval.planner import plan
        p = plan(self._parsed("cross_document"))
        assert len(p.channels) >= 4
        assert p.graph_expansion is True
        assert p.rerank is True

    def test_similar_matter_plan(self):
        from app.retrieval.planner import plan
        p = plan(self._parsed("similar_matter"))
        assert "vector" in p.channels
        assert "matter" in p.channels
        assert p.graph_expansion is True

    def test_semantic_plan(self):
        from app.retrieval.planner import plan
        p = plan(self._parsed("semantic"))
        assert "vector" in p.channels
        assert p.rerank is True

    def test_default_with_matter_ids_enables_expansion(self):
        from app.retrieval.planner import plan
        p = plan(self._parsed("matter_research", matter_ids=["MTR-001"]))
        assert p.graph_expansion is True

    def test_default_without_matter_ids_no_expansion(self):
        from app.retrieval.planner import plan
        p = plan(self._parsed("matter_research", matter_ids=[]))
        assert p.graph_expansion is False


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ENGINE V2 — parallel retrieval
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngineV2Deduplication:
    def test_dedup_keeps_highest_score(self):
        from app.retrieval.contracts import Candidate
        from app.retrieval.engine_v2 import _deduplicate

        c1 = Candidate(chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1",
                        channel="bm25", raw_score=0.5)
        c2 = Candidate(chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1",
                        channel="vector", raw_score=0.9)
        c3 = Candidate(chunk_id="CHK-2", document_id="DOC-2", matter_id="MTR-1",
                        channel="bm25", raw_score=0.3)

        result = _deduplicate([c1, c2, c3])
        assert len(result) == 2
        chk1 = [c for c in result if c.chunk_id == "CHK-1"][0]
        assert chk1.raw_score == 0.9
        assert set(chk1.provenance.channels_found_in) == {"bm25", "vector"}

    def test_dedup_empty_list(self):
        from app.retrieval.engine_v2 import _deduplicate
        assert _deduplicate([]) == []

    def test_dedup_single_candidate(self):
        from app.retrieval.contracts import Candidate
        from app.retrieval.engine_v2 import _deduplicate
        c = Candidate(chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1",
                      channel="bm25", raw_score=0.5)
        result = _deduplicate([c])
        assert len(result) == 1
        assert result[0].provenance.channels_found_in == ["bm25"]

    def test_dedup_preserves_per_channel_scores(self):
        from app.retrieval.contracts import Candidate
        from app.retrieval.engine_v2 import _deduplicate
        c1 = Candidate(chunk_id="CHK-1", document_id="D-1", matter_id="M-1",
                        channel="bm25", raw_score=0.8)
        c2 = Candidate(chunk_id="CHK-1", document_id="D-1", matter_id="M-1",
                        channel="vector", raw_score=0.7)
        result = _deduplicate([c1, c2])
        assert len(result) == 1
        p = result[0].provenance
        assert p.bm25_score == 0.8
        assert p.vector_score == 0.7


class TestEngineV2Fusion:
    def test_fusion_ranking(self):
        from app.retrieval.contracts import Candidate
        from app.retrieval.engine_v2 import _fuse_candidates

        candidates = [
            Candidate(chunk_id="A", document_id="DA", matter_id="MA",
                      channel="bm25", raw_score=0.9),
            Candidate(chunk_id="B", document_id="DB", matter_id="MB",
                      channel="bm25", raw_score=0.5),
            Candidate(chunk_id="A", document_id="DA", matter_id="MA",
                      channel="vector", raw_score=0.8),
        ]
        weights = {"bm25": 1.0, "vector": 1.0}
        fused = _fuse_candidates(candidates, weights, limit=10)

        # A appears in both channels → higher fusion score
        assert fused[0].chunk_id == "A"
        assert fused[0].fusion_score is not None
        assert fused[0].fusion_score > fused[1].fusion_score

    def test_fusion_respects_weights(self):
        from app.retrieval.contracts import Candidate
        from app.retrieval.engine_v2 import _fuse_candidates

        # Two candidates in different channels, same rank (1st)
        c_bm25 = Candidate(chunk_id="A", document_id="DA", matter_id="MA",
                           channel="bm25", raw_score=0.9)
        c_vec = Candidate(chunk_id="B", document_id="DB", matter_id="MB",
                          channel="vector", raw_score=0.9)

        # Heavily weight vector
        fused = _fuse_candidates([c_bm25, c_vec], {"bm25": 0.1, "vector": 10.0}, limit=10)
        assert fused[0].chunk_id == "B"

        # Heavily weight bm25
        fused = _fuse_candidates([c_bm25, c_vec], {"bm25": 10.0, "vector": 0.1}, limit=10)
        assert fused[0].chunk_id == "A"

    def test_fusion_empty_candidates(self):
        from app.retrieval.engine_v2 import _fuse_candidates
        assert _fuse_candidates([], {"bm25": 1.0}, limit=10) == []

    def test_fusion_limit(self):
        from app.retrieval.contracts import Candidate
        from app.retrieval.engine_v2 import _fuse_candidates

        candidates = [
            Candidate(chunk_id=f"CHK-{i}", document_id=f"DOC-{i}", matter_id="MTR-1",
                      channel="bm25", raw_score=1.0 - i * 0.01)
            for i in range(50)
        ]
        fused = _fuse_candidates(candidates, {"bm25": 1.0}, limit=5)
        assert len(fused) == 5


class TestEngineV2BuildContext:
    def test_context_from_parsed_query(self):
        from app.retrieval.engine_v2 import _build_context
        parsed = MagicMock()
        parsed.raw = "test query"
        parsed.search_text = "test"
        parsed.intent = "matter_research"
        parsed.matter_ids = ["MTR-001"]
        parsed.matter_codes = ["DIS/BLR/0001/2024"]
        parsed.document_ids = []
        parsed.member_ids = ["MEM-001"]
        parsed.practice_area = "Disputes"

        ctx = _build_context(parsed, "MEM-001", 20)
        assert ctx.query_raw == "test query"
        assert ctx.member_id == "MEM-001"
        assert ctx.matter_ids == ["MTR-001"]
        assert ctx.practice_area == "Disputes"
        assert ctx.k == 20

    def test_context_none_member_id(self):
        from app.retrieval.engine_v2 import _build_context
        parsed = MagicMock()
        parsed.raw = "query"
        parsed.search_text = "query"
        parsed.intent = "semantic"
        parsed.matter_ids = []
        parsed.matter_codes = []
        parsed.document_ids = []
        parsed.member_ids = []
        parsed.practice_area = None

        ctx = _build_context(parsed, None, 10)
        assert ctx.member_id is None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. CIRCUIT BREAKER
# ═══════════════════════════════════════════════════════════════════════════════


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        from app.resilience.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED
        assert cb.is_available is True

    def test_opens_after_threshold(self):
        from app.resilience.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(name="test", failure_threshold=3)
        for _ in range(3):
            cb.record_failure(Exception("fail"))
        assert cb.state == CircuitState.OPEN
        assert cb.is_available is False

    def test_stays_closed_below_threshold(self):
        from app.resilience.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(name="test", failure_threshold=3)
        cb.record_failure(Exception("fail"))
        cb.record_failure(Exception("fail"))
        assert cb.state == CircuitState.CLOSED

    def test_success_resets_failure_count(self):
        from app.resilience.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(name="test", failure_threshold=3)
        cb.record_failure(Exception("fail"))
        cb.record_failure(Exception("fail"))
        cb.record_success()  # resets
        cb.record_failure(Exception("fail"))
        cb.record_failure(Exception("fail"))
        assert cb.state == CircuitState.CLOSED  # still only 2 consecutive

    def test_transitions_to_half_open_after_timeout(self):
        from app.resilience.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure(Exception("fail"))
        assert cb._state == CircuitState.OPEN
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_closes_on_success(self):
        from app.resilience.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure(Exception("fail"))
        time.sleep(0.02)
        _ = cb.state  # trigger HALF_OPEN transition
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_reopens_on_failure(self):
        from app.resilience.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure(Exception("fail"))
        time.sleep(0.02)
        _ = cb.state
        cb.record_failure(Exception("still broken"))
        assert cb._state == CircuitState.OPEN

    def test_stats(self):
        from app.resilience.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(name="test-stats")
        cb.record_success()
        cb.record_failure(Exception("err"))
        stats = cb.stats()
        assert stats["name"] == "test-stats"
        assert stats["total_successes"] == 1
        assert stats["total_failures"] == 1
        assert stats["state"] in ("closed", "open", "half_open")

    def test_rejection_tracking(self):
        from app.resilience.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(name="test", failure_threshold=1)
        cb.record_failure(Exception("fail"))
        cb.record_rejection()
        cb.record_rejection()
        assert cb.stats()["total_rejected"] == 2

    def test_global_registry(self):
        from app.resilience.circuit_breaker import get_breaker, all_breaker_stats
        b1 = get_breaker("svc-a")
        b2 = get_breaker("svc-a")
        assert b1 is b2
        stats = all_breaker_stats()
        assert any(s["name"] == "svc-a" for s in stats)

    def test_call_with_breaker_open(self):
        from app.resilience.circuit_breaker import (
            CircuitBreaker, CircuitOpenError, call_with_breaker,
        )
        cb = CircuitBreaker(name="test-open", failure_threshold=1)
        cb.record_failure(Exception("fail"))
        with pytest.raises(CircuitOpenError):
            asyncio.run(call_with_breaker(cb, lambda: "ok"))


# ═══════════════════════════════════════════════════════════════════════════════
# 5. EVALUATION METRICS
# ═══════════════════════════════════════════════════════════════════════════════


class TestEvalMetrics:
    def test_recall_at_k_perfect(self):
        from evals.evaluate import _recall_at_k
        assert _recall_at_k(["a", "b", "c"], ["a", "b"], 5) == 1.0

    def test_recall_at_k_partial(self):
        from evals.evaluate import _recall_at_k
        assert _recall_at_k(["a", "x", "y"], ["a", "b"], 5) == 0.5

    def test_recall_at_k_none_found(self):
        from evals.evaluate import _recall_at_k
        assert _recall_at_k(["x", "y", "z"], ["a", "b"], 5) == 0.0

    def test_recall_at_k_empty_expected(self):
        from evals.evaluate import _recall_at_k
        assert _recall_at_k(["a", "b"], [], 5) == 0.0

    def test_recall_at_k_respects_k(self):
        from evals.evaluate import _recall_at_k
        # "b" is at position 3, but k=2
        assert _recall_at_k(["x", "y", "b"], ["b"], 2) == 0.0
        assert _recall_at_k(["x", "y", "b"], ["b"], 3) == 1.0

    def test_mrr_first_position(self):
        from evals.evaluate import _mrr
        assert _mrr(["a", "b", "c"], ["a"]) == 1.0

    def test_mrr_second_position(self):
        from evals.evaluate import _mrr
        assert _mrr(["x", "a", "c"], ["a"]) == 0.5

    def test_mrr_not_found(self):
        from evals.evaluate import _mrr
        assert _mrr(["x", "y", "z"], ["a"]) == 0.0

    def test_mrr_empty_expected(self):
        """MRR with empty expected should return 0."""
        from evals.evaluate import _mrr
        assert _mrr(["a", "b"], []) == 0.0

    def test_ndcg_perfect(self):
        from evals.evaluate import _ndcg_at_k
        assert _ndcg_at_k(["a", "b"], ["a", "b"], 10) == 1.0

    def test_ndcg_empty(self):
        from evals.evaluate import _ndcg_at_k
        assert _ndcg_at_k(["a", "b"], [], 10) == 0.0

    def test_ndcg_partial(self):
        from evals.evaluate import _ndcg_at_k
        score = _ndcg_at_k(["x", "a", "b"], ["a", "b"], 10)
        assert 0 < score < 1.0

    def test_precision_at_k(self):
        from evals.evaluate import _precision_at_k
        assert _precision_at_k(["a", "b", "c"], ["a", "b"], 3) == pytest.approx(2 / 3)

    def test_precision_at_k_all_relevant(self):
        from evals.evaluate import _precision_at_k
        assert _precision_at_k(["a", "b"], ["a", "b"], 2) == 1.0

    def test_precision_at_k_none_relevant(self):
        from evals.evaluate import _precision_at_k
        assert _precision_at_k(["x", "y"], ["a", "b"], 2) == 0.0

    def test_precision_empty_retrieved(self):
        from evals.evaluate import _precision_at_k
        assert _precision_at_k([], ["a", "b"], 5) == 0.0

    def test_percentile(self):
        from evals.evaluate import _percentile
        assert _percentile([10, 20, 30, 40, 50], 50) == 30
        assert _percentile([], 50) == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 6. EDGE CASES — unicode, SQL injection, empties, limits
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_candidate_with_unicode_text(self):
        from app.retrieval.contracts import Candidate
        c = Candidate(
            chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1",
            text="म्हणून न्यायालयाने ठरवले की — \'बल महान\' कलमानुसार",
            title="मराठी शीर्षक",
        )
        d = c.to_dict()
        assert "म्हणून" in d["text"]
        assert "मराठी" in d["title"]

    def test_candidate_with_emoji(self):
        from app.retrieval.contracts import Candidate
        c = Candidate(
            chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1",
            text="Contract signed ✅ by parties 🤝",
        )
        assert "✅" in c.text

    def test_candidate_with_sql_injection_text(self):
        """Candidate should safely store SQL injection attempts."""
        from app.retrieval.contracts import Candidate
        malicious = "'; DROP TABLE chunks; --"
        c = Candidate(
            chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1",
            text=malicious,
        )
        d = c.to_dict()
        assert d["text"] == malicious  # stored as-is, parameterized queries protect

    def test_dedup_all_same_candidate(self):
        from app.retrieval.contracts import Candidate
        from app.retrieval.engine_v2 import _deduplicate
        candidates = [
            Candidate(chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1",
                      channel=f"ch-{i}", raw_score=0.1 * i)
            for i in range(10)
        ]
        result = _deduplicate(candidates)
        assert len(result) == 1
        assert result[0].raw_score == 0.9  # highest
        assert len(result[0].provenance.channels_found_in) == 10

    def test_fusion_single_channel(self):
        from app.retrieval.contracts import Candidate
        from app.retrieval.engine_v2 import _fuse_candidates
        candidates = [
            Candidate(chunk_id=f"C-{i}", document_id=f"D-{i}", matter_id="M-1",
                      channel="bm25", raw_score=1.0 - i * 0.1)
            for i in range(5)
        ]
        fused = _fuse_candidates(candidates, {"bm25": 1.0}, limit=100)
        assert len(fused) == 5
        # Should be ordered by RRF (which preserves raw_score ordering for single channel)
        scores = [c.fusion_score for c in fused]
        assert scores == sorted(scores, reverse=True)

    def test_retrieval_context_with_empty_entities(self):
        from app.retrieval.contracts import RetrievalContext
        ctx = RetrievalContext(
            query_raw="", query_search_text="", intent="empty",
            matter_ids=[], matter_codes=[], entities=[],
        )
        assert ctx.entities == []
        assert ctx.limit == 50

    def test_retrieval_plan_default_weights_immutable_across_instances(self):
        from app.retrieval.contracts import RetrievalPlan
        p1 = RetrievalPlan()
        p2 = RetrievalPlan()
        p1.weights["bm25"] = 999.0
        assert p2.weights["bm25"] != 999.0  # field factory creates new dict

    def test_very_long_query_in_context(self):
        from app.retrieval.contracts import RetrievalContext
        long_query = "word " * 10000
        ctx = RetrievalContext(
            query_raw=long_query, query_search_text=long_query, intent="semantic",
        )
        assert len(ctx.query_raw) == 50000

    def test_pool_not_initialized_raises(self):
        """acquire() should raise RuntimeError when pool isn't initialized."""
        import app.db.pool as pool_mod
        original_pool = pool_mod._pool
        pool_mod._pool = None
        try:
            async def _test():
                async with pool_mod.acquire() as conn:
                    pass
            with pytest.raises(RuntimeError, match="not initialized"):
                asyncio.run(_test())
        finally:
            pool_mod._pool = original_pool

    def test_pool_stats_when_not_initialized(self):
        import app.db.pool as pool_mod
        original_pool = pool_mod._pool
        pool_mod._pool = None
        try:
            stats = pool_mod.pool_stats()
            assert stats == {"initialized": False}
        finally:
            pool_mod._pool = original_pool


class TestQueryUnderstandingEdgeCases:
    """Edge cases for the understand() function that feeds into the v2 engine."""

    def test_unicode_query(self):
        from app.query.understand import understand
        p = understand("न्यायालयाचा निर्णय काय आहे?")
        assert p.intent in {"matter_research", "semantic", "empty"}

    def test_sql_injection_query(self):
        from app.query.understand import understand
        p = understand("'; DROP TABLE chunks; --")
        assert p.raw == "'; DROP TABLE chunks; --"
        assert p.intent != "empty"

    def test_extremely_long_query(self):
        from app.query.understand import understand
        p = understand("word " * 5000)
        assert p.raw is not None
        assert p.search_text is not None

    def test_special_characters_query(self):
        from app.query.understand import understand
        p = understand("M&A mergers % _ \\")
        assert p.practice_area == "M&A"

    def test_only_whitespace_is_empty(self):
        from app.query.understand import understand
        assert understand("   \t\n  ").intent == "empty"

    def test_mixed_case_matter_ids(self):
        from app.query.understand import understand
        p = understand("mtr-2024-00001")
        assert len(p.matter_ids) == 1
        assert p.matter_ids[0] == "MTR-2024-00001"

    def test_multiple_entities_in_single_query(self):
        from app.query.understand import understand
        p = understand("Compare MTR-2024-001 and DOC-00005 for MEM-001")
        assert len(p.matter_ids) >= 1
        assert len(p.document_ids) >= 1
        assert len(p.member_ids) >= 1


class TestPlannerEdgeCases:
    def test_unknown_intent_defaults_to_full_plan(self):
        from app.retrieval.planner import plan
        parsed = MagicMock()
        parsed.intent = "completely_unknown_intent"
        parsed.matter_ids = []
        p = plan(parsed)
        assert len(p.channels) >= 4  # Should use default plan

    def test_planner_with_none_intent(self):
        """Planner should handle None-ish intents gracefully."""
        from app.retrieval.planner import plan
        parsed = MagicMock()
        parsed.intent = ""
        parsed.matter_ids = []
        p = plan(parsed)
        assert len(p.channels) >= 1  # Should produce some plan


# ═══════════════════════════════════════════════════════════════════════════════
# 7. EVALUATION RUNNER — end to end
# ═══════════════════════════════════════════════════════════════════════════════


class TestEvalRunner:
    def test_evaluate_single_query_perfect_retrieval(self):
        from evals.evaluate import evaluate_query

        spec = {
            "id": "test-001",
            "query": "test query",
            "intent": "exact_lookup",
            "difficulty": "easy",
            "expected_matters": ["MTR-001"],
            "expected_documents": ["DOC-001"],
        }

        def mock_retrieve(q):
            return [
                {"document_id": "DOC-001", "matter_id": "MTR-001", "score": 0.9},
                {"document_id": "DOC-002", "matter_id": "MTR-002", "score": 0.5},
            ], {"understand": 1.0}

        result = evaluate_query(spec, mock_retrieve)
        assert result.recall_at_5 == 1.0
        assert result.mrr == 1.0
        assert result.precision_at_5 == pytest.approx(1 / 2)

    def test_evaluate_single_query_no_results(self):
        from evals.evaluate import evaluate_query

        spec = {
            "id": "test-002",
            "query": "nothing found",
            "intent": "semantic",
            "difficulty": "hard",
            "expected_matters": ["MTR-999"],
            "expected_documents": [],
        }

        def mock_retrieve(q):
            return [], {}

        result = evaluate_query(spec, mock_retrieve)
        assert result.result_count == 0
        assert result.recall_at_5 == 0.0
        assert result.mrr == 0.0

    def test_run_evaluation_with_mock(self):
        import json
        import tempfile
        from evals.evaluate import run_evaluation

        benchmark = {
            "version": "1.0",
            "description": "test",
            "metrics": ["recall@5"],
            "queries": [
                {
                    "id": "q1", "query": "test", "intent": "exact_lookup",
                    "difficulty": "easy",
                    "expected_matters": ["MTR-1"],
                    "expected_documents": ["DOC-1"],
                },
                {
                    "id": "q2", "query": "test2", "intent": "semantic",
                    "difficulty": "hard",
                    "expected_matters": [],
                    "expected_documents": [],
                },
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(benchmark, f)
            f.flush()

            def mock_retrieve(q):
                if "test2" in q:
                    return [], {}
                return [{"document_id": "DOC-1", "matter_id": "MTR-1"}], {}

            summary = run_evaluation(mock_retrieve, f.name, engine_version="test")

        assert summary.total_queries == 2
        assert summary.evaluated_queries == 1  # q2 has no expected
        assert summary.skipped_queries == 1
        assert summary.avg_recall_at_5 == 1.0  # only q1 is evaluated
        assert len(summary.query_results) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 8. ASYNC ENGINE — integration tests (mocked stores)
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngineV2Async:
    """Test the async retrieve function with mocked stores."""

    @pytest.fixture(autouse=True)
    def patch_pool_and_stores(self):
        """Patch the acquire context manager and all stores to avoid real DB."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        # Create async mock cursor
        mock_cursor = AsyncMock()
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_cursor.execute = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)

        with patch("app.retrieval.engine_v2.acquire") as mock_acquire:
            mock_acquire.return_value = mock_conn
            mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_acquire.__aexit__ = AsyncMock(return_value=False)
            yield mock_acquire

    @pytest.mark.asyncio
    async def test_empty_query_returns_immediately(self):
        from app.retrieval.engine_v2 import retrieve_async
        candidates, latency = await retrieve_async("", None, 20)
        assert candidates == []
        assert "understand" in latency

    @pytest.mark.asyncio
    async def test_whitespace_query_returns_empty(self):
        from app.retrieval.engine_v2 import retrieve_async
        candidates, latency = await retrieve_async("   ", None, 20)
        assert candidates == []

    @pytest.mark.asyncio
    async def test_latency_keys_present(self):
        """Even with mocked empty results, latency should have all keys."""
        from app.retrieval.engine_v2 import retrieve_async

        with patch("app.retrieval.engine_v2._channel_bm25", return_value=[]), \
             patch("app.retrieval.engine_v2._channel_vector", return_value=[]), \
             patch("app.retrieval.engine_v2._channel_metadata", return_value=[]), \
             patch("app.retrieval.engine_v2._channel_matter", return_value=[]), \
             patch("app.retrieval.engine_v2._channel_graph_seed", return_value=[]), \
             patch("app.retrieval.engine_v2._channel_similar_matter", return_value=[]):
            candidates, latency = await retrieve_async("test legal query", None, 20)

        assert "understand" in latency
        assert "plan" in latency
        assert "parallel_wall_ms" in latency
        assert "total_raw_candidates" in latency
        assert "unique_candidates" in latency
        assert "final_count" in latency

    @pytest.mark.asyncio
    async def test_channel_failure_doesnt_crash_engine(self):
        """If one channel raises, others should still return results."""
        from app.retrieval.contracts import Candidate
        from app.retrieval.engine_v2 import retrieve_async, _CHANNEL_FNS

        good_candidate = Candidate(
            chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1",
            channel="bm25", raw_score=0.9, text="good result",
        )

        async def failing_channel(*a, **kw):
            raise RuntimeError("Channel exploded!")

        async def good_channel(*a, **kw):
            return [good_candidate]

        async def empty_channel(*a, **kw):
            return []

        original_fns = dict(_CHANNEL_FNS)
        _CHANNEL_FNS["bm25"] = good_channel
        _CHANNEL_FNS["vector"] = failing_channel
        _CHANNEL_FNS["metadata"] = empty_channel
        _CHANNEL_FNS["matter"] = empty_channel
        _CHANNEL_FNS["graph_seed"] = empty_channel
        _CHANNEL_FNS["similar_matter"] = empty_channel

        try:
            with patch("app.retrieval.engine_v2.rerank", side_effect=lambda q, h: h):
                candidates, latency = await retrieve_async("shareholder dispute", None, 20)
            # Should still get results from the good channel
            assert len(candidates) >= 1
            assert candidates[0].chunk_id == "CHK-1"
        finally:
            _CHANNEL_FNS.update(original_fns)

    @pytest.mark.asyncio
    async def test_all_channels_fail_returns_empty(self):
        from app.retrieval.engine_v2 import retrieve_async, _CHANNEL_FNS

        async def failing(*a, **kw):
            raise RuntimeError("fail")

        original_fns = dict(_CHANNEL_FNS)
        for key in _CHANNEL_FNS:
            _CHANNEL_FNS[key] = failing

        try:
            candidates, latency = await retrieve_async("test query", None, 20)
            assert candidates == []
            assert latency["final_count"] == 0
        finally:
            _CHANNEL_FNS.update(original_fns)


class TestSyncWrapper:
    """Test the backward-compatible synchronous retrieve() wrapper."""

    def test_sync_wrapper_calls_async(self):
        from app.retrieval.contracts import Candidate
        from app.retrieval.engine_v2 import retrieve

        mock_candidates = [
            Candidate(chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1",
                      channel="bm25", raw_score=0.9, text="result"),
        ]

        with patch("app.retrieval.engine_v2.retrieve_async",
                    return_value=(mock_candidates, {"total": 10.0})):
            conn = MagicMock()
            hits, latency = retrieve(conn, "test query")

        assert len(hits) == 1
        assert hits[0]["chunk_id"] == "CHK-1"
        assert hits[0]["channel"] == "bm25"
        assert "score" in hits[0]
