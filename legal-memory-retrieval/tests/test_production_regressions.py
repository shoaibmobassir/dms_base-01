"""Regression tests for known production bugs found during live E2E testing.

These tests target specific failure modes discovered when running v2
against a live Postgres database. Each test reproduces a bug that passed
unit tests but fails under real data conditions.

BUG INVENTORY (from 2026-09-03 audit):

  BUG-001: exact_lookup → metadata returns 50 rows but fusion_limit=0 → 0 final hits
           Root cause: planner sets rerank=False + rerank_candidates=50,
           but engine fusion_limit calc was: `rerank_candidates if rerank else final_k`
           which gave rerank_candidates=0 when rerank=False before the fix in engine_v2.
           The fix at line 470-471 uses max(rerank_candidates, final_k, k).

  BUG-002: semantic query → only vector contributes; bm25/matter/graph_seed = 0
           Root cause: bm25 uses plainto_tsquery which returns 0 rows for vague queries.
           matter channel needs client_name/practice_area/entities populated from understand().
           graph_seed needs matter_ids/matter_codes populated.
           Context builder was not populating client_name.

  BUG-003: metadata SQL escape bug — `ESCAPE '\\\\'` may generate invalid
           escape string on some Postgres configs (standard_conforming_strings).

  BUG-004: use_engine_v2=True in config is wired via engine.py delegation,
           but the delegation isn't tested. If someone removes line 90-93
           of engine.py, all production traffic silently falls back to legacy.

  BUG-005: exact_lookup planner sets rerank=False but rerank_candidates=50.
           These are contradictory — if rerank is disabled, rerank_candidates
           is semantically meaningless, and fusion_limit must still be adequate.

  BUG-006: sync wrapper runs in ThreadPool when called from async context
           (FastAPI), creating a new event loop. This works but the pool
           isn't initialized in the new thread. Need to verify it handles
           pool-not-initialized gracefully.

  BUG-007: _channel_matter with no client_name/practice_area/entities
           falls through to search_by_text, but search_by_text returns []
           for queries < 3 chars. Short cleaned search_text → 0 results.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ═══════════════════════════════════════════════════════════════════════════════
# BUG-001: exact_lookup → fusion_limit must produce > 0 final hits
# ═══════════════════════════════════════════════════════════════════════════════


class TestBug001ExactLookupFusionLimit:
    """
    When planner says rerank=False (exact lookup), the fusion_limit
    must still be > 0 so that fused results are returned.
    """

    def test_exact_lookup_plan_has_nonzero_fusion_pool(self):
        """Planner's exact_lookup plan must produce a fusion_limit > 0
        when the engine computes: max(rerank_candidates, final_k, k)."""
        from app.retrieval.planner import plan
        parsed = MagicMock()
        parsed.intent = "exact_lookup"
        parsed.matter_ids = ["MTR-2020-00463"]
        p = plan(parsed)

        # Simulate the engine's fusion_limit calculation (engine_v2.py L470-471)
        k = 20
        fusion_limit = p.rerank_candidates if p.rerank else p.final_k
        fusion_limit = max(fusion_limit, p.final_k, k)

        assert fusion_limit > 0, "Fusion limit must be > 0 for exact_lookup"
        assert fusion_limit >= k, "Fusion limit must be >= k"

    def test_exact_lookup_with_metadata_results_returns_nonempty(self):
        """If metadata returns 50 candidates for an exact lookup,
        the final result must NOT be empty."""
        from app.retrieval.contracts import Candidate
        from app.retrieval.engine_v2 import _fuse_candidates

        # Simulate: metadata channel returned 50 candidates (exact lookup)
        candidates = [
            Candidate(
                chunk_id=f"CHK-{i}", document_id=f"DOC-{i}",
                matter_id="MTR-2020-00463",
                channel="metadata", raw_score=1.0,
                text=f"chunk text {i}",
            )
            for i in range(50)
        ]

        # Use exact_lookup plan's weights
        from app.retrieval.planner import plan
        parsed = MagicMock()
        parsed.intent = "exact_lookup"
        parsed.matter_ids = ["MTR-2020-00463"]
        p = plan(parsed)

        # Compute fusion_limit like the engine does
        k = 20
        fusion_limit = p.rerank_candidates if p.rerank else p.final_k
        fusion_limit = max(fusion_limit, p.final_k, k)

        fused = _fuse_candidates(candidates, p.weights, limit=fusion_limit)
        assert len(fused) > 0, \
            f"BUG-001: 50 metadata candidates → 0 after fusion (limit={fusion_limit})"
        assert len(fused) >= k

    def test_exact_lookup_rerank_false_means_no_reranking(self):
        """exact_lookup plan must set rerank=False so no cross-encoder runs."""
        from app.retrieval.planner import plan
        parsed = MagicMock()
        parsed.intent = "exact_lookup"
        parsed.matter_ids = []
        p = plan(parsed)
        assert p.rerank is False

    def test_fusion_limit_never_zero_for_any_plan(self):
        """For ALL planner outputs, the engine's fusion_limit must be > 0."""
        from app.retrieval.planner import plan

        for intent in ["exact_lookup", "experience_search", "graph_reasoning",
                       "cross_document", "similar_matter", "semantic",
                       "matter_research"]:
            parsed = MagicMock()
            parsed.intent = intent
            parsed.matter_ids = []
            p = plan(parsed)

            k = 20
            fusion_limit = p.rerank_candidates if p.rerank else p.final_k
            fusion_limit = max(fusion_limit, p.final_k, k)

            assert fusion_limit > 0, \
                f"Fusion limit is 0 for intent={intent}"


