"""Harbour benchmark builder and retrieval-cache key shape."""
from __future__ import annotations

import json
from pathlib import Path

from evals.build_harbour_benchmark import (
    argument_rows,
    exact_rows,
    negative_rows,
    related_rows,
)


def test_harbour_sets_cover_retrieval_tasks() -> None:
    rows = exact_rows() + argument_rows() + negative_rows() + related_rows(limit=8)
    types = {row["type"] for row in rows}
    assert {"exact", "argument", "negative", "related_matter"} <= types
    for row in rows:
        assert row["question_id"].startswith("H-")
        assert row["question"]
        assert "expected_documents" in row
        assert "expected_matters" in row


def test_negative_rows_carry_absent_terms() -> None:
    for row in negative_rows():
        assert row["should_abstain"] is True
        assert row["absent_terms"]
        assert not row["expected_documents"]


def test_retrieval_cache_key_includes_index_version(monkeypatch) -> None:
    from app.cache.multi_tier import CacheTier, _cache_key
    from app.config import settings

    monkeypatch.setattr(settings, "index_version", "harbour-v1")
    monkeypatch.setattr(settings, "knowledge_version", 1)
    monkeypatch.setattr(settings, "permission_version", 1)
    key_a = _cache_key(CacheTier.RETRIEVAL, "lotus", "MEM-00001")
    monkeypatch.setattr(settings, "index_version", "harbour-v2")
    key_b = _cache_key(CacheTier.RETRIEVAL, "lotus", "MEM-00001")
    monkeypatch.setattr(settings, "knowledge_version", 2)
    key_c = _cache_key(CacheTier.RETRIEVAL, "lotus", "MEM-00001")
    monkeypatch.setattr(settings, "permission_version", 2)
    key_d = _cache_key(CacheTier.RETRIEVAL, "lotus", "MEM-00001")
    assert key_a != key_b
    assert key_b != key_c
    assert key_c != key_d
    assert key_a.startswith("ret:")


def test_related_rows_are_one_question_per_seed() -> None:
    rows = related_rows()
    questions = [row["question"] for row in rows]
    assert questions
    assert len(questions) == len(set(questions))
    assert any(len(row["expected_matters"]) > 1 for row in rows)
    assert {row["relationship"] for row in rows} >= {
        "same_client",
        "similar_facts",
        "precedent_for",
        "follow_up_to",
    }


def test_exact_gold_is_corpus_labeled() -> None:
    rows = exact_rows()
    lotus = next(row for row in rows if "Lotus" in row["question"])
    assert "DOC-00031" in lotus["expected_documents"]
    assert "MTR-1927-00010" in lotus["expected_matters"]
    payload = json.dumps(lotus)
    assert "MTR-1927-00010" in payload
    assert Path("evals/build_harbour_benchmark.py").exists()


def test_independent_holdout_is_disjoint_and_corpus_labeled() -> None:
    from evals.build_independent_holdout import FORBIDDEN_PREFIXES, build_rows

    official = {
        json.loads(line)["question"]
        for line in Path("evals/harbour_benchmark.jsonl").read_text().splitlines()
        if line.strip()
    }
    rows = build_rows()
    questions = [row["question"] for row in rows]
    assert questions
    assert len(questions) == len(set(questions))
    assert not (set(questions) & official)
    for row in rows:
        assert not row["question"].lower().startswith(FORBIDDEN_PREFIXES)
        if row["type"] == "negative":
            assert row["absent_terms"]
            assert not row["expected_documents"]
        elif row["gold_target"] == "document":
            assert row["expected_documents"]
        elif row["gold_target"] == "matter":
            assert row["expected_matters"]
    types = {row["type"] for row in rows}
    assert {
        "matter_name",
        "document_name",
        "matter_code",
        "client_name",
        "related_matter",
        "paraphrase",
        "negative",
    } <= types
