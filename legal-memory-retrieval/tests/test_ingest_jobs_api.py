"""Tests for ingest job API endpoints."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.main import app

HEADERS = {"X-Member-Id": "MEM-00001"}
ROOT = Path(__file__).resolve().parents[1]


def test_ingest_job_create_and_status() -> None:
    client = TestClient(app)
    docs = str((ROOT.parent / "docs").resolve())
    manifest = str(ROOT / "ingest" / "manifests" / "real_filings.yaml")

    with patch("app.api.ingest_jobs.run_ingest_job") as mock_run:
        mock_run.return_value = {"processed": 0, "status": {"status": "completed"}}
        resp = client.post(
            "/api/documents/ingest/jobs",
            json={
                "source_root": docs,
                "manifest": manifest,
                "workers": 1,
                "run_immediately": False,
            },
            headers=HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "documents"
    assert body["job_id"].startswith("JOB-")
    assert body["total_items"] >= 1

    status_resp = client.get(f"/api/documents/ingest/jobs/{body['job_id']}", headers=HEADERS)
    assert status_resp.status_code == 200
    assert status_resp.json()["job_id"] == body["job_id"]


def test_ingest_job_invalid_source() -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/documents/ingest/jobs",
        json={
            "source_root": "/no/such/path",
            "manifest": str(ROOT / "ingest/manifests/real_filings.yaml"),
            "run_immediately": False,
        },
        headers=HEADERS,
    )
    assert resp.status_code == 400
