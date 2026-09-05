"""Tests for FirmOS domain models + local object store + upload batch."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.domain import Document, DocumentVersion, Evidence, Finding, Tenant, UploadBatch
from app.storage.object_store import (
    LocalObjectStore,
    build_storage_key,
    content_sha256_bytes,
    reset_object_store_for_tests,
)


class TestDomainModels:
    def test_hierarchy_fields(self):
        t = Tenant(tenant_id="harbour", name="Harbour")
        d = Document(
            document_id="DOC-1",
            matter_id="MTR-1",
            name="SPA.pdf",
            document_type="spa",
            folder_path="Client/Matter/Agreements",
        )
        v = DocumentVersion(
            version_id="VER-1",
            document_id=d.document_id,
            version_number=1,
            content_hash="abc",
            storage_uri="file:///tmp/x",
            is_current=True,
        )
        assert t.tenant_id == "harbour"
        assert d.folder_path.startswith("Client/")
        assert v.is_current

    def test_finding_evidence_no_bbox_required(self):
        ev = Evidence(
            version_id="VER-1",
            block_id="BLK-1",
            quote="$75,000",
            start_offset=0,
            end_offset=7,
            text_hash=content_sha256_bytes(b"$75,000"),
        )
        f = Finding(
            finding_id="FND-1",
            document_id="DOC-1",
            version_id="VER-1",
            category="liability",
            title="Cap",
            explanation="Cap present",
            evidence=[ev],
        )
        assert ev.bbox is None
        assert f.evidence[0].quote == "$75,000"


class TestObjectStore:
    def test_local_put_get_exists(self, tmp_path: Path):
        reset_object_store_for_tests()
        store = LocalObjectStore(tmp_path)
        key = build_storage_key(
            tenant_id="harbour",
            client_id="CLI-1",
            matter_id="MTR-1",
            document_id="DOC-1",
            version_number=2,
            filename="SPA.pdf",
        )
        assert key.endswith("versions/v002/original.pdf")
        uri = store.put(key, b"%PDF-demo", content_type="application/pdf")
        assert uri.startswith("file://")
        assert store.exists(uri)
        assert store.get(uri) == b"%PDF-demo"
        store.delete(uri)
        assert not store.exists(uri)


@pytest.fixture
def object_store_env(tmp_path: Path, monkeypatch):
    reset_object_store_for_tests()
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "local")
    monkeypatch.setenv("OBJECT_STORE_ROOT", str(tmp_path / "objects"))
    # Force settings reload fields used by get_object_store
    from app.config import settings

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_root", str(tmp_path / "objects"))
    yield tmp_path / "objects"
    reset_object_store_for_tests()


class TestUploadBatchDB:
    def test_create_and_process_preserves_folder_path(self, object_store_env):
        from app.db.connection import connect
        from app.ingest.upload_batch import create_upload_batch, process_upload_batch
        from app.documents.canonical import get_version_blocks

        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT matter_id, client_id FROM matters LIMIT 1")
                row = cur.fetchone()
        if not row:
            pytest.skip("no matters in DB")
        matter_id = row["matter_id"] if isinstance(row, dict) else row[0]

        uniq = os.urandom(3).hex()
        files = [
            (f"Transaction Documents/Agreements/SPA_{uniq}.txt", f"SECTION 8.2 Liability {uniq} shall not exceed $50,000.\n".encode()),
            (f"Transaction Documents/Schedules/Schedule_{uniq}.txt", f"Schedule disclosures {uniq}.\n".encode()),
            (f"Transaction Documents/Agreements/notes_{uniq}.txt", f"ARTICLE I Definitions {uniq}\n\nBuyer means the purchasing party.\n".encode()),
        ]
        batch = create_upload_batch(matter_id=matter_id, files=files)
        assert batch["total_files"] == 3
        assert all(f["storage_uri"].startswith("file://") for f in batch["files"])
        rels = {f["relative_path"] for f in batch["files"]}
        assert any(r.endswith(f"SPA_{uniq}.txt") for r in rels)

        result = process_upload_batch(batch["batch_id"])
        assert result["failed"] == 0
        assert result["indexed"] == 3

        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT d.document_id, d.folder_path, d.current_version_id, v.storage_uri
                    FROM documents d
                    JOIN document_versions v ON v.version_id = d.current_version_id
                    WHERE d.matter_id = %(mid)s AND d.title = %(title)s
                    LIMIT 1
                    """,
                    {"mid": matter_id, "title": f"SPA_{uniq}.txt"},
                )
                doc = cur.fetchone()
        assert doc is not None
        folder_path = doc["folder_path"] if isinstance(doc, dict) else doc[1]
        version_id = doc["current_version_id"] if isinstance(doc, dict) else doc[2]
        storage_uri = doc["storage_uri"] if isinstance(doc, dict) else doc[3]
        assert "Agreements" in (folder_path or "")
        assert storage_uri
        blocks = get_version_blocks(version_id)
        assert len(blocks) >= 1

    def test_one_failure_does_not_fail_batch(self, object_store_env, monkeypatch):
        from app.db.connection import connect
        from app.ingest import upload_batch as ub

        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT matter_id FROM matters LIMIT 1")
                row = cur.fetchone()
        if not row:
            pytest.skip("no matters in DB")
        matter_id = row["matter_id"] if isinstance(row, dict) else row[0]

        uniq = os.urandom(3).hex()
        files = [
            (f"Good/doc_{uniq}.txt", f"Good document text about indemnity {uniq}.\n".encode()),
            (f"Bad/fail_{uniq}.txt", f"will fail {uniq}".encode()),
        ]
        batch = ub.create_upload_batch(matter_id=matter_id, files=files)

        original = ub._extract_document

        def flaky(filename: str, data: bytes):
            if "fail_" in filename:
                raise RuntimeError("simulated extract failure")
            return original(filename, data)

        monkeypatch.setattr(ub, "_extract_document", flaky)
        result = ub.process_upload_batch(batch["batch_id"])
        assert result["indexed"] == 1
        assert result["failed"] == 1
        assert result["status"] == "completed_with_errors"