"""Shared test fixtures for doc-search tests."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure doc-search modules are importable
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def mock_conn():
    """Mock psycopg connection that returns empty results."""
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = []
    return conn


@pytest.fixture
def sample_hits():
    """Sample retrieval hits with metadata for testing."""
    return [
        {
            "chunk_id": "abc123_00001",
            "filename": "Affidavit - CA 10046 of 2025.pdf",
            "page_number": 1,
            "text": "The petitioner respectfully submits this affidavit in support of the Civil Appeal.",
            "matter_id": "MWSP_PROJ000031537",
            "document_type": "Affidavit",
            "tags": ["Affidavit", "Civil Appeal"],
            "channel": "keyword",
            "fused_score": 0.8,
        },
        {
            "chunk_id": "def456_00002",
            "filename": "WRITTEN SUBMISSION IN PETITION NO. 22 OF 2026 (VECTOR GREEN) 01.08.2026.pdf",
            "page_number": 3,
            "text": "Vector Green Energy Pvt. Ltd. submits that the tariff determination by CERC is erroneous.",
            "matter_id": None,
            "document_type": "Written Submission",
            "tags": ["Regulatory", "Tariff"],
            "channel": "vector",
            "fused_score": 0.6,
        },
        {
            "chunk_id": "ghi789_00003",
            "filename": "MSEDCL Note in APL. 163 of 2018.pdf",
            "page_number": 2,
            "text": "MSEDCL hereby submits its note on the issues raised in the appeal.",
            "matter_id": None,
            "document_type": "Brief Note",
            "tags": ["MSEDCL", "Regulatory"],
            "channel": "keyword",
            "fused_score": 0.4,
        },
    ]


@pytest.fixture
def empty_hits():
    """Empty hit list for abstention tests."""
    return []


@pytest.fixture
def single_hit():
    """Single hit for edge case tests."""
    return [
        {
            "chunk_id": "single_00001",
            "filename": "Final Reply (310-MP-2026).pdf",
            "page_number": 5,
            "text": "The respondent denies all allegations made in the petition.",
            "matter_id": None,
            "document_type": "Final Reply",
            "tags": ["Regulatory"],
            "channel": "vector",
            "fused_score": 0.9,
        },
    ]
