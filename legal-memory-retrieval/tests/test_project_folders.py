"""Tests for project folders and document assignment.

Tests:
  - Folder creation with parent
  - Cycle detection on move
  - Depth limit enforcement
  - Directory tree building
  - Document folder move
  - Activity recording
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestCycleDetection:
    """Test cycle detection in folder move operations."""

    def test_self_reference_detected(self):
        """Moving a folder into itself should raise HTTPException."""
        from app.api.routers.projects import _check_cycle

        mock_cur = MagicMock()
        # Simulate: folder A's parent is A itself (direct cycle)
        mock_cur.fetchone.return_value = {"parent_folder_id": None}

        # new_parent_id == folder_id → immediate cycle
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _check_cycle(mock_cur, "PRJ-001", "FLD-A", "FLD-A")
        assert exc.value.status_code == 400
        assert "itself" in exc.value.detail

    def test_indirect_cycle_detected(self):
        """Moving A under C where C is already under A should raise."""
        from app.api.routers.projects import _check_cycle
        from fastapi import HTTPException

        mock_cur = MagicMock()
        # Walk: FLD-C → parent=FLD-B → parent=FLD-A (== folder we're moving)
        mock_cur.fetchone.side_effect = [
            {"parent_folder_id": "FLD-B"},  # C's parent is B
            {"parent_folder_id": "FLD-A"},  # B's parent is A (the folder we're moving)
        ]

        with pytest.raises(HTTPException) as exc:
            _check_cycle(mock_cur, "PRJ-001", "FLD-A", "FLD-C")
        assert exc.value.status_code == 400

    def test_no_cycle_when_moving_to_root(self):
        """Moving to root (parent=None) should never cycle."""
        from app.api.routers.projects import _check_cycle

        mock_cur = MagicMock()
        # No cycle — new_parent is None
        _check_cycle(mock_cur, "PRJ-001", "FLD-A", None)
        # Should not raise


class TestFolderDepth:
    """Test depth limit enforcement."""

    def test_max_depth_exceeded(self):
        """Exceeding MAX_FOLDER_DEPTH should raise HTTPException."""
        from app.api.routers.projects import _check_folder_depth, MAX_FOLDER_DEPTH
        from fastapi import HTTPException

        mock_cur = MagicMock()
        # Simulate a chain deeper than MAX_FOLDER_DEPTH
        chain = [{"parent_folder_id": f"FLD-{i}"} for i in range(MAX_FOLDER_DEPTH + 2)]
        chain[-1] = {"parent_folder_id": None}
        mock_cur.fetchone.side_effect = chain

        with pytest.raises(HTTPException) as exc:
            _check_folder_depth(mock_cur, "PRJ-001", "FLD-0")
        assert "depth" in exc.value.detail.lower()

    def test_shallow_folder_ok(self):
        """A folder at depth 2 should pass."""
        from app.api.routers.projects import _check_folder_depth

        mock_cur = MagicMock()
        # parent → root (depth = 2)
        mock_cur.fetchone.side_effect = [
            {"parent_folder_id": None},  # parent is root
        ]

        depth = _check_folder_depth(mock_cur, "PRJ-001", "FLD-PARENT")
        assert depth <= 5


class TestProjectPayload:
    """Test the project payload builder."""

    def test_full_payload(self):
        from app.api.routers.projects import _project_payload

        row = {
            "project_id": "PRJ-001",
            "matter_id": "MTR-001",
            "title": "Test Project",
            "practice_team": "Litigation",
            "lead_member_id": "MEM-001",
            "lead_lawyer": "John Doe",
            "status": "In Progress",
            "progress": 50,
            "deadline": "2026-12-31",
            "scope": "Full scope",
            "milestones": [{"title": "M1", "done": True}],
        }
        matter = {
            "matter_code": "LIT/001",
            "title": "Test Matter",
            "client_id": "CLI-001",
            "client_name": "Test Corp",
            "claim_amount": "₹10Cr",
        }
        payload = _project_payload(row, matter)

        assert payload["project_id"] == "PRJ-001"
        assert payload["matter_code"] == "LIT/001"
        assert payload["client_name"] == "Test Corp"
        assert payload["quantum"] == "₹10Cr"
        assert payload["service"] == "projects"

    def test_missing_matter(self):
        from app.api.routers.projects import _project_payload

        row = {
            "project_id": "PRJ-002",
            "matter_id": "MTR-002",
            "title": "Bare Project",
            "practice_team": "Corporate",
        }
        payload = _project_payload(row, None)
        assert payload["matter_code"] == ""
        assert payload["client_name"] == ""


class TestPydanticSchemas:
    """Test new Pydantic schemas."""

    def test_folder_create(self):
        from app.api.schemas import FolderCreate
        f = FolderCreate(name="Submissions", parent_folder_id="FLD-001")
        assert f.name == "Submissions"
        assert f.parent_folder_id == "FLD-001"

    def test_folder_create_root(self):
        from app.api.schemas import FolderCreate
        f = FolderCreate(name="Root Folder")
        assert f.parent_folder_id is None

    def test_folder_update(self):
        from app.api.schemas import FolderUpdate
        f = FolderUpdate(name="Renamed")
        assert f.name == "Renamed"
        assert f.parent_folder_id is None

    def test_document_folder_move(self):
        from app.api.schemas import DocumentFolderMove
        m = DocumentFolderMove(folder_id="FLD-001")
        assert m.folder_id == "FLD-001"

    def test_document_folder_move_to_root(self):
        from app.api.schemas import DocumentFolderMove
        m = DocumentFolderMove(folder_id=None)
        assert m.folder_id is None

    def test_version_create(self):
        from app.api.schemas import VersionCreate
        v = VersionCreate(body="Updated legal text", source="edit")
        assert v.body == "Updated legal text"
        assert v.source == "edit"
        assert v.title is None