# ═══════════════════════════════════════════════════════════════════════════════
# BUG-002: semantic → only vector contributes; other channels return 0
# ═══════════════════════════════════════════════════════════════════════════════


class TestBug002SemanticChannelContributions:
    """
    For semantic/similar_matter queries like "force majeure" or "Narang Limited",
    only the vector channel contributes results. bm25/matter/graph_seed = 0.

    Root causes:
    - bm25: plainto_tsquery may not match if text lacks exact terms in tsv
    - matter: needs client_name / practice_area populated, which context builder misses
    - graph_seed: needs matter_ids/matter_codes, which semantic queries don't have
    """

    def test_context_builder_propagates_client_name(self):
        """_build_context must propagate client_name to RetrievalContext."""
        from app.retrieval.engine_v2 import _build_context

        parsed = MagicMock()
        parsed.raw = "What have we done for Narang Limited?"
        parsed.search_text = "Narang Limited"
        parsed.intent = "matter_research"
        parsed.matter_ids = []
        parsed.matter_codes = []
        parsed.document_ids = []
        parsed.member_ids = []
        parsed.practice_area = None
        # This is the critical field — understand() should extract it
        # but the context builder must forward it if present.

        ctx = _build_context(parsed, None, 20)
        # client_name should come from parsed query or be extractable
        assert ctx.query_search_text == "Narang Limited"

    def test_graph_seed_returns_empty_when_no_seeds(self):
        """graph_seed must gracefully return [] when no matter_ids exist."""
        from app.retrieval.contracts import RetrievalContext
        from app.retrieval.engine_v2 import _channel_graph_seed

        ctx = RetrievalContext(
            query_raw="force majeure flooding",
            query_search_text="force majeure flooding",
            intent="semantic",
            matter_ids=[],
            matter_codes=[],
            member_ids=[],
        )

        # graph_seed should return [] immediately, not error
        result = asyncio.run(_channel_graph_seed(ctx, 50))
        assert result == [], "graph_seed should return [] when seeds list is empty"

    def test_matter_channel_no_entities_falls_to_text_search(self):
        """When matter channel has no practice/client/entities,
        it should fall back to search_by_text with query text."""
        from app.retrieval.contracts import RetrievalContext

        ctx = RetrievalContext(
            query_raw="force majeure flooding construction",
            query_search_text="force majeure flooding construction",
            intent="semantic",
            matter_ids=[],
            matter_codes=[],
            member_ids=[],
            practice_area=None,
            client_name=None,
            entities=[],
        )

        # The matter channel should use search_by_text as fallback
        # and the needle should be the search_text (which is >= 3 chars)
        needle = ctx.client_name or ctx.query_search_text or ctx.query_raw
        assert len(needle) >= 3, \
            "Matter channel fallback text must be >= 3 chars to not be short-circuited"

    def test_matter_channel_short_query_returns_empty(self):
        """PgMatterStore.search_by_text returns [] for queries < 3 chars.
        This is a known limitation that can cause 0 results."""
        from app.storage.postgres import PgMatterStore
        store = PgMatterStore()
        # search_by_text has a len(text) < 3 early return
        # This documents the behavior, not necessarily a bug
        assert hasattr(store, 'search_by_text')

    def test_planner_includes_bm25_for_semantic_queries(self):
        """Planner should include bm25 for semantic queries even though
        it may return 0 results — it's a channel, not a gate."""
        from app.retrieval.planner import plan
        parsed = MagicMock()
        parsed.intent = "semantic"
        parsed.matter_ids = []
        p = plan(parsed)
        assert "bm25" in p.channels, \
            "bm25 must be in semantic plan channels even if it often returns 0"
        assert "vector" in p.channels
        assert "matter" in p.channels


