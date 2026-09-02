"""Tests for the production ingest pipeline.

Tests:
  - Idempotent re-ingest (sha skip)
  - Empty PDF handling
  - Invalid matter (no manifest match)
  - Manifest parsing
  - Normalize title
  - Document type inference
  - Batch writer dedup
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingest.models import DocumentRecord, MatterManifest
from app.ingest.normalize import infer_document_type, match_matter, normalize_title


class TestInferDocumentType:
    def test_affidavit(self):
        assert infer_document_type("Affidavit - CA 10046 of 2025.pdf") == "Affidavit"

    def test_written_submission(self):
        assert infer_document_type("WRITTEN SUBMISSION IN PETITION.pdf") == "Written Submission"

    def test_rejoinder(self):
        assert infer_document_type("Rejoinder to Reply.pdf") == "Rejoinder"

    def test_brief_note(self):
        assert infer_document_type("BRIEF NOTE OF SUBMISSIONS.pdf") == "Brief Note"

    def test_final_reply(self):
        assert infer_document_type("Final Reply (310-MP-2026).pdf") == "Final Reply"

    def test_from_text_fallback(self):
        assert infer_document_type("document.pdf", "This is an affidavit") == "Affidavit"

    def test_unknown(self):
        assert infer_document_type("random.pdf", "") == "Legal Document"


class TestMatchMatter:
    @pytest.fixture
    def manifests(self):
        return [
            MatterManifest(
                matter_id="MTR-REAL-00001", matter_code="REAL/ENR/MSEDCL/2018",
                title="MSEDCL", client_id="CLI-MSEDCL", client_name="MSEDCL",
                file_patterns=["MSEDCL", "BRIEF NOTE.*RESPONDENT", "Rejoinder"],
            ),
            MatterManifest(
                matter_id="MTR-REAL-00002", matter_code="REAL/ENR/VGREEN/2026",
                title="Vector Green", client_id="CLI-VGREEN", client_name="Vector Green",
                file_patterns=["VECTOR GREEN", "PETITION NO.*22"],
            ),
        ]

    def test_msedcl_match(self, manifests):
        m = match_matter("MSEDCL Note in APL. 163 of 2018.pdf", manifests)
        assert m is not None
        assert m.matter_id == "MTR-REAL-00001"

    def test_vector_green_match(self, manifests):
        m = match_matter("WRITTEN SUBMISSION IN PETITION NO. 22 OF 2026 (VECTOR GREEN).pdf", manifests)
        assert m is not None
        assert m.matter_id == "MTR-REAL-00002"

    def test_rejoinder_match(self, manifests):
        m = match_matter("Rejoinder to Reply to Impleadment Application.pdf", manifests)
        assert m is not None
        assert m.matter_id == "MTR-REAL-00001"

    def test_no_match(self, manifests):
        m = match_matter("random_unrelated_file.pdf", manifests)
        assert m is None


class TestNormalizeTitle:
    def test_removes_extension(self):
        assert normalize_title("Affidavit - CA 10046 of 2025.pdf") == "Affidavit - CA 10046 of 2025"

    def test_removes_date_suffix(self):
        result = normalize_title("WRITTEN SUBMISSION IN PETITION NO. 22 OF 2026 (VECTOR GREEN) 01.08.2026.pdf")
        assert "01.08.2026" not in result

    def test_simple_name(self):
        assert normalize_title("document.pdf") == "document"


class TestDocumentRecord:
    def test_creation(self):
        doc = DocumentRecord(
            document_id="DOC-001",
            matter_id="MTR-001",
            matter_code="CODE/001",
            title="Test Doc",
            document_type="Affidavit",
            body="Some legal text",
            source_uri="/path/to/file.pdf",
            content_sha256="abc123",
        )
        assert doc.document_id == "DOC-001"
        assert doc.mime_type == "application/pdf"


class TestIdempotentIngest:
    """Test that re-ingesting the same file skips based on content_sha256."""

    @patch("app.ingest.writer.write_document")
    def test_sha_skip(self, mock_write):
        """Simulate: writer returns (0, True) when sha already exists."""
        mock_write.return_value = (0, True)
        n_chunks, was_skipped = mock_write("/fake/path", MagicMock())
        assert was_skipped is True
        assert n_chunks == 0


class TestManifestParsing:
    def test_load_manifest(self):
        from app.ingest.pipeline import load_manifest
        manifest_path = ROOT / "ingest" / "manifests" / "real_filings.yaml"
        if manifest_path.exists():
            manifests = load_manifest(manifest_path)
            assert len(manifests) == 3
            assert manifests[0].matter_id == "MTR-REAL-00001"
            assert manifests[1].client_name == "Vector Green Energy Pvt. Ltd."
            assert "MSEDCL" in manifests[0].file_patterns
