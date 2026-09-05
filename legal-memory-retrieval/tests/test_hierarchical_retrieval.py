"""P5.3 — Matter → Document → Chunk hierarchical channel + review prune."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.db.pool import acquire, init_pool, pool_stats
from app.query.understand import understand
from app.retrieval.contracts import Candidate
from app.retrieval.planner import plan


class TestPlannerHierarchicalChannel:
    def _parsed(self, intent: str):
        m = MagicMock()
        m.intent = intent
        m.matter_ids = []
        return m

    def test_cross_document_includes_hierarchical(self):
        p = plan(self._parsed("cross_document"))
        assert "hierarchical" in p.channels
        # P5.5: hierarchy is candidate-gen, not a high RRF weight
        assert p.weights.get("hierarchical", 1) <= 0.5

    def test_semantic_includes_hierarchical(self):
        p = plan(self._parsed("semantic"))
        assert "hierarchical" in p.channels

    def test_default_research_includes_hierarchical(self):
        p = plan(self._parsed("matter_research"))
        assert "hierarchical" in p.channels
        assert p.weights.get("matter", 1) <= 0.6
        assert p.weights.get("graph_seed", 1) <= 0.5

    def test_exact_lookup_skips_hierarchical(self):
        p = plan(self._parsed("exact_lookup"))
        assert "hierarchical" not in p.channels


class TestCandidateHierarchicalMetadata:
    def test_from_db_row_keeps_hierarchy_fields(self):
        row = {
            "chunk_id": "CHK-1",
            "document_id": "DOC-1",
            "matter_id": "MTR-1",
            "title": "SPA",
            "text": "Tax indemnity cap",
            "score": 1.5,
            "version_id": "VER-1",
            "section_id": "8.2",
            "page_number": 12,
            "folder_path": "Client/Matter/Agreements",
            "is_parent": False,
            "block_ids": ["BLK-1"],
            "hierarchy": "matter>document>chunk",
            "matter_stage_score": 0.2,
            "doc_stage_score": 0.4,
        }
        c = Candidate.from_db_row(row, "hierarchical")
        assert c.channel == "hierarchical"
        assert c.metadata["version_id"] == "VER-1"
        assert c.metadata["section_id"] == "8.2"
        assert c.metadata["hierarchy"] == "matter>document>chunk"
        assert "metadata" in c.to_dict()


class TestEngineHierarchicalRegistry:
    def test_channel_registered(self):
        from app.retrieval.engine_v2 import _CHANNEL_FNS

        assert "hierarchical" in _CHANNEL_FNS


class TestReviewBlockFilter:
    def test_filter_prefers_matching_blocks(self):
        from app.review.engine import FastReviewEngine

        blocks = [
            {"block_id": "A", "section_id": "1", "text": "a"},
            {"block_id": "B", "section_id": "8.2", "text": "indemnity"},
            {"block_id": "C", "section_id": "9", "text": "c"},
        ]
        filtered = FastReviewEngine._filter_blocks_by_hints(
            blocks, {"block_ids": {"B"}, "section_ids": set()},
        )
        assert [b["block_id"] for b in filtered] == ["B"]

    def test_filter_falls_back_when_no_match(self):
        from app.review.engine import FastReviewEngine

        blocks = [
            {"block_id": "A", "section_id": "1", "text": "a"},
        ]
        filtered = FastReviewEngine._filter_blocks_by_hints(
            blocks, {"block_ids": {"Z"}, "section_ids": {"99"}},
        )
        assert filtered == blocks


@pytest.mark.asyncio
async def test_hierarchical_store_cascade_live_db():
    """Live DB: cascade returns version-scoped children when present, else legacy."""
    from app.storage.postgres import PgHierarchicalStore

    if not pool_stats().get("initialized"):
        await init_pool()
    store = PgHierarchicalStore()
    async with acquire() as conn:
        rows = await store.retrieve(
            conn, "indemnity liability", member_id=None,
            top_matters=8, top_docs=20, top_chunks=30,
        )
    for r in rows:
        assert r.get("document_id")
        assert r.get("matter_id")
        assert "hierarchy" in r
        assert "score" in r
    if rows and any(r.get("version_id") for r in rows):
        assert all(not r.get("is_parent") for r in rows if r.get("version_id"))


@pytest.mark.asyncio
async def test_hierarchical_channel_runs_in_engine():
    from app.retrieval.engine_v2 import _CHANNEL_FNS, _build_context

    if not pool_stats().get("initialized"):
        await init_pool()
    parsed = understand("indemnity tax liability caps")
    ctx = _build_context(parsed, member_id=None, k=10)
    fn = _CHANNEL_FNS["hierarchical"]
    candidates = await fn(ctx, limit=20)
    assert isinstance(candidates, list)
    for c in candidates:
        assert c.channel == "hierarchical"
        assert c.document_id