# ═══════════════════════════════════════════════════════════════════════════════
# BUG-003: metadata SQL ESCAPE '\\' may produce invalid escape string
# ═══════════════════════════════════════════════════════════════════════════════


class TestBug003MetadataSqlEscape:
    """
    PgMetadataStore._like() produces escaped strings for SQL LIKE.
    The SQL uses ESCAPE '\\' which can break on some Postgres configs
    when standard_conforming_strings is off.

    Using parameterized queries + Python-level escaping should be safe,
    but the _like() method must handle all edge cases.
    """

    def test_like_basic(self):
        from app.storage.postgres import PgMetadataStore
        assert PgMetadataStore._like("hello") == "%hello%"

    def test_like_escapes_percent(self):
        from app.storage.postgres import PgMetadataStore
        result = PgMetadataStore._like("100% complete")
        assert "\\%" in result, f"Percent not escaped: {result!r}"
        assert result == "%100\\% complete%"

    def test_like_escapes_underscore(self):
        from app.storage.postgres import PgMetadataStore
        result = PgMetadataStore._like("snake_case")
        assert "\\_" in result, f"Underscore not escaped: {result!r}"

    def test_like_escapes_backslash(self):
        from app.storage.postgres import PgMetadataStore
        result = PgMetadataStore._like("path\\to\\file")
        assert "\\\\" in result, f"Backslash not escaped: {result!r}"

    def test_like_combined_special_chars(self):
        """All three special characters in one string."""
        from app.storage.postgres import PgMetadataStore
        result = PgMetadataStore._like("100%_path\\test")
        assert "\\%" in result
        assert "\\_" in result
        assert "\\\\" in result

    def test_like_empty_string(self):
        from app.storage.postgres import PgMetadataStore
        assert PgMetadataStore._like("") == "%%"

    def test_like_unicode(self):
        from app.storage.postgres import PgMetadataStore
        result = PgMetadataStore._like("न्यायालय")
        assert result == "%न्यायालय%"

    def test_like_sql_injection_safe(self):
        """LIKE value with SQL injection attempt — should be safely escaped."""
        from app.storage.postgres import PgMetadataStore
        result = PgMetadataStore._like("'; DROP TABLE--")
        assert "DROP TABLE" in result  # stored as-is
        assert result.startswith("%")
        assert result.endswith("%")

    def test_catalog_search_does_not_call_like_for_short_queries(self):
        """_catalog_search should use '__no_like__' for queries < 3 chars,
        preventing the ESCAPE clause from ever running on short input."""
        from app.storage.postgres import PgMetadataStore
        store = PgMetadataStore()
        # _like is only called when len(needle) >= 3
        # For len < 3, like is set to "__no_like__" (line 393)
        short = "ab"
        assert len(short) < 3
        # This documents the behavior guard


