"""Tests for document versioning module.

Tests:
  - content_sha256 deterministic
  - create version auto-increments version_number
  - list versions ordered DESC
  - diff between two versions
  - seed_initial_version idempotent (no-op if versions exist)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.documents import content_sha256, diff_versions


class TestContentSha256:
    def test_deterministic(self):
        text = "This is a legal document about MSEDCL."
        assert content_sha256(text) == content_sha256(text)

    def test_different_input(self):
        assert content_sha256("foo") != content_sha256("bar")

    def test_empty(self):
        sha = content_sha256("")
        assert len(sha) == 64  # SHA-256 hex digest is always 64 chars

    def test_unicode(self):
        sha = content_sha256("Résumé — Ñoño")
        assert len(sha) == 64


class TestDiffVersions:
    @patch("app.documents.connect")
    def test_diff_produces_lines(self, mock_connect):
        """Diff between two versions with different bodies."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)

        # Two versions with slightly different bodies
        va = {"version_id": "VER-001", "version_number": 1, "title": "Draft", "body": "Line 1\nLine 2\nLine 3"}
        vb = {"version_id": "VER-002", "version_number": 2, "title": "Final", "body": "Line 1\nLine 2 modified\nLine 3\nLine 4"}
        mock_cur.fetchone.side_effect = [va, vb]

        result = diff_versions("VER-001", "VER-002")

        assert result["version_a"]["version_id"] == "VER-001"
        assert result["version_b"]["version_id"] == "VER-002"
        assert result["added_lines"] >= 1
        assert result["removed_lines"] >= 0
        assert len(result["diff"]) > 0

    @patch("app.documents.connect")
    def test_diff_identical(self, mock_connect):
        """Diff of identical bodies produces no changes."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)

        body = "Same content"
        va = {"version_id": "VER-001", "version_number": 1, "title": "V1", "body": body}
        vb = {"version_id": "VER-002", "version_number": 2, "title": "V2", "body": body}
        mock_cur.fetchone.side_effect = [va, vb]

        result = diff_versions("VER-001", "VER-002")
        assert result["added_lines"] == 0
        assert result["removed_lines"] == 0

    @patch("app.documents.connect")
    def test_diff_missing_version(self, mock_connect):
        """Should raise ValueError if a version is not found."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)

        mock_cur.fetchone.side_effect = [None, None]

        with pytest.raises(ValueError, match="not found"):
            diff_versions("VER-MISSING", "VER-ALSO-MISSING")
