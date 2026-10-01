"""Document workspace lean header, outline, and ranged reads."""

from __future__ import annotations

import pytest

from app.db.connection import connect
from conftest import as_member

ME = as_member("MEM-00016")


pytestmark = pytest.mark.usefixtures("seeded")


@pytest.fixture(scope="module")
def any_document() -> dict:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT d.document_id, d.current_version_id
            FROM documents d
            WHERE EXISTS (SELECT 1 FROM chunks c WHERE c.document_id = d.document_id)
            ORDER BY d.document_id
            LIMIT 1
            """
        ).fetchone()
    if not row:
        pytest.skip("no documents with chunks in seed")
    return dict(row)


def test_document_lean_omits_body_and_chunks(client, any_document):
    doc_id = any_document["document_id"]
    lean = client.get(f"/api/documents/{doc_id}", params={"lean": "true"}, headers=ME)
    assert lean.status_code == 200
    body = lean.json()
    assert body.get("body") in (None, "")
    assert body.get("chunks") == []
    assert body.get("chunk_count", 0) >= 1
    assert "has_original" in body
    assert "current_version_id" in body


def test_document_chunks_range(client, any_document):
    doc_id = any_document["document_id"]
    res = client.get(
        f"/api/documents/{doc_id}/chunks",
        params={"offset": 0, "limit": 2},
        headers=ME,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert len(data["chunks"]) <= 2


def test_version_outline_and_blocks_range(client, any_document):
    doc_id = any_document["document_id"]
    version_id = any_document["current_version_id"]
    if not version_id:
        with connect() as conn:
            row = conn.execute(
                "SELECT version_id FROM document_versions WHERE document_id = %s"
                " ORDER BY version_number DESC LIMIT 1",
                (doc_id,),
            ).fetchone()
        if not row:
            pytest.skip("no versions for document")
        version_id = row["version_id"]

    outline = client.get(
        f"/api/documents/{doc_id}/versions/{version_id}/outline",
        headers=ME,
    )
    assert outline.status_code == 200
    assert "outline" in outline.json()

    blocks = client.get(
        f"/api/documents/{doc_id}/versions/{version_id}/blocks",
        params={"from": 0, "limit": 3},
        headers=ME,
    )
    assert blocks.status_code == 200
    data = blocks.json()
    assert "total" in data
    assert len(data["blocks"]) <= 3