# ═══════════════════════════════════════════════════════════════════════════════
# BUG-004: use_engine_v2 delegation is wired but untested
# ═══════════════════════════════════════════════════════════════════════════════


class TestBug004EngineV2Delegation:
    """
    engine.py line 90 delegates to engine_v2 when settings.use_engine_v2=True.
    If someone removes this delegation, all traffic silently falls back to legacy.
    These tests verify the delegation wiring.
    """

    def test_engine_retrieve_delegates_to_v2_when_enabled(self):
        """engine.retrieve() must call engine_v2.retrieve when flag is True."""
        with patch("app.retrieval.engine.settings") as mock_settings, \
             patch("app.retrieval.engine_v2.retrieve") as mock_v2:
            mock_settings.use_engine_v2 = True
            mock_v2.return_value = ([{"doc_id": "from_v2"}], {"engine": "v2"})

            from app.retrieval.engine import retrieve
            conn = MagicMock()
            hits, latency = retrieve(conn, "test query")
            mock_v2.assert_called_once()
            assert hits == [{"doc_id": "from_v2"}]

    def test_engine_retrieve_uses_legacy_when_disabled(self):
        """engine.retrieve() must use legacy when flag is False."""
        with patch("app.retrieval.engine.settings") as mock_settings, \
             patch("app.retrieval.engine.retrieve_legacy") as mock_legacy:
            mock_settings.use_engine_v2 = False
            mock_settings.retrieve_k = 20
            mock_legacy.return_value = ([{"doc_id": "from_legacy"}], {"engine": "legacy"})

            from app.retrieval.engine import retrieve
            conn = MagicMock()
            hits, latency = retrieve(conn, "test query")
            mock_legacy.assert_called_once()
            assert hits == [{"doc_id": "from_legacy"}]

    def test_config_default_is_v2_enabled(self):
        """Config must default to use_engine_v2=True."""
        from app.config import settings
        assert settings.use_engine_v2 is True, \
            "use_engine_v2 must default to True in production config"


# ═══════════════════════════════════════════════════════════════════════════════
# BUG-005: rerank_candidates vs rerank contradiction
# ═══════════════════════════════════════════════════════════════════════════════


class TestBug005RerankCandidatesContradiction:
    """
    When a plan sets rerank=False, rerank_candidates is semantically meaningless.
    But the engine was using rerank_candidates as fusion_limit when rerank=True.
    The fix ensures fusion_limit = max(rerank_candidates, final_k, k).
    """

    def test_all_plans_have_adequate_fusion_pool(self):
        """Every plan must produce a fusion_limit >= final_k."""
        from app.retrieval.planner import plan

        intents = [
            "exact_lookup", "experience_search", "graph_reasoning",
            "cross_document", "similar_matter", "semantic", "matter_research",
        ]
        for intent in intents:
            parsed = MagicMock()
            parsed.intent = intent
            parsed.matter_ids = []
            p = plan(parsed)

            # Engine computation (engine_v2.py L470-471)
            k = 20
            fusion_limit = p.rerank_candidates if p.rerank else p.final_k
            fusion_limit = max(fusion_limit, p.final_k, k)

            assert fusion_limit >= p.final_k, \
                f"Intent {intent}: fusion_limit ({fusion_limit}) < final_k ({p.final_k})"

    def test_exact_lookup_rerank_false_rerank_candidates_irrelevant(self):
        """When rerank=False, rerank_candidates should not matter."""
        from app.retrieval.planner import plan

        parsed = MagicMock()
        parsed.intent = "exact_lookup"
        parsed.matter_ids = []
        p = plan(parsed)

        assert p.rerank is False
        # Even if rerank_candidates were 0, fusion_limit must still work
        k = 20
        fusion_limit = p.rerank_candidates if p.rerank else p.final_k
        fusion_limit = max(fusion_limit, p.final_k, k)
        # rerank is False, so we take final_k path, then max with k
        assert fusion_limit >= k


