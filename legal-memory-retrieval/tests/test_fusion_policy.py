"""Unit tests for P5.5 fusion policy (no DB)."""
from __future__ import annotations

from app.retrieval.contracts import Candidate, Provenance
from app.retrieval.fusion_policy import (
    POLICIES,
    apply_ce_protection,
    merge_plan_weights,
)


class TestFusionPolicy:
    def test_repair_zeros_hierarchical_rank_weight(self):
        w = merge_plan_weights(
            {"bm25": 1.0, "hierarchical": 1.2, "graph_seed": 0.9},
            POLICIES["p55_repair"],
        )
        assert w["hierarchical"] == 0.0
        assert w["graph_seed"] <= 0.5
        assert w["bm25"] == 1.0

    def test_exact_lookup_weights_untouched(self):
        base = {"metadata": 2.0, "bm25": 1.0}
        w = merge_plan_weights(base, POLICIES["p55_repair"], intent="exact_lookup")
        assert w == base

    def test_ce_protection_keeps_lexical_candidate_up(self):
        gold = Candidate(
            chunk_id="G",
            document_id="DOC-G",
            matter_id="M",
            channel="bm25",
            fusion_score=0.9,
            rerank_score=0.1,  # CE hated it
            provenance=Provenance(
                channel="bm25",
                channels_found_in=["bm25", "metadata"],
                ce_score=0.1,
            ),
        )
        noise = Candidate(
            chunk_id="N",
            document_id="DOC-N",
            matter_id="M",
            channel="vector",
            fusion_score=0.1,
            rerank_score=0.95,
            provenance=Provenance(
                channel="vector",
                channels_found_in=["vector"],
                ce_score=0.95,
            ),
        )
        out = apply_ce_protection([noise, gold], POLICIES["p55_repair_ce_protect"])
        ranks = {c.chunk_id: i for i, c in enumerate(out)}
        assert ranks["G"] <= ranks["N"]
