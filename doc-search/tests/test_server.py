"""Tests for server.py — API endpoint validation.

Tests:
  - POST /ask with valid query → 200, DMS-style response fields present
  - POST /ask with empty query → handles gracefully
  - GET /health → 200, {"status": "ok"}
  - GET /doc/serve path traversal → 400
  - GET /doc/serve nonexistent → 404
  - Response contains matter_id, tags, document_type, key_finding, primary_document
  - Latency breakdown is present
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a TestClient with mocked retrieval and LLM."""
    with patch("server.retrieve") as mock_retrieve, \
         patch("server.complete") as mock_complete, \
         patch("server.psycopg") as mock_psycopg:

        # Mock DB connection
        mock_conn = MagicMock()
        mock_psycopg.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_psycopg.connect.return_value.__exit__ = MagicMock(return_value=False)

        # Mock retrieve to return sample hits with latency
        mock_retrieve.return_value = (
            [
                {
                    "chunk_id": "abc_00001",
                    "filename": "test_doc.pdf",
                    "page_number": 1,
                    "text": "Sample legal text about force majeure.",
                    "matter_id": "MWSP_PROJ000031537",
                    "document_type": "Affidavit",
                    "tags": ["Force Majeure", "Regulatory"],
                    "rerank_score": 0.85,
                    "channel": "keyword",
                },
            ],
            {"keyword_ms": 10.0, "vector_ms": 15.0, "parallel_search_ms": 16.0, "total_ms": 20.0},
        )

        # Mock complete to return DMS-style answer
        mock_complete.return_value = {
            "abstain": False,
            "key_finding": "Documents reference force majeure in energy contracts.",
            "answer": "The petitioner invoked force majeure [test_doc.pdf, p.1]",
            "primary_document": {
                "filename": "test_doc.pdf",
                "page": 1,
                "matter_id": "MWSP_PROJ000031537",
                "document_type": "Affidavit",
                "tags": ["Force Majeure"],
                "snippet": "Sample legal text about force majeure.",
            },
            "supporting_documents": [],
            "citations": [{"file": "test_doc.pdf", "page": 1, "snippet": "force majeure"}],
            "provider": "groq",
        }

        from server import app
        yield TestClient(app)


class TestAskEndpoint:
    def test_valid_query_returns_200(self, client):
        resp = client.post("/ask", json={"query": "What is force majeure?"})
        assert resp.status_code == 200

    def test_response_has_dms_fields(self, client):
        resp = client.post("/ask", json={"query": "What is force majeure?"})
        data = resp.json()
        assert "answer" in data
        assert "key_finding" in data
        assert "primary_document" in data
        assert "supporting_documents" in data
        assert "citations" in data
        assert "hits" in data
        assert "latency_ms" in data

    def test_primary_document_has_metadata(self, client):
        resp = client.post("/ask", json={"query": "What is force majeure?"})
        data = resp.json()
        primary = data["primary_document"]
        assert primary is not None
        assert "matter_id" in primary
        assert "document_type" in primary
        assert "tags" in primary
        assert "open_document_url" in primary

    def test_hits_have_metadata(self, client):
        resp = client.post("/ask", json={"query": "What is force majeure?"})
        data = resp.json()
        for hit in data["hits"]:
            assert "matter_id" in hit
            assert "document_type" in hit
            assert "tags" in hit

    def test_latency_breakdown_present(self, client):
        resp = client.post("/ask", json={"query": "test"})
        data = resp.json()
        latency = data["latency_ms"]
        assert "keyword_ms" in latency
        assert "vector_ms" in latency
        assert "llm_ms" in latency
        assert "total_ms" in latency

    def test_provider_returned(self, client):
        resp = client.post("/ask", json={"query": "test"})
        data = resp.json()
        assert data["provider"] == "groq"


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        from server import app
        with TestClient(app) as tc:
            resp = tc.get("/health")
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "ok"
            assert body["parallel_retrieval"] is True
            assert "keyword" in body["channels"]


class TestDebugAndDocs:
    def test_debug_endpoint(self, client):
        resp = client.post("/debug", json={"query": "force majeure", "k": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "doc-search-debug"
        assert "channel_counts" in data
        assert "latency_ms" in data
        assert len(data["hits"]) >= 1

    def test_architecture_markdown(self):
        from server import app
        with TestClient(app) as tc:
            resp = tc.get("/architecture")
            assert resp.status_code == 200
            assert "Doc Search" in resp.text or "LEXOS" in resp.text

    def test_docs_ui(self):
        from server import app
        with TestClient(app) as tc:
            resp = tc.get("/docs-ui")
            assert resp.status_code == 200
            assert "Architecture" in resp.text


class TestDocServeEndpoint:
    def test_path_traversal_blocked(self):
        from server import app
        with TestClient(app) as tc:
            resp = tc.get("/doc/serve/../../etc/passwd")
            # Framework may normalize to 404; our handler returns 400 for ".."
            assert resp.status_code in (400, 404)

    def test_absolute_path_blocked(self):
        from server import app
        with TestClient(app) as tc:
            resp = tc.get("/doc/serve//etc/passwd")
            assert resp.status_code == 400

    def test_nonexistent_file_returns_404(self):
        from server import app
        with TestClient(app) as tc:
            resp = tc.get("/doc/serve/nonexistent_document.pdf")
            assert resp.status_code == 404

    def test_non_pdf_returns_404(self):
        from server import app
        with TestClient(app) as tc:
            resp = tc.get("/doc/serve/malicious.exe")
            assert resp.status_code == 404


class TestAskEdgeCases:
    def test_empty_query(self, client):
        """Empty query should not crash, may abstain."""
        resp = client.post("/ask", json={"query": ""})
        assert resp.status_code == 200

    def test_custom_k(self, client):
        """Custom k parameter should be accepted."""
        resp = client.post("/ask", json={"query": "test", "k": 3})
        assert resp.status_code == 200

    def test_large_k(self, client):
        """Large k should not crash."""
        resp = client.post("/ask", json={"query": "test", "k": 100})
        assert resp.status_code == 200