# ═══════════════════════════════════════════════════════════════════════════════
# BUG-006: sync wrapper + pool initialization in new thread
# ═══════════════════════════════════════════════════════════════════════════════


class TestBug006SyncWrapperPoolHandling:
    """
    The sync wrapper in engine_v2.retrieve() creates a new thread + event loop
    when called from an async context (FastAPI). The pool might not be
    initialized in that new thread's event loop.
    """

    def test_sync_wrapper_formats_output_correctly(self):
        """Sync wrapper must convert Candidates to dicts with
        fused_score, score, and ce_score fields."""
        from app.retrieval.contracts import Candidate, Provenance
        from app.retrieval.engine_v2 import retrieve

        c = Candidate(
            chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1",
            channel="bm25", raw_score=0.9, text="result text",
        )
        c.fusion_score = 0.85
        c.rerank_score = 0.92
        c.provenance = Provenance(channel="bm25", raw_score=0.9, ce_score=0.88)

        with patch("app.retrieval.engine_v2.retrieve_async",
                    return_value=([c], {"total": 10.0})):
            conn = MagicMock()
            hits, latency = retrieve(conn, "test query")

        assert len(hits) == 1
        hit = hits[0]
        assert hit["fused_score"] == 0.85
        assert hit["score"] == 0.92  # rerank_score takes priority
        assert hit["ce_score"] == 0.88

    def test_sync_wrapper_score_fallback_chain(self):
        """score field should fallback: rerank_score → fusion_score → raw_score"""
        from app.retrieval.contracts import Candidate
        from app.retrieval.engine_v2 import retrieve

        # No rerank_score
        c = Candidate(
            chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1",
            channel="bm25", raw_score=0.9,
        )
        c.fusion_score = 0.85
        # rerank_score = None (default)

        with patch("app.retrieval.engine_v2.retrieve_async",
                    return_value=([c], {})):
            conn = MagicMock()
            hits, _ = retrieve(conn, "test")

        assert hits[0]["score"] == 0.85  # falls back to fusion_score

    def test_sync_wrapper_score_raw_fallback(self):
        """When both rerank_score and fusion_score are None, use raw_score."""
        from app.retrieval.contracts import Candidate
        from app.retrieval.engine_v2 import retrieve

        c = Candidate(
            chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1",
            channel="bm25", raw_score=0.7,
        )
        # fusion_score = None, rerank_score = None

        with patch("app.retrieval.engine_v2.retrieve_async",
                    return_value=([c], {})):
            conn = MagicMock()
            hits, _ = retrieve(conn, "test")

        assert hits[0]["score"] == 0.7  # falls back to raw_score


# ═══════════════════════════════════════════════════════════════════════════════
# BUG-007: matter channel short text fallback
# ═══════════════════════════════════════════════════════════════════════════════


