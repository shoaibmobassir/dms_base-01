"""Unit tests for P5.6 matter-scope helpers (no DB)."""
from __future__ import annotations

import os

import pytest

from app.retrieval.matter_scope import (
    active_matter_scope,
    adjust_fusion_weights,
    apply_channel_plan,
    scope_filters,
    scope_stats,
    should_apply_matter_scope,
    should_boost_matter_score,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("MATTER_SCOPE", raising=False)
    monkeypatch.delenv("MATTER_SCOPE_CHANNELS", raising=False)


def test_default_scope_hard():
    assert active_matter_scope() == "hard"
    assert should_apply_matter_scope("matter_research")
    assert scope_filters(["M1"], "matter_research") == {"matter_ids": ["M1"]}


def test_off_disables_filters(monkeypatch):
    monkeypatch.setenv("MATTER_SCOPE", "off")
    assert active_matter_scope() == "off"
    assert not should_apply_matter_scope("matter_research")
    assert scope_filters(["M1"], "matter_research") is None


def test_hard_scope_filters_matter_research(monkeypatch):
    monkeypatch.setenv("MATTER_SCOPE", "hard")
    assert should_apply_matter_scope("matter_research")
    assert not should_apply_matter_scope("exact_lookup")
    assert not should_apply_matter_scope("similar_matter")
    assert scope_filters(["M1", "M2"], "matter_research") == {"matter_ids": ["M1", "M2"]}
    weights = adjust_fusion_weights({"matter": 0.5, "bm25": 1.0}, "matter_research")
    assert weights["matter"] == 0.0
    assert weights["bm25"] == 1.0


def test_score_boost(monkeypatch):
    monkeypatch.setenv("MATTER_SCOPE", "score")
    assert should_boost_matter_score("matter_research")
    assert not should_apply_matter_scope("matter_research")
    weights = adjust_fusion_weights({"matter": 0.5}, "matter_research")
    assert weights["matter"] == 1.5


def test_hier_channel_override(monkeypatch):
    monkeypatch.setenv("MATTER_SCOPE", "hier")
    monkeypatch.setenv("MATTER_SCOPE_CHANNELS", "hierarchical")
    planned = apply_channel_plan(
        ["bm25", "vector", "matter", "hierarchical"],
        "matter_research",
    )
    assert planned == ["hierarchical"]


def test_hard_injects_matter_scope(monkeypatch):
    monkeypatch.setenv("MATTER_SCOPE", "hard")
    planned = apply_channel_plan(
        ["bm25", "vector", "matter", "metadata"],
        "matter_research",
    )
    assert "matter" not in planned
    assert "matter_scope" in planned
    weights = adjust_fusion_weights({"matter": 0.5, "bm25": 1.0}, "matter_research")
    assert weights["matter"] == 0.0
    assert weights["matter_scope"] == 1.2


def test_scope_stats_crr():
    stats = scope_stats(
        [{"matter_id": "M1", "document_count": 10, "score": 80}],
        corpus_documents=1000,
    )
    assert stats["candidate_reduction_ratio"] == 100.0
