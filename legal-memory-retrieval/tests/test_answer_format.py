"""Tests for DMS answer format module.

Tests:
  - structured citations include matter_id + document_type + tags
  - matchedMatters are deduplicated by matter_id
  - sources are deduplicated by document_id
  - key_finding falls back to first paragraph
  - _build_tags produces correct tag structure
  - empty hits handled gracefully
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.answers.format import (
    _build_matched_matters,
    _build_tags,
    _structured_citation,
    format_dms_response,
)


@pytest.fixture
def sample_hits():
    return [
        {
            "document_id": "DOC-R001",
            "matter_id": "MTR-REAL-00001",
            "matter_code": "REAL/ENR/MSEDCL/2018",
            "title": "MSEDCL Note",
            "document_type": "Brief Note",
            "client_name": "MSEDCL",
            "court": "APTEL",
            "practice_area": "Regulatory",
            "text": "MSEDCL submits this note.",
            "fused_score": 0.8,
            "rerank_score": 0.9,
        },
        {
            "document_id": "DOC-R002",
            "matter_id": "MTR-REAL-00001",
            "matter_code": "REAL/ENR/MSEDCL/2018",
            "title": "Rejoinder",
            "document_type": "Rejoinder",
            "client_name": "MSEDCL",
            "court": "APTEL",
            "text": "The rejoinder argues floods were force majeure.",
            "fused_score": 0.6,
        },
        {
            "document_id": "DOC-R003",
            "matter_id": "MTR-REAL-00002",
            "matter_code": "REAL/ENR/VGREEN/2026",
            "title": "Vector Green Submission",
            "document_type": "Written Submission",
            "client_name": "Vector Green",
            "court": "CERC",
            "text": "Vector Green submits tariff arguments.",
            "fused_score": 0.4,
        },
    ]


class TestBuildTags:
    def test_full_tags(self, sample_hits):
        tags = _build_tags(sample_hits[0])
        tag_keys = {t["key"] for t in tags}
        assert "Matter ID" in tag_keys
        assert "Document Type" in tag_keys
        assert "Client" in tag_keys
        assert "Forum" in tag_keys

    def test_empty_hit(self):
        tags = _build_tags({})
        assert tags == []

    def test_partial_hit(self):
        tags = _build_tags({"matter_id": "MTR-001"})
        assert len(tags) == 1
        assert tags[0]["key"] == "Matter ID"


class TestStructuredCitation:
    def test_full_citation(self, sample_hits):
        cite = _structured_citation(sample_hits[0])
        assert cite["document_id"] == "DOC-R001"
        assert cite["matter_id"] == "MTR-REAL-00001"
        assert cite["document_type"] == "Brief Note"
        assert len(cite["tags"]) > 0


class TestMatchedMatters:
    def test_deduplication(self, sample_hits):
        matched = _build_matched_matters(sample_hits)
        matter_ids = [m["matter_id"] for m in matched]
        assert len(matter_ids) == 2  # Two unique matters
        assert matter_ids[0] == "MTR-REAL-00001"  # Higher score first

    def test_document_count(self, sample_hits):
        matched = _build_matched_matters(sample_hits)
        msedcl = next(m for m in matched if m["matter_id"] == "MTR-REAL-00001")
        assert msedcl["document_count"] == 2

    def test_empty(self):
        assert _build_matched_matters([]) == []


class TestFormatDmsResponse:
    @patch("app.answers.format._enrich_hits_with_matter_data", side_effect=lambda h: h)
    def test_full_response(self, mock_enrich, sample_hits):
        result = format_dms_response(
            query="What about MSEDCL?",
            answer_result={"answer": "MSEDCL argued X.", "key_finding": "MSEDCL argued force majeure."},
            hits=sample_hits,
            retrieval_latency={"total_ms": 100},
        )
        assert result["key_finding"] == "MSEDCL argued force majeure."
        assert len(result["structured_citations"]) > 0
        assert len(result["matchedMatters"]) == 2
        assert len(result["tags"]) > 0

    @patch("app.answers.format._enrich_hits_with_matter_data", side_effect=lambda h: h)
    def test_key_finding_fallback(self, mock_enrich, sample_hits):
        result = format_dms_response(
            query="test",
            answer_result={"answer": "First paragraph answer.\n\nSecond paragraph."},
            hits=sample_hits,
            retrieval_latency={},
        )
        assert "First paragraph" in result["key_finding"]

    @patch("app.answers.format._enrich_hits_with_matter_data", side_effect=lambda h: h)
    def test_empty_hits(self, mock_enrich):
        result = format_dms_response(
            query="test", answer_result={}, hits=[], retrieval_latency={},
        )
        assert result["tags"] == []
        assert result["matchedMatters"] == []
