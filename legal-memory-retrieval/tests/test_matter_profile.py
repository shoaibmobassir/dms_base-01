"""Unit tests for P5.6-C4 matter evidence profiles."""
from __future__ import annotations

from app.retrieval.matter_profile import (
    build_query_evidence_intent,
    infer_theme_keys,
    score_matter_profile,
)


def test_theme_inference():
    assert infer_theme_keys("insider trading SCNs") == ["sebi_insider"]
    assert infer_theme_keys("joint venture deadlocks and shotgun") == ["jv"]


def test_intent_and_score_theme_dominates():
    intent = build_query_evidence_intent(
        "Have we advised on unpublished price sensitive information or insider trading SCNs?",
        search_text="unpublished price sensitive information or insider trading SCNs",
        practice_area="Regulatory",
    )
    assert intent.theme_keys == ["sebi_insider"]
    holder = {
        "theme_key": "sebi_insider",
        "practice_area": "Regulatory",
        "legal_issues": ["UPSI", "Connected person"],
        "title": "Kalla Ltd. — Competition Commission",
        "client_name": "Kalla Ltd.",
        "opposing_party": "X",
        "document_types": ["Engagement Letter"],
        "doc_evidence_score": 0.1,
        "lexical_score": 0.01,
    }
    other = {**holder, "theme_key": "jv"}
    s_h, _ = score_matter_profile(holder, intent)
    s_o, _ = score_matter_profile(other, intent)
    assert s_h > s_o
