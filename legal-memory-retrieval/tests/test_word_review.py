"""Word review through the HTTP API and the real database (plan 18): who changed what,
accept/reject as attributed versions, editing that keeps other reviewers' pending changes,
and comments both ways."""
from __future__ import annotations

import io

from app.db.connection import connect
from app.documents import docx_comments as C
from app.documents import docx_review as R
from tests.conftest import as_member
from tests.test_document_editor import doc, people  # noqa: F401 — fixtures
from tests.word_fixtures import build

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _upload(client, doc_id, member, data=None):
    r = client.post(f"/api/editor/documents/{doc_id}/versions", headers=as_member(member),
                    files={"file": ("reviewed.docx", data or build(), DOCX)})
    assert r.status_code == 201, r.text
    return r.json()


def _review(client, doc_id, member, version_id=None):
    r = client.get(f"/api/editor/documents/{doc_id}/review", params={"version_id": version_id} if version_id else {},
                   headers=as_member(member))
    assert r.status_code == 200, r.text
    return r.json()


def _file(doc_id: str) -> bytes:
    from app.storage.object_store import get_object_store

    with connect() as conn:
        uri = conn.execute("SELECT v.storage_uri FROM documents d JOIN document_versions v ON v.version_id = d.current_version_id "
                           "WHERE d.document_id = %s", (doc_id,)).fetchone()["storage_uri"]
    return get_object_store().get(uri)


def test_review_lists_people_and_changes(client, doc, people):
    _upload(client, doc, people["editor"])
    rv = _review(client, doc, people["editor2"])
    assert rv["word"] and rv["total"] == 7 and rv["can_review"]
    people_rows = {p["author"]: p for p in rv["people"]}
    assert set(people_rows) == {"Ravi Kalra", "Trilegal", "Kunal Lalit Kaistha"}
    assert people_rows["Trilegal"]["deletions"] == 1 and people_rows["Trilegal"]["member_id"] is None  # external
    assert any(c["type"] == "insert" and c["paragraph"] and c["author"] == "Trilegal" for c in rv["changes"])
    # Stored per version for "who worked on it".
    with connect() as conn:
        rows = conn.execute("SELECT author_name FROM document_revision_authors WHERE document_id = %s", (doc,)).fetchall()
    assert {r["author_name"] for r in rows} == {"Ravi Kalra", "Trilegal", "Kunal Lalit Kaistha"}


def test_word_comments_come_in_once(client, doc, people):
    _upload(client, doc, people["editor"])
    listed = client.get(f"/api/editor/documents/{doc}/comments", headers=as_member(people["editor"])).json()
    word = [t for t in listed["threads"] if t["source"] == "word"]
    assert {(t["author"], t["status"]) for t in word} == {("Ravi Kalra", "open"), ("Kunal Lalit Kaistha", "resolved")}
    ravi = next(t for t in word if t["author"] == "Ravi Kalra")
    assert ravi["quote"] == "within 30 days" and [r["author"] for r in ravi["replies"]] == ["Trilegal"]
    # The same file again (or a later version carrying the same comments) adds nothing.
    _upload(client, doc, people["editor"])
    with connect() as conn:
        n = conn.execute("SELECT count(*) AS n FROM annotations WHERE document_id = %s AND source = 'word'", (doc,)).fetchone()["n"]
    assert n == 3


def test_accept_one_persons_changes_as_a_new_version(client, doc, people):
    v = _upload(client, doc, people["editor"])
    h = as_member(people["editor"])
    r = client.post(f"/api/editor/documents/{doc}/review", headers=h,
                    json={"base_version_id": v["version_id"], "action": "accept", "authors": ["Trilegal"]})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["by_author"] == {"Trilegal": 3} and out["note"].startswith("Accepted 3 changes by Trilegal")
    after = _review(client, doc, people["editor"])
    assert {p["author"] for p in after["people"] if p["insertions"] + p["deletions"] + p["formats"] + p["moves"]} == {
        "Ravi Kalra", "Kunal Lalit Kaistha"}
    assert "Governing law is English law." in R.text_view(_file(doc), "original")  # accepted: part of the text now
    with connect() as conn:
        ev = conn.execute("SELECT member_id, detail FROM document_events WHERE document_id = %s AND action = 'review.accept'",
                          (doc,)).fetchone()
        origin = conn.execute("SELECT origin, created_by_member_id FROM document_versions WHERE version_id = %s",
                              (out["version_id"],)).fetchone()
    assert ev["member_id"] == people["editor"] and origin == {"origin": "review", "created_by_member_id": people["editor"]}
    # A stale base is refused; so is a reviewer while someone else edits.
    stale = client.post(f"/api/editor/documents/{doc}/review", headers=h,
                        json={"base_version_id": v["version_id"], "action": "reject", "all": True})
    assert stale.status_code == 409
    client.post(f"/api/editor/documents/{doc}/lock", headers=as_member(people["editor2"]))
    held = client.post(f"/api/editor/documents/{doc}/review", headers=h,
                       json={"base_version_id": out["version_id"], "action": "reject", "all": True})
    assert held.status_code == 409
    client.delete(f"/api/editor/documents/{doc}/lock", headers=as_member(people["editor2"]))
    # Readers cannot review.
    assert client.post(f"/api/editor/documents/{doc}/review", headers=as_member(people["outsider"]),
                       json={"base_version_id": out["version_id"], "action": "accept", "all": True}).status_code == 403


