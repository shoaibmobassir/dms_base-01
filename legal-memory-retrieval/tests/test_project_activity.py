"""Tests for project activity recording.

Tests:
  - record_activity with cursor
  - record_activity standalone (creates own connection)
  - metadata serialization
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestRecordActivity:
    def test_with_cursor(self):
        """record_activity with an existing cursor executes SQL."""
        from app.projects import record_activity

        mock_cur = MagicMock()
        record_activity(
            "PRJ-001", "document.added",
            actor_id="MEM-001",
            target_id="DOC-001",
            target_title="Test Doc",
            metadata={"source": "upload"},
            cur=mock_cur,
        )
        mock_cur.execute.assert_called_once()
        args = mock_cur.execute.call_args
        sql = args[0][0]
        params = args[0][1]
        assert "INSERT INTO project_activity" in sql
        assert params["project_id"] == "PRJ-001"
        assert params["action"] == "document.added"
        assert params["actor_id"] == "MEM-001"
        assert '"source": "upload"' in params["metadata"]

    def test_with_conn(self):
        """record_activity with a connection creates its own cursor."""
        from app.projects import record_activity

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        record_activity(
            "PRJ-001", "milestone.toggled",
            actor_id="MEM-002",
            conn=mock_conn,
        )
        mock_cur.execute.assert_called_once()

    @patch("app.projects.connect")
    def test_standalone(self, mock_connect):
        """record_activity without conn/cur creates its own connection."""
        from app.projects import record_activity as record_act

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        record_act("PRJ-001", "folder.created")
        mock_cur.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_empty_metadata(self):
        """None metadata should serialize as '{}'."""
        from app.projects import record_activity

        mock_cur = MagicMock()
        record_activity("PRJ-001", "project.created", cur=mock_cur)

        params = mock_cur.execute.call_args[0][1]
        assert params["metadata"] == "{}"
