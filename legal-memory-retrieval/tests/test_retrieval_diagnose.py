"""Unit tests for P5.4 stage-rank diagnosis (no DB required for core logic)."""
from __future__ import annotations

from app.retrieval.contracts import Candidate, Provenance
from app.retrieval.diagnose import assign_stage_ranks, summarize_rows


def _c(chunk: str, doc: str, matter: str, channel: str, score: float) -> Candidate:
    return Candidate(
        chunk_id=chunk,
        document_id=doc,
        matter_id=matter,
        channel=channel,
        raw_score=score,
        provenance=Provenance(channel=channel, raw_score=score),
    )


class TestAssignStageRanks:
    def test_relevant_drop_after_fusion(self):
        gold = {"DOC-GOOD"}
        by_channel = {
            "vector": [
                _c("CHK-G", "DOC-GOOD", "M1", "vector", 0.9),
                _c("CHK-B", "DOC-BAD", "M1", "vector", 0.5),
            ],
            "hierarchical": [
                _c("CHK-B", "DOC-BAD", "M1", "hierarchical", 0.99),
                _c("CHK-G", "DOC-GOOD", "M1", "hierarchical", 0.1),
            ],
        }
        fused = [
            _c("CHK-B", "DOC-BAD", "M1", "hierarchical", 0.99),
            _c("CHK-G", "DOC-GOOD", "M1", "vector", 0.9),
        ]
        fused[0].fusion_score = 0.02
        fused[1].fusion_score = 0.01
        final = fused[:1]

        rows = assign_stage_ranks(
            query_id="Q1",
            query="test",
            query_type="exact",
            intent="matter_research",
            by_channel=by_channel,
            fused=fused,
            reranked=None,
            final=final,
            gold_docs=gold,
            gold_matters=set(),
        )
        by_doc = {r.document_id: r for r in rows}
        good = by_doc["DOC-GOOD"]
        assert good.is_relevant == 1
        assert good.vector_rank == 1
        assert good.hierarchical_rank == 2
        assert good.rrf_rank == 2
        assert good.final_rank is None

        summary = summarize_rows(rows)
        assert summary["relevant_drop_count"] >= 1
        stages = summary["relevant_drop_stages"]
        # RRF still had gold at rank 2; final top-1 cutoff (no CE score) → topk
        assert "final_topk_cutoff" in stages or "fusion_or_hierarchy_channel" in stages

    def test_channel_combo_string(self):
        by_channel = {
            "bm25": [_c("CHK-1", "DOC-1", "M1", "bm25", 1.0)],
            "vector": [_c("CHK-1", "DOC-1", "M1", "vector", 0.8)],
        }
        fused = [_c("CHK-1", "DOC-1", "M1", "bm25", 1.0)]
        fused[0].fusion_score = 0.05
        rows = assign_stage_ranks(
            query_id="Q2",
            query="q",
            query_type="exact",
            intent="exact_lookup",
            by_channel=by_channel,
            fused=fused,
            reranked=fused,
            final=fused,
            gold_docs={"DOC-1"},
            gold_matters=set(),
        )
        assert rows[0].retrieved_by == "bm25|vector"
        assert rows[0].final_rank == 1
        assert rows[0].is_relevant == 1
