"""Tests for metadata_extractor.py — PDF metadata extraction.

Tests:
  - Document type extraction from filenames and text
  - Forum/court extraction
  - Case number extraction with various formats
  - Matter ID extraction (MWSP_PROJ, MTR- patterns)
  - Client name heuristics
  - Tag inference from content
  - Metadata override merging
  - Edge cases: empty text, no matches, multiple matches
"""
from metadata_extractor import (
    extract_all,
    extract_case_number,
    extract_client,
    extract_document_type,
    extract_forum,
    extract_matter_id,
    extract_tags,
    extract_with_overrides,
)


class TestExtractDocumentType:
    def test_affidavit_from_filename(self):
        assert extract_document_type("Affidavit - CA 10046 of 2025.pdf", "") == "Affidavit"

    def test_written_submission_from_filename(self):
        assert extract_document_type("WRITTEN SUBMISSION IN PETITION NO. 22.pdf", "") == "Written Submission"

    def test_rejoinder_from_filename(self):
        assert extract_document_type("Rejoinder to Reply.pdf", "") == "Rejoinder"

    def test_brief_note_from_filename(self):
        assert extract_document_type("BRIEF NOTE OF SUBMISSIONS.pdf", "") == "Brief Note"

    def test_reply_from_filename(self):
        assert extract_document_type("Final Reply (310-MP-2026).pdf", "") == "Final Reply"

    def test_type_from_text_fallback(self):
        assert extract_document_type("document.pdf", "This is an affidavit filed on behalf of...") == "Affidavit"

    def test_unknown_default(self):
        assert extract_document_type("random.pdf", "nothing relevant here") == "Legal Document"

    def test_writ_petition(self):
        assert extract_document_type("Writ Petition filed in Gujarat.pdf", "") == "Writ Petition"


class TestExtractForum:
    def test_cerc(self):
        assert extract_forum("Filed before CERC in the matter") == "CERC"

    def test_aptel(self):
        assert extract_forum("Appeal before APTEL") == "APTEL"

    def test_merc(self):
        assert extract_forum("MERC tariff order") == "MERC"

    def test_supreme_court(self):
        assert extract_forum("Hon'ble Supreme Court of India") == "Supreme Court"

    def test_msedcl(self):
        assert extract_forum("MSEDCL distribution company") == "MSEDCL"

    def test_no_match(self):
        assert extract_forum("some random text without any forum mention") is None

    def test_empty_text(self):
        assert extract_forum("") is None


class TestExtractCaseNumber:
    def test_pn_format(self):
        result = extract_case_number("P.N. 186 of 2026")
        assert result is not None
        assert "186" in result
        assert "2026" in result

    def test_petition_no_format(self):
        result = extract_case_number("Petition No. 22 of 2026")
        assert result is not None
        assert "22" in result

    def test_ca_format(self):
        result = extract_case_number("CA 10046 of 2025")
        assert result is not None
        assert "10046" in result

    def test_mp_format(self):
        result = extract_case_number("310-MP-2026")
        assert result is not None
        assert "310-MP-2026" in result

    def test_apl_format(self):
        result = extract_case_number("APL. 163 of 2018")
        assert result is not None
        assert "163" in result

    def test_no_match(self):
        assert extract_case_number("no case number here") is None

    def test_empty_text(self):
        assert extract_case_number("") is None


class TestExtractMatterId:
    def test_mwsp_proj_format(self):
        result = extract_matter_id("Matter: MWSP_PROJ000031537")
        assert result == "MWSP_PROJ000031537"

    def test_mtr_format(self):
        result = extract_matter_id("Reference: MTR-2024-00123")
        assert result == "MTR-2024-00123"

    def test_no_match(self):
        assert extract_matter_id("no matter id here") is None

    def test_empty_text(self):
        assert extract_matter_id("") is None

    def test_case_insensitive_mwsp(self):
        result = extract_matter_id("mwsp_proj000012345")
        assert result is not None


class TestExtractClient:
    def test_avaada(self):
        assert extract_client("Avaada Energy Pvt. Ltd. filed the petition") == "Avaada Energy Pvt. Ltd."

    def test_msedcl(self):
        assert extract_client("MSEDCL is the respondent") == "MSEDCL"

    def test_vector_green(self):
        assert extract_client("Vector Green Energy submits") == "Vector Green Energy Pvt. Ltd."

    def test_no_match(self):
        assert extract_client("unknown entity filed this") is None

    def test_empty_text(self):
        assert extract_client("") is None


class TestExtractTags:
    def test_force_majeure(self):
        tags = extract_tags("doc.pdf", "force majeure clause invoked")
        assert "Force Majeure" in tags

    def test_multiple_tags(self):
        tags = extract_tags("doc.pdf", "The tariff determination under the PPA in Gujarat")
        assert "Tariff" in tags
        assert "PPA" in tags
        assert "Gujarat" in tags

    def test_no_tags(self):
        tags = extract_tags("doc.pdf", "nothing relevant")
        assert tags == []

    def test_tags_from_filename(self):
        tags = extract_tags("Force Majeure Analysis.pdf", "")
        assert "Force Majeure" in tags

    def test_electricity_tag(self):
        tags = extract_tags("doc.pdf", "electricity sector regulation")
        assert "Electricity" in tags
        assert "Regulatory" in tags


class TestExtractAll:
    def test_full_extraction(self):
        text = """
        This affidavit is filed before CERC in P.N. 186 of 2026.
        Matter: MWSP_PROJ000031537
        On behalf of Avaada Energy Pvt. Ltd.
        The force majeure clause in the PPA is applicable.
        """
        result = extract_all("Affidavit - Test.pdf", text)
        assert result["document_type"] == "Affidavit"
        assert result["forum"] == "CERC"
        assert result["matter_id"] == "MWSP_PROJ000031537"
        assert result["client_name"] == "Avaada Energy Pvt. Ltd."
        assert "Force Majeure" in result["tags"]
        assert "PPA" in result["tags"]
        assert result["case_number"] is not None

    def test_minimal_extraction(self):
        result = extract_all("random.pdf", "nothing here")
        assert result["document_type"] == "Legal Document"
        assert result["forum"] is None
        assert result["matter_id"] is None
        assert result["client_name"] is None
        assert result["tags"] == []


class TestExtractWithOverrides:
    def test_override_merges(self, monkeypatch):
        """Override values take precedence over auto-extracted."""
        monkeypatch.setattr(
            "metadata_extractor.load_overrides",
            lambda: {"test.pdf": {"matter_id": "OVERRIDE-123", "tags": ["Custom"]}},
        )
        result = extract_with_overrides("test.pdf", "some text")
        assert result["matter_id"] == "OVERRIDE-123"
        assert result["tags"] == ["Custom"]

    def test_no_override_uses_auto(self, monkeypatch):
        monkeypatch.setattr("metadata_extractor.load_overrides", lambda: {})
        result = extract_with_overrides("Affidavit - Test.pdf", "filed before CERC")
        assert result["document_type"] == "Affidavit"
        assert result["forum"] == "CERC"
