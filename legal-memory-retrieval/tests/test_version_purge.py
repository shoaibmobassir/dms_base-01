"""Deleting a version's content for good (plan 22, W-R8): the row stays in the history as "deleted", the content,
file, index and comments are gone, and nothing can reopen, compare, download or restore it."""
from __future__ import annotations

import pytest

from app.db.connection import connect
from app.storage.object_store import get_object_store
from tests.conftest import as_member
from tests.test_document_editor import _model, _save, doc, people  # noqa: F401  (fixtures)

OPS = [{"op": "replace", "pid": 2, "text": "The Supplier shall deliver the Services on a best-efforts basis."}]


@pytest.fixture
def lead(people):
    with connect() as conn:
        row = conn.execute("SELECT member_id FROM matter_members WHERE matter_id = %s AND lower(role_on_matter) = 'lead' "
                           "AND (ended_at IS NULL OR ended_at >= current_date) LIMIT 1", (people["matter_id"],)).fetchone()
    if not row:
        pytest.skip("the test matter has no lead")
    return row["member_id"]


def _v1_and_v2(client, doc, people):
    first = _model(client, doc, people["editor"])["base_version_id"]
    second = _save(client, doc, people["editor"], first, OPS, note="tighten delivery").json()["version_id"]
    return first, second


def test_purge_removes_content_but_keeps_the_history_entry(client, doc, people, lead):
    first, second = _v1_and_v2(client, doc, people)
    with connect() as conn:
        uri = conn.execute("SELECT storage_uri FROM document_versions WHERE version_id = %s", (first,)).fetchone()["storage_uri"]
        conn.execute("INSERT INTO annotations (annotation_id, document_id, version_id, annotation_type, start_offset, "
                     "end_offset, quoted_text, text_hash) VALUES ('ANN-PURGE-T', %s, %s, 'comment', 0, 5, 'quotes the "
                     "old text', 'x')", (doc, first))
        conn.commit()
    assert get_object_store().exists(uri)

    r = client.post(f"/api/editor/documents/{doc}/versions/{first}/purge", json={"reason": "client asked for removal"},
                    headers=as_member(lead))
    assert r.status_code == 200, r.text
    assert r.json()["files_removed"] == 1
    assert not get_object_store().exists(uri)

    with connect() as conn:
        v = conn.execute("SELECT body, storage_uri, deleted_at, deleted_by, delete_reason FROM document_versions "
                         "WHERE version_id = %s", (first,)).fetchone()
        left = conn.execute("""SELECT (SELECT count(*) FROM document_blocks WHERE version_id = %(v)s)
                                    + (SELECT count(*) FROM annotations WHERE version_id = %(v)s)
                                    + (SELECT count(*) FROM chunks WHERE version_id = %(v)s) AS n""", {"v": first}).fetchone()
        src = conn.execute("SELECT source_uri FROM documents WHERE document_id = %s", (doc,)).fetchone()["source_uri"]
    assert v["body"] == "" and v["storage_uri"] is None and v["deleted_by"] == lead
    assert v["delete_reason"] == "client asked for removal" and left["n"] == 0
    assert src != uri

    items = client.get(f"/api/editor/documents/{doc}/commits", headers=as_member(people["editor"])).json()["items"]
    gone = next(i for i in items if i["version_id"] == first)
    assert gone["deleted"] and gone["delete_reason"] == "client asked for removal"


def test_a_deleted_version_cannot_be_opened_compared_downloaded_or_restored(client, doc, people, lead):
    first, second = _v1_and_v2(client, doc, people)
    assert client.post(f"/api/editor/documents/{doc}/versions/{first}/purge", json={"reason": "duplicate upload"},
                       headers=as_member(lead)).status_code == 200
    h = as_member(people["editor"])
    assert client.get(f"/api/editor/documents/{doc}/compare", params={"from": first, "to": second}, headers=h).status_code == 410
    assert client.get(f"/api/documents/{doc}/download", params={"version_id": first}, headers=h).status_code == 410
    r = client.post(f"/api/editor/documents/{doc}/restore", headers=h, json={"version_id": first, "base_version_id": second})
    assert r.status_code == 410
    # the current version is untouched
    assert client.get(f"/api/documents/{doc}/download", headers=h).status_code == 200
    blame = client.get(f"/api/editor/documents/{doc}/blame", headers=h).json()
    assert {p["version_id"] for p in blame["paragraphs"]} == {second}


