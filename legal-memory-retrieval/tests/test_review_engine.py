"""Tests for High-Concurrency Review Engine (Map -> Reduce -> Verify).

Verifies:
  - Review Planner feature catalog selection and query generation
  - Map Worker structured legal finding extraction
  - Deterministic Verification Gate quote validation
  - Cross-Document Reduce risk metrics aggregation
"""
from __future__ import annotations

import asyncio
import pytest

from app.review.planner import FEATURE_CATALOG, build_review_plan
from app.review.engine import (
    EvidenceAnchorResult,
    FastReviewEngine,
    FindingResult,
)


class TestReviewPlanner:
    def test_build_plan_with_specific_features(self):
        plan = build_review_plan(
            requested_features=["indemnity", "change_of_control"],
            matter_id="MAT-100",
        )
        assert len(plan.features) == 2
        assert any(f.feature_id == "indemnity" for f in plan.features)
        assert any(f.feature_id == "change_of_control" for f in plan.features)
        assert "indemnify" in plan.keywords_filter
        assert "change of control" in plan.keywords_filter

    def test_build_plan_from_query_intent(self):
        plan = build_review_plan(
            query_text="Review all agreements for liability caps, governing law and termination rights",
        )
        assert any(f.feature_id == "liability" for f in plan.features)
        assert any(f.feature_id == "governing_law" for f in plan.features)
        assert any(f.feature_id == "termination" for f in plan.features)


class TestReviewEngine:
    @pytest.mark.asyncio
    async def test_map_worker_extracts_findings(self):
        engine = FastReviewEngine(max_concurrency=5)
        plan = build_review_plan(requested_features=["indemnity", "liability"])

        doc = {
            "document_id": "DOC-001",
            "title": "Share Purchase Agreement v8",
            "version_id": "VER-008",
        }
        blocks = [
            {
                "block_id": "BLK-01",
                "page_number": 47,
                "start_offset": 100,
                "text": "Section 8.2 Tax Indemnity. The aggregate liability of the Seller shall not exceed $75,000.",
            },
            {
                "block_id": "BLK-02",
                "page_number": 52,
                "start_offset": 300,
                "text": "Section 11.1 Governing Law. Governed by Delaware law.",
            },
        ]

        findings = await engine._map_document_findings(doc, blocks, plan)
        assert len(findings) >= 1

        f = findings[0]
        assert f.document_id == "DOC-001"
        assert f.financial_impact_usd == 75000.0
        assert len(f.evidence_anchors) == 1
        assert f.evidence_anchors[0].block_id == "BLK-01"

    def test_deterministic_verify_gate(self):
        engine = FastReviewEngine()
        doc_block_map = {
            "DOC-001": (
                {"document_id": "DOC-001", "title": "SPA"},
                [
                    {
                        "block_id": "BLK-01",
                        "text": "Section 8.2 Tax Indemnity. The aggregate liability shall not exceed $75,000.",
                    }
                ],
            )
        }

        # Valid finding with matching quote
        valid_anchor = EvidenceAnchorResult(
            anchor_id="ANC-01",
            version_id="VER-01",
            block_id="BLK-01",
            page_number=47,
            start_offset=0,
            end_offset=30,
            quoted_text="aggregate liability shall not exceed $75,000",
            text_hash="hash123",
        )
        valid_finding = FindingResult(
            finding_id="FND-01",
            document_id="DOC-001",
            document_title="SPA",
            version_id="VER-01",
            category="indemnity",
            severity="high",
            title="Indemnity cap",
            explanation="Cap found",
            risk_direction="risk_increased",
            financial_impact_usd=75000.0,
            confidence_score=0.95,
            evidence_anchors=[valid_anchor],
        )

        # Hallucinated finding with quote that doesn't exist in block
        fake_anchor = EvidenceAnchorResult(
            anchor_id="ANC-02",
            version_id="VER-01",
            block_id="BLK-01",
            page_number=47,
            start_offset=0,
            end_offset=30,
            quoted_text="unlimited liability for all environmental contamination",
            text_hash="fakehash",
        )
        fake_finding = FindingResult(
            finding_id="FND-02",
            document_id="DOC-001",
            document_title="SPA",
            version_id="VER-01",
            category="liability",
            severity="critical",
            title="Environmental liability",
            explanation="Hallucinated text",
            risk_direction="risk_increased",
            financial_impact_usd=None,
            confidence_score=0.90,
            evidence_anchors=[fake_anchor],
        )

        verified = engine._verify_findings([valid_finding, fake_finding], doc_block_map)
        assert len(verified) == 1
        assert verified[0].finding_id == "FND-01"

    def test_reduce_executive_summary(self):
        engine = FastReviewEngine()
        plan = build_review_plan(requested_features=["indemnity", "liability"])

        findings = [
            FindingResult(
                finding_id="FND-01",
                document_id="DOC-01",
                document_title="SPA 1",
                version_id="VER-01",
                category="indemnity",
                severity="high",
                title="Tax Indemnity",
                explanation="...",
                risk_direction="risk_increased",
                financial_impact_usd=75000.0,
                confidence_score=0.95,
            ),
            FindingResult(
                finding_id="FND-02",
                document_id="DOC-02",
                document_title="SPA 2",
                version_id="VER-02",
                category="liability",
                severity="critical",
                title="Liability Cap",
                explanation="...",
                risk_direction="risk_increased",
                financial_impact_usd=50000.0,
                confidence_score=0.95,
            ),
        ]

        summary = engine._reduce_executive_summary(findings, total_docs=50, plan=plan)
        assert summary["total_documents_scanned"] == 50
        assert summary["relevant_documents_count"] == 2
        assert summary["total_findings"] == 2
        assert summary["severity_breakdown"]["critical"] == 1
        assert summary["severity_breakdown"]["high"] == 1
        assert summary["estimated_aggregate_financial_exposure_usd"] == 125000.0
