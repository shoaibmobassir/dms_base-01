"""Tests for llm.py — LLM parsing, context packing, extractive fallback.

Tests:
  - _parse_raw() with valid JSON, markdown fences, invalid JSON, abstain flag
  - _extractive_answer() with hits and empty hits
  - _pack_context() formatting with and without metadata
  - DMS-style output fields: key_finding, primary_document, supporting_documents
"""
from llm import _parse_raw, _extractive_answer, _pack_context


class TestParseRaw:
    def test_valid_json(self):
        raw = '{"abstain": false, "answer": "The court held X.", "key_finding": "X was decided.", "citations": [{"file": "doc.pdf", "page": 1, "snippet": "held X"}]}'
        result = _parse_raw(raw)
        assert result is not None
        assert result["abstain"] is False
        assert result["answer"] == "The court held X."
        assert result["key_finding"] == "X was decided."
        assert len(result["citations"]) == 1

    def test_markdown_fences_stripped(self):
        raw = '```json\n{"abstain": false, "answer": "test", "citations": []}\n```'
        result = _parse_raw(raw)
        assert result is not None
        assert result["answer"] == "test"

    def test_markdown_fences_no_lang(self):
        raw = '```\n{"abstain": true, "answer": "", "citations": []}\n```'
        result = _parse_raw(raw)
        assert result is not None
        assert result["abstain"] is True

    def test_invalid_json_returns_none(self):
        assert _parse_raw("not json at all") is None
        assert _parse_raw("{broken json") is None
        assert _parse_raw("") is None
        assert _parse_raw(None) is None

    def test_abstain_true(self):
        raw = '{"abstain": true, "answer": "", "citations": []}'
        result = _parse_raw(raw)
        assert result is not None
        assert result["abstain"] is True
        assert result["answer"] == ""

    def test_missing_fields_default(self):
        raw = '{"answer": "hello"}'
        result = _parse_raw(raw)
        assert result is not None
        assert result["abstain"] is False
        assert result["citations"] == []
        assert result["key_finding"] == ""

    def test_primary_document_parsed(self):
        raw = '{"abstain": false, "answer": "test", "primary_document": {"filename": "doc.pdf", "page": 1}, "citations": []}'
        result = _parse_raw(raw)
        assert result is not None
        assert result["primary_document"]["filename"] == "doc.pdf"

    def test_supporting_documents_parsed(self):
        raw = '{"abstain": false, "answer": "test", "supporting_documents": [{"filename": "a.pdf", "page": 2}], "citations": []}'
        result = _parse_raw(raw)
        assert result is not None
        assert len(result["supporting_documents"]) == 1


class TestExtractiveAnswer:
    def test_with_hits(self, sample_hits):
        result = _extractive_answer(sample_hits)
        assert result["abstain"] is False
        assert "answer" in result
        assert "primary_document" in result
        assert result["primary_document"]["filename"] == sample_hits[0]["filename"]
        assert len(result["supporting_documents"]) > 0
        assert len(result["citations"]) > 0

    def test_with_empty_hits(self, empty_hits):
        result = _extractive_answer(empty_hits)
        assert result["abstain"] is False
        assert result["primary_document"] is None
        assert result["supporting_documents"] == []

    def test_primary_doc_has_metadata(self, sample_hits):
        result = _extractive_answer(sample_hits)
        primary = result["primary_document"]
        assert primary is not None
        assert "matter_id" in primary
        assert "document_type" in primary
        assert "tags" in primary
        assert primary["document_type"] == "Affidavit"
        assert primary["matter_id"] == "MWSP_PROJ000031537"

    def test_key_finding_present(self, sample_hits):
        result = _extractive_answer(sample_hits)
        assert result["key_finding"]
        assert "relevant" in result["key_finding"].lower() or "found" in result["key_finding"].lower()

    def test_citations_from_hits_only(self, sample_hits):
        result = _extractive_answer(sample_hits)
        hit_files = {h["filename"] for h in sample_hits}
        for cite in result["citations"]:
            assert cite["file"] in hit_files


class TestPackContext:
    def test_basic_formatting(self, sample_hits):
        context = _pack_context(sample_hits)
        assert "[1]" in context
        assert sample_hits[0]["filename"] in context
        assert "---" in context  # separator

    def test_includes_metadata(self, sample_hits):
        context = _pack_context(sample_hits)
        assert "Type: Affidavit" in context
        assert "Matter: MWSP_PROJ000031537" in context
        assert "Tags:" in context

    def test_metadata_absent_when_none(self):
        hits = [{"filename": "test.pdf", "page_number": 1, "text": "hello"}]
        context = _pack_context(hits)
        assert "Type:" not in context
        assert "Matter:" not in context

    def test_text_truncation(self):
        hits = [{
            "filename": "test.pdf",
            "page_number": 1,
            "text": "x" * 5000,
        }]
        context = _pack_context(hits)
        # Text should be truncated to 1200 chars
        assert len(context) < 5000

    def test_empty_hits(self):
        context = _pack_context([])
        assert context == ""
