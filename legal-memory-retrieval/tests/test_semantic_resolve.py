"""Unit tests for P5.6-C0 semantic matter→doc routing helpers."""
from __future__ import annotations

from app.retrieval.contracts import Candidate, Provenance
from app.retrieval.semantic_resolve import (
    matter_ids_from_ranked,
    rank_matters_from_vector,
    routing_stats,
    should_semantic_doc_resolve,
)


def _c(matter_id: str, doc_id: str, score: float) -> Candidate:
    return Candidate(
        chunk_id=f"{doc_id}-0",
        document_id=doc_id,
        matter_id=matter_id,
        raw_score=score,
        channel="vector",
        provenance=Provenance(channel="vector", raw_score=score),
    )


def test_rank_matters_dedupes_and_orders():
    cands = [
        _c("M1", "D1", 0.9),
        _c("M1", "D2", 0.5),
        _c("M2", "D3", 0.8),
        _c("M3", "D4", 0.7),
    ]
    ranked = rank_matters_from_vector(cands, k=2)
    assert matter_ids_from_ranked(ranked) == ["M1", "M2"]
    assert ranked[0]["score"] == 0.9


def test_routing_stats_ceiling():
    ranked = [{"matter_id": "M1", "score": 1.0}, {"matter_id": "M2", "score": 0.5}]
    stats = routing_stats(
        ranked,
        gold_matters={"M1", "M9"},
        gold_docs={"D1", "D2"},
        docs_in_scope={"D1", "DX"},
    )
    assert stats["matter_hit"] == 1.0
    assert stats["gold_matters_in_routed"] == 1
    assert stats["doc_recall_ceiling"] == 0.5


def test_should_resolve_only_semantic_c0(monkeypatch):
    monkeypatch.setenv("SEMANTIC_DOC_RESOLVE", "c0")
    assert should_semantic_doc_resolve("semantic")
    assert not should_semantic_doc_resolve("matter_research")
    monkeypatch.setenv("SEMANTIC_DOC_RESOLVE", "off")
    assert not should_semantic_doc_resolve("semantic")