def test_editing_keeps_other_reviewers_pending_changes(client, doc, people):
    v = _upload(client, doc, people["editor"])
    h = as_member(people["editor"])
    m = client.get(f"/api/editor/documents/{doc}", headers=h).json()
    assert m["pending_changes"] == 7 and set(m["pending_people"]) == {"Ravi Kalra", "Trilegal", "Kunal Lalit Kaistha"}
    paras = m["paragraphs"]
    assert paras[1]["locked"] and paras[1]["text"] == "The Supplier shall deliver within 30 days"
    assert not paras[4].get("locked")
    # Editing a paragraph with someone else's pending change is refused.
    r = client.post(f"/api/editor/documents/{doc}/save", headers=h, json={
        "base_version_id": v["version_id"], "ops": [{"op": "replace", "pid": 1, "text": "The Supplier shall deliver promptly"}]})
    assert r.status_code == 422 and r.json()["detail"]["locked_pids"] == [1]
    # Editing elsewhere keeps every other reviewer's changes exactly as they were.
    before = [(x.type, x.author, x.text) for x in R.read_revisions(_file(doc))]
    r = client.post(f"/api/editor/documents/{doc}/save", headers=h, json={
        "base_version_id": v["version_id"], "ops": [{"op": "replace", "pid": 4, "text": "Termination on thirty days' notice."}]})
    assert r.status_code == 201, r.text
    after = R.read_revisions(_file(doc))
    theirs = [(x.type, x.author, x.text) for x in after if x.author in ("Ravi Kalra", "Trilegal", "Kunal Lalit Kaistha")]
    assert theirs == before
    mine = {x.author for x in after} - {"Ravi Kalra", "Trilegal", "Kunal Lalit Kaistha"}
    assert len(mine) == 1  # the editor, under their name
    # The editor edits their own pending change again: allowed, still tracked against the original.
    m2 = client.get(f"/api/editor/documents/{doc}", headers=h).json()
    assert m2["paragraphs"][4].get("pending") and not m2["paragraphs"][4].get("locked")
    r = client.post(f"/api/editor/documents/{doc}/save", headers=h, json={
        "base_version_id": m2["base_version_id"], "ops": [{"op": "replace", "pid": 4, "text": "Termination on sixty days' notice."}]})
    assert r.status_code == 201, r.text
    f = _file(doc)
    assert R.text_view(f, "final")[4] == "Termination on sixty days' notice."
    assert R.text_view(f, "original")[4] == "Termination on notice."


def test_comments_go_back_into_the_word_file(client, doc, people):
    _upload(client, doc, people["editor"])
    h = as_member(people["editor"])
    listed = client.get(f"/api/editor/documents/{doc}/comments", headers=h).json()
    ravi = next(t for t in listed["threads"] if t["author"] == "Ravi Kalra")
    assert client.post(f"/api/editor/documents/{doc}/comments", headers=h,
                       json={"body": "Client confirmed 30 days in writing.", "parent_id": ravi["comment_id"]}).status_code == 201
    client.patch(f"/api/editor/documents/{doc}/comments/{ravi['comment_id']}", headers=h, json={"status": "resolved"})
    r = client.get(f"/api/editor/documents/{doc}/download-with-comments", headers=h)
    assert r.status_code == 200 and r.content[:2] == b"PK"
    cs = C.read_comments(r.content)
    reply = next(c for c in cs if c["text"] == "Client confirmed 30 days in writing.")
    root = next(c for c in cs if c["author"] == "Ravi Kalra" and not c["parent_para_id"])
    assert reply["parent_para_id"] == root["para_id"] and root["done"] is True
    assert R.read_revisions(r.content) == R.read_revisions(_file(doc))  # tracked changes untouched
    # Uploading that file back does not duplicate anything.
    _upload(client, doc, people["editor"], r.content)
    with connect() as conn:
        n = conn.execute("SELECT count(*) AS n FROM annotations WHERE document_id = %s AND content = %s",
                         (doc, "Client confirmed 30 days in writing.")).fetchone()["n"]
        status = conn.execute("SELECT status FROM annotations WHERE annotation_id = %s", (ravi["comment_id"],)).fetchone()["status"]
    assert n == 1 and status == "resolved"


def test_contributors_across_versions(client, doc, people):
    v = _upload(client, doc, people["editor"])
    client.post(f"/api/editor/documents/{doc}/save", headers=as_member(people["editor2"]), json={
        "base_version_id": v["version_id"], "ops": [{"op": "replace", "pid": 6, "text": "Notices go to the head office."}]})
    out = client.get(f"/api/editor/documents/{doc}/contributors", headers=as_member(people["editor"])).json()
    by = {p["name"]: p for p in out["people"]}
    assert by["Trilegal"]["external"] and by["Trilegal"]["word"]["deletions"] == 1
    member = next(p for p in out["people"] if p["member_id"] == people["editor2"])
    assert member["precentis"].get("edit.save") == 1 and member["word"]["insertions"] >= 1


def test_final_and_original_renditions(client, doc, people):
    _upload(client, doc, people["editor"])
    for view in ("final", "original", "markup"):
        r = client.get(f"/api/documents/{doc}/render", params={"view": view}, headers=as_member(people["editor"]))
        assert r.status_code in (200, 415), r.text
        if r.status_code == 200:
            assert r.content[:4] == b"%PDF"