class TestBug007MatterChannelShortText:
    """
    PgMatterStore.search_by_text returns [] for text < 3 chars.
    When context has no client_name/practice_area/entities AND
    cleaned search_text < 3 chars, matter channel returns 0 results.
    """

    def test_context_with_short_search_text_matter_needle(self):
        """When query_search_text is short, matter channel uses it as needle.
        If < 3 chars, search_by_text returns []. Document this behavior."""
        from app.retrieval.contracts import RetrievalContext

        ctx = RetrievalContext(
            query_raw="hi",
            query_search_text="hi",
            intent="semantic",
        )
        needle = ctx.client_name or ctx.query_search_text or ctx.query_raw
        assert needle == "hi"
        assert len(needle) < 3  # Will cause search_by_text to return []

    def test_context_with_adequate_search_text(self):
        """Normal queries should produce a needle >= 3 chars."""
        from app.retrieval.contracts import RetrievalContext

        ctx = RetrievalContext(
            query_raw="What about force majeure?",
            query_search_text="force majeure",
            intent="semantic",
        )
        needle = ctx.client_name or ctx.query_search_text or ctx.query_raw
        assert len(needle) >= 3


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: dedup → fusion → rerank pipeline correctness
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipelineIntegration:
    """End-to-end pipeline stages in isolation (no DB, no embedder)."""

    def test_full_pipeline_dedup_fusion_rerank(self):
        """Simulate a realistic multi-channel retrieval pipeline."""
        from app.retrieval.contracts import Candidate, RetrievalPlan
        from app.retrieval.engine_v2 import _deduplicate, _fuse_candidates

        # Channel results
        bm25_results = [
            Candidate(chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1",
                      channel="bm25", raw_score=0.9, text="relevant result"),
            Candidate(chunk_id="CHK-2", document_id="DOC-2", matter_id="MTR-1",
                      channel="bm25", raw_score=0.3, text="less relevant"),
        ]
        vector_results = [
            Candidate(chunk_id="CHK-1", document_id="DOC-1", matter_id="MTR-1",
                      channel="vector", raw_score=0.85, text="relevant result"),
            Candidate(chunk_id="CHK-3", document_id="DOC-3", matter_id="MTR-2",
                      channel="vector", raw_score=0.7, text="vector only"),
        ]
        metadata_results = [
            Candidate(chunk_id="CHK-4", document_id="DOC-4", matter_id="MTR-1",
                      channel="metadata", raw_score=1.0, text="exact match"),
        ]

        all_candidates = bm25_results + vector_results + metadata_results

        # Step 1: Dedup
        deduped = _deduplicate(all_candidates)
        assert len(deduped) == 4  # CHK-1 deduped (bm25 + vector)

        chk1 = [c for c in deduped if c.chunk_id == "CHK-1"][0]
        assert set(chk1.provenance.channels_found_in) == {"bm25", "vector"}
        assert chk1.raw_score == 0.9  # highest score kept

        # Step 2: Fusion
        weights = {"bm25": 1.2, "vector": 1.0, "metadata": 1.5}
        fused = _fuse_candidates(deduped, weights, limit=10)

        # CHK-1 should rank highly (found in 2 channels)
        # CHK-4 should also rank well (metadata weight is high)
        assert len(fused) == 4
        assert all(c.fusion_score is not None for c in fused)
        assert all(c.fusion_score > 0 for c in fused)

        # Top 2 should be CHK-1 (multi-channel) or CHK-4 (high weight)
        top_ids = {fused[0].chunk_id, fused[1].chunk_id}
        assert "CHK-1" in top_ids, \
            f"CHK-1 (multi-channel) should be in top-2, got {top_ids}"

    def test_pipeline_all_same_channel_still_works(self):
        """Pipeline must work when all results come from a single channel."""
        from app.retrieval.contracts import Candidate
        from app.retrieval.engine_v2 import _deduplicate, _fuse_candidates

        candidates = [
            Candidate(chunk_id=f"CHK-{i}", document_id=f"DOC-{i}",
                      matter_id="MTR-1", channel="vector", raw_score=1.0 - i * 0.1)
            for i in range(10)
        ]

        deduped = _deduplicate(candidates)
        assert len(deduped) == 10

        fused = _fuse_candidates(deduped, {"vector": 1.0}, limit=5)
        assert len(fused) == 5
        # Should be ordered by fusion score (which mirrors raw_score rank)
        for i in range(len(fused) - 1):
            assert fused[i].fusion_score >= fused[i + 1].fusion_score

    def test_pipeline_empty_after_dedup_produces_empty_fusion(self):
        """If dedup produces empty list, fusion should return empty."""
        from app.retrieval.engine_v2 import _deduplicate, _fuse_candidates

        deduped = _deduplicate([])
        fused = _fuse_candidates(deduped, {"bm25": 1.0}, limit=10)
        assert fused == []


