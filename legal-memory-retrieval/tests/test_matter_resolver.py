"""Unit tests for P5.6-C1 matter resolver helpers."""
from __future__ import annotations

from app.retrieval.matter_resolver import (
    build_matter_query_rep,
    holder_coverage,
    min_k_for_coverage,
    rrf_merge_matter_lists,
    to_or_tsquery,
)


def test_concept_expand_insider():
    rep = build_matter_query_rep(
        "Have we advised on unpublished price sensitive information or insider trading SCNs?",
        search_text="unpublished price sensitive information or insider trading SCNs",
        practice_area="Regulatory",
    )
    assert any("insider" in c.lower() or "upsi" in c.lower() for c in rep.concepts)
    assert "Regulatory" in rep.vector_text()


def test_or_tsquery():
    q = to_or_tsquery(["termination right", "lender", "the"])
    assert q is not None
    assert "|" in q
    assert "termination" in q


def test_holder_coverage_and_min_k():
    ranked = [{"matter_id": f"M{i}"} for i in range(1, 21)]
    holders = {"M3", "M10", "M99"}
    cov = holder_coverage(ranked, holders, k=10)
    assert cov["holders_found"] == 2
    assert cov["holder_coverage"] == round(2 / 3, 4)
    assert min_k_for_coverage(ranked, holders, target=0.9, max_k=20) is None
    assert min_k_for_coverage(ranked, {"M3"}, target=0.9, max_k=20) == 3


def test_rrf_merge():
    a = [{"matter_id": "M1", "score": 1.0}, {"matter_id": "M2", "score": 0.5}]
    b = [{"matter_id": "M2", "score": 0.9}, {"matter_id": "M3", "score": 0.8}]
    merged = rrf_merge_matter_lists([a, b], k=3)
    assert {r["matter_id"] for r in merged} == {"M1", "M2", "M3"}
    assert merged[0]["matter_id"] == "M2"  # appears in both
