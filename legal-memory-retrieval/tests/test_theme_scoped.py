"""Unit tests for P5.6-C5 theme-scoped helpers."""
from __future__ import annotations

from app.retrieval.theme_scoped import (
    resolve_theme_keys,
    rrf_merge_doc_lists,
    scope_reduction_ratio,
)


def test_resolve_theme_keys_limits():
    intent = resolve_theme_keys(
        "Have we advised on unpublished price sensitive information or insider trading SCNs?",
        max_themes=1,
    )
    assert intent.theme_keys == ["sebi_insider"]


def test_rrf_docs_and_srr():
    a = [{"document_id": "D1", "score": 1.0}, {"document_id": "D2", "score": 0.5}]
    b = [{"document_id": "D2", "score": 0.9}, {"document_id": "D3", "score": 0.8}]
    merged = rrf_merge_doc_lists([a, b], k=3)
    assert {r["document_id"] for r in merged} == {"D1", "D2", "D3"}
    assert scope_reduction_ratio(10000, 100) == 100.0
