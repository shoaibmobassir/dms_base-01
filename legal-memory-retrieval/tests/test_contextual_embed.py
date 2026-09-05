"""Unit tests for C5.5 contextual chunk helpers."""
from __future__ import annotations

from app.retrieval.contextual_embed import (
    aggregate_chunk_scores,
    format_contextual_chunk,
)


def test_format_contextual_chunk_contains_identity():
    text = format_contextual_chunk(
        title="Engagement Letter — Acme — SEBI",
        document_type="Engagement Letter",
        section_title="Scope",
        folder_path="Matter / Correspondence",
        chunk_text="We advise on UPSI and insider trading.",
    )
    assert "[DOCUMENT TITLE]" in text
    assert "Engagement Letter" in text
    assert "[SECTION]" in text
    assert "UPSI" in text


def test_aggregate_max_and_top3():
    chunks = [
        {"document_id": "D1", "matter_id": "M1", "chunk_id": "c1", "score": 0.9, "title": "t"},
        {"document_id": "D1", "matter_id": "M1", "chunk_id": "c2", "score": 0.3, "title": "t"},
        {"document_id": "D1", "matter_id": "M1", "chunk_id": "c3", "score": 0.6, "title": "t"},
        {"document_id": "D2", "matter_id": "M1", "chunk_id": "c4", "score": 0.8, "title": "u"},
    ]
    mx = aggregate_chunk_scores(chunks, method="max")
    assert mx[0]["document_id"] == "D1"
    assert mx[0]["score"] == 0.9
    assert mx[0]["best_chunk_id"] == "c1"
    t3 = {r["document_id"]: r for r in aggregate_chunk_scores(chunks, method="top3_mean")}
    assert abs(t3["D1"]["score"] - (0.9 + 0.6 + 0.3) / 3) < 1e-6
