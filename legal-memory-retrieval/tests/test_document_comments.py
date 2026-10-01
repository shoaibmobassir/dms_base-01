"""Comments on the exact view of a document (plan 16, E6), through the HTTP API and the real DB."""
from __future__ import annotations

from app.db.connection import connect
from tests.conftest import as_member
from tests.test_document_editor import _docx, doc, people  # noqa: F401 — fixtures

RECT = {"x0": 0.1, "y0": 0.2, "x1": 0.6, "y1": 0.23}


def _url(doc_id: str, suffix: str = "") -> str:
    return f"/api/editor/documents/{doc_id}/comments{suffix}"


def _add(client, doc_id, member, **body):
    return client.post(_url(doc_id), headers=as_member(member),
                       json={"body": "Check this date", "page": 1, "rects": [RECT], "quote": "Effective Date", **body})


def _threads(client, doc_id, member, **params):
    r = client.get(_url(doc_id), headers=as_member(member), params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_comment_is_attributed_to_the_session_and_listed_on_its_page(client, doc, people):
    r = _add(client, doc, people["editor"], author_name="Someone Else")
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["author_id"] == people["editor"] and c["author"] != "Someone Else"
    assert c["rects"] == [RECT] and c["page"] == 1 and c["status"] == "open"
    listed = _threads(client, doc, people["editor2"])
    assert listed["is_current"] and [t["comment_id"] for t in listed["threads"]] == [c["comment_id"]]
    with connect() as conn:
        actions = [r["action"] for r in conn.execute(
            "SELECT action FROM document_events WHERE document_id = %s ORDER BY seq", (doc,))]
    assert "comment.add" in actions


def test_replies_thread_under_the_first_comment(client, doc, people):
    root = _add(client, doc, people["editor"]).json()["comment_id"]
    r = client.post(_url(doc), headers=as_member(people["editor2"]), json={"body": "Agreed — 1 March", "parent_id": root})
    assert r.status_code == 201, r.text
    reply = r.json()["comment_id"]
    # No replies to replies.
    r = client.post(_url(doc), headers=as_member(people["editor"]), json={"body": "x", "parent_id": reply})
    assert r.status_code == 422
    t = _threads(client, doc, people["editor"])["threads"][0]
    assert [x["comment_id"] for x in t["replies"]] == [reply] and t["replies"][0]["author_id"] == people["editor2"]


def test_resolve_and_reopen(client, doc, people):
    cid = _add(client, doc, people["editor"]).json()["comment_id"]
    r = client.patch(_url(doc, f"/{cid}"), headers=as_member(people["editor2"]), json={"status": "resolved"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved" and r.json()["resolved_by"]
    r = client.patch(_url(doc, f"/{cid}"), headers=as_member(people["editor"]), json={"status": "open"})
    assert r.json()["status"] == "open" and r.json()["resolved_at"] is None


def test_only_the_author_or_a_manager_deletes(client, doc, people):
    cid = _add(client, doc, people["editor"]).json()["comment_id"]
    r = client.delete(_url(doc, f"/{cid}"), headers=as_member(people["outsider"]))
    assert r.status_code == 403
    assert client.delete(_url(doc, f"/{cid}"), headers=as_member(people["editor"])).status_code == 204
    assert _threads(client, doc, people["editor"])["threads"] == []


def test_readers_comment_but_only_the_author_or_editors_resolve(client, doc, people):
    """The matter is firm-open: people outside the team can read and comment, not resolve others' threads."""
    theirs = _add(client, doc, people["outsider"], body="Is this the signed copy?")
    assert theirs.status_code == 201, theirs.text
    mine = _add(client, doc, people["editor"]).json()["comment_id"]
    r = client.patch(_url(doc, f"/{mine}"), headers=as_member(people["outsider"]), json={"status": "resolved"})
    assert r.status_code == 403
    r = client.patch(_url(doc, f"/{theirs.json()['comment_id']}"), headers=as_member(people["outsider"]),
                     json={"status": "resolved"})
    assert r.status_code == 200


def test_bad_input_is_refused(client, doc, people):
    assert _add(client, doc, people["editor"], body="   ").status_code == 422
    assert _add(client, doc, people["editor"], rects=[{"x0": 0.5, "y0": 0.2, "x1": 0.4, "y1": 0.3}]).status_code == 422
    assert _add(client, doc, people["editor"], rects=[{"x0": 0.1, "y0": 0.2, "x1": 1.4, "y1": 0.3}]).status_code == 422
    assert _add(client, doc, people["editor"], page=None).status_code == 422
    assert _add(client, doc, people["editor"], version_id="VER-NOPE").status_code == 404


def test_open_threads_carry_forward_resolved_ones_stay(client, doc, people):
    open_one = _add(client, doc, people["editor"]).json()
    done = _add(client, doc, people["editor"], body="Typo fixed").json()
    client.patch(_url(doc, f"/{done['comment_id']}"), headers=as_member(people["editor"]), json={"status": "resolved"})
    r = client.post(f"/api/editor/documents/{doc}/versions", headers=as_member(people["editor"]),
                    files={"file": ("v2.docx", _docx(), "application/octet-stream")})
    assert r.status_code == 201, r.text
    now = _threads(client, doc, people["editor"])
    assert [t["comment_id"] for t in now["threads"]] == [open_one["comment_id"]]
    carried = now["threads"][0]
    assert carried["carried"] and carried["version_id"] == open_one["version_id"] and carried["quote"] == "Effective Date"
    assert now["on_other_versions"] == 1  # the resolved thread, left on v1
    # Replies and resolving work on a carried thread from the new version's view.
    assert client.post(_url(doc), headers=as_member(people["editor2"]),
                       json={"body": "Still open on v2", "parent_id": open_one["comment_id"]}).status_code == 201
    assert _threads(client, doc, people["editor"])["threads"][0]["replies"][0]["body"] == "Still open on v2"
    client.patch(_url(doc, f"/{open_one['comment_id']}"), headers=as_member(people["editor"]), json={"status": "resolved"})
    assert _threads(client, doc, people["editor"])["threads"] == []
    old = _threads(client, doc, people["editor"], version_id=open_one["version_id"])
    assert not old["is_current"] and {t["comment_id"] for t in old["threads"]} == {open_one["comment_id"], done["comment_id"]}
    assert not any(t["carried"] for t in old["threads"])


def test_legacy_annotation_endpoint_takes_the_author_from_the_session(client, doc, people):
    vid = _threads(client, doc, people["editor"])["version_id"]
    url = f"/api/documents/{doc}/versions/{vid}/annotations"
    r = client.post(url, headers=as_member(people["editor"]), json={"quoted_text": "Effective Date", "author_name": "Someone Else"})
    assert r.status_code == 200, r.text
    ann = r.json()["annotation"]
    assert ann["author_id"] == people["editor"] and ann["author_name"] != "Someone Else"
    # Comments must go through the comment rules; versions of other documents are refused.
    assert client.post(url, headers=as_member(people["editor"]), json={"quoted_text": "x", "annotation_type": "comment"}).status_code == 422
    other = f"/api/documents/{doc}/versions/VER-NOTMINE/annotations"
    assert client.post(other, headers=as_member(people["editor"]), json={"quoted_text": "x"}).status_code == 404
