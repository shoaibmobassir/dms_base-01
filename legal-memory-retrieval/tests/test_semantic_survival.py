"""Unit tests for P5.6-B0 survival helpers (no DB)."""
from __future__ import annotations

from app.retrieval.contracts import Candidate, Provenance
from app.retrieval.semantic_survival import (
    QuerySurvival,
    _classify_drop,
    _survival,
    aggregate_survival,
)


def _cand(doc_id: str, score: float = 1.0) -> Candidate:
    return Candidate(
        document_id=doc_id,
        matter_id="M1",
        matter_code="MTR-1",
        title=doc_id,
        text="x",
        chunk_id=f"{doc_id}-0",
        chunk_index=0,
        channel="vector",
        raw_score=score,
        provenance=Provenance(channel="vector", raw_score=score),
    )


def test_survival_recall():
    gold = {"D1", "D2", "D3"}
    cands = [_cand("D1", 3), _cand("X", 2), _cand("D2", 1)]
    s = _survival("vector", cands, gold)
    assert s.gold_docs_hit == 2
    assert s.recall["R@20"] == 2 / 3


def test_outcome_candidate_generation():
    rows = []
    for i in range(3):
        q = QuerySurvival(
            query_id=f"Q{i}",
            query="q",
            intent="semantic",
            n_gold_docs=20,
            n_gold_matters=0,
            channels_planned=["vector"],
            matter_scope_mode="hard",
            fusion_policy="p55_repair_ce_protect",
        )
        q.channel["vector"] = _survival("vector", [_cand("X")], {"D1", "D2"})
        q.union = q.channel["vector"]
        q.fusion = q.union
        q.ce = q.union
        q.final = q.union
        q.drop_stage = _classify_drop(q)
        rows.append(q)
    agg = aggregate_survival(rows)
    assert agg["outcome"] == "A_candidate_generation"