def test_only_managers_purge_never_the_current_version_and_a_reason_is_required(client, doc, people, lead):
    first, second = _v1_and_v2(client, doc, people)
    url = f"/api/editor/documents/{doc}/versions/{first}/purge"
    assert client.post(url, json={"reason": "please remove"}, headers=as_member(people["editor"])).status_code == 403
    assert client.post(url, json={"reason": "please remove"}, headers=as_member(people["outsider"])).status_code in (403, 404)
    assert client.post(url, json={"reason": ""}, headers=as_member(lead)).status_code == 422
    r = client.post(f"/api/editor/documents/{doc}/versions/{second}/purge", json={"reason": "please remove"},
                    headers=as_member(lead))
    assert r.status_code == 409
    assert client.post(url, json={"reason": "please remove"}, headers=as_member(lead)).status_code == 200
    assert client.post(url, json={"reason": "again"}, headers=as_member(lead)).status_code == 409


def test_bytes_shared_with_another_version_stay(client, doc, people, lead):
    """A restore re-uses the old file; purging the old version must not delete what the restore still shows."""
    first, second = _v1_and_v2(client, doc, people)
    r = client.post(f"/api/editor/documents/{doc}/restore", headers=as_member(people["editor"]),
                    json={"version_id": first, "base_version_id": second})
    assert r.status_code == 201, r.text
    with connect() as conn:
        uri = conn.execute("SELECT storage_uri FROM document_versions WHERE version_id = %s", (first,)).fetchone()["storage_uri"]
        third_uri = conn.execute("SELECT storage_uri FROM document_versions WHERE version_id = %s",
                                 (r.json()["version_id"],)).fetchone()["storage_uri"]
    out = client.post(f"/api/editor/documents/{doc}/versions/{first}/purge", json={"reason": "tidy up"},
                      headers=as_member(lead)).json()
    if third_uri == uri:
        assert out["files_removed"] == 0 and get_object_store().exists(uri)
    assert client.get(f"/api/documents/{doc}/download", headers=as_member(people["editor"])).status_code == 200


def test_copy_from_another_document_is_a_new_version_and_leaves_the_source_alone(client, doc, people):
    from app.storage.object_store import get_object_store as store
    import uuid as _uuid

    other = f"DOC-{_uuid.uuid4().hex[:10].upper()}"
    with connect() as conn:
        conn.execute("""INSERT INTO documents (document_id, matter_id, client_id, title, document_type, body)
                        VALUES (%s, %s, %s, 'Other memo.txt', 'Memo', 'Replacement text of the other memo.')""",
                     (other, people["matter_id"], people["client_id"]))
        conn.commit()
    from app.documents import create_version

    create_version(document_id=other, body="Replacement text of the other memo.", title="Other memo.txt")
    try:
        h = as_member(people["editor"])
        base = _model(client, doc, people["editor"])["base_version_id"]
        r = client.post(f"/api/editor/documents/{doc}/versions/copy-from", headers=h,
                        json={"source_document_id": other, "base_version_id": base})
        assert r.status_code == 201, r.text
        out = r.json()
        assert out["version_number"] == 2 and out["source"]["unchanged"]
        items = client.get(f"/api/editor/documents/{doc}/commits", headers=h).json()["items"]
        assert items[0]["kind"] == "copy" and "Other memo" in items[0]["message"]
        with connect() as conn:
            assert "Replacement text" in conn.execute("SELECT body FROM documents WHERE document_id = %s", (doc,)).fetchone()["body"]
            assert conn.execute("SELECT count(*) AS n FROM document_versions WHERE document_id = %s", (other,)).fetchone()["n"] == 1
        # someone who cannot read the source cannot copy from it
        r = client.post(f"/api/editor/documents/{doc}/versions/copy-from", headers=as_member(people["outsider"]),
                        json={"source_document_id": other})
        assert r.status_code in (403, 404)
    finally:
        with connect() as conn, conn.transaction():
            from app.ingest.purge import purge_documents

            purge_documents(conn, [other])
        _ = store