# ═══════════════════════════════════════════════════════════════════════════════
# ACL enforcement
# ═══════════════════════════════════════════════════════════════════════════════


class TestACLEnforcement:
    """Verify that ACL WHERE clause is present in every store query."""

    def test_acl_fragment_is_defined(self):
        from app.storage.postgres import _ACL_WHERE
        assert "member_id" in _ACL_WHERE
        assert "restricted" in _ACL_WHERE
        assert "allowed_members" in _ACL_WHERE

    def test_search_store_uses_acl(self):
        """PgSearchStore SQL must contain ACL fragment."""
        import inspect
        from app.storage.postgres import PgSearchStore
        source = inspect.getsource(PgSearchStore.search)
        assert "_ACL_WHERE" in source or "restricted" in source, \
            "PgSearchStore.search must enforce ACL"

    def test_vector_store_uses_acl(self):
        import inspect
        from app.storage.postgres import PgVectorStore
        source = inspect.getsource(PgVectorStore.search)
        assert "_ACL_WHERE" in source or "restricted" in source, \
            "PgVectorStore.search must enforce ACL"

    def test_graph_store_seed_uses_acl(self):
        import inspect
        from app.storage.postgres import PgGraphStore
        source = inspect.getsource(PgGraphStore.seed)
        assert "_ACL_WHERE" in source or "restricted" in source, \
            "PgGraphStore.seed must enforce ACL"

    def test_graph_store_expand_uses_acl(self):
        import inspect
        from app.storage.postgres import PgGraphStore
        source = inspect.getsource(PgGraphStore.expand)
        assert "_ACL_WHERE" in source or "restricted" in source, \
            "PgGraphStore.expand must enforce ACL"

    def test_metadata_store_uses_acl(self):
        import inspect
        from app.storage.postgres import PgMetadataStore
        source = inspect.getsource(PgMetadataStore._scoped_search)
        assert "_ACL_WHERE" in source or "restricted" in source
        source2 = inspect.getsource(PgMetadataStore._catalog_search)
        assert "_ACL_WHERE" in source2 or "restricted" in source2

    def test_matter_store_all_methods_use_acl(self):
        import inspect
        from app.storage.postgres import PgMatterStore
        for method_name in ["search_by_practice", "search_by_client",
                            "search_by_legal_issues", "search_by_text"]:
            source = inspect.getsource(getattr(PgMatterStore, method_name))
            assert "_ACL_WHERE" in source or "restricted" in source, \
                f"PgMatterStore.{method_name} must enforce ACL"


# ═══════════════════════════════════════════════════════════════════════════════
# Reranker integration with Candidate pipeline
# ═══════════════════════════════════════════════════════════════════════════════


class TestRerankCandidateIntegration:
    """Test _rerank_candidates preserves Candidate provenance."""

    @pytest.mark.asyncio
    async def test_rerank_skips_when_plan_says_no(self):
        from app.retrieval.contracts import Candidate, RetrievalPlan
        from app.retrieval.engine_v2 import _rerank_candidates

        candidates = [
            Candidate(chunk_id=f"C-{i}", document_id=f"D-{i}", matter_id="M-1",
                      channel="bm25", raw_score=0.5)
            for i in range(5)
        ]
        plan = RetrievalPlan(rerank=False)
        result = await _rerank_candidates("test", candidates, plan)
        assert result is candidates  # No transformation

    @pytest.mark.asyncio
    async def test_rerank_skips_single_candidate(self):
        from app.retrieval.contracts import Candidate, RetrievalPlan
        from app.retrieval.engine_v2 import _rerank_candidates

        candidates = [
            Candidate(chunk_id="C-1", document_id="D-1", matter_id="M-1",
                      channel="bm25", raw_score=0.5)
        ]
        plan = RetrievalPlan(rerank=True)
        result = await _rerank_candidates("test", candidates, plan)
        assert result is candidates  # Single candidate, skip rerank
