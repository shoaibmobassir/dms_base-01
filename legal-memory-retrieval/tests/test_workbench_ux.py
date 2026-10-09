"""The workbench fixes from the product audit (docs/ui-roadmap/10): deleting empty projects, renaming documents, sharing
from your own library, "shared with me", the reader's own list of everything they may open, project list filters,
saving the firm-templates layout, stopping a review, and naming conversations after their first question.

Through the HTTP API and the real database; everything a test creates is removed afterwards.
"""
from __future__ import annotations

import json
import uuid

from app.chat.store import title_from
from tests.conftest import as_member
from tests.test_workspaces import _ok, _project, _upload, cast, made  # noqa: F401  (fixtures)


def test_only_an_empty_project_can_be_deleted_by_its_owner(client, cast, made):
    p = _project(client, cast["outsider"], made)
    pid = p["project_id"]
    _ok(client.put(f"/api/projects/{pid}/members", json={"principal_id": cast["insider"], "role": "editor"},
                   headers=as_member(cast["outsider"])))
    doc, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid)
    made["documents"].append(doc)
    # an editor may not delete; the owner may not while something is in it
    assert client.delete(f"/api/projects/{pid}", headers=as_member(cast["insider"])).status_code == 403
    r = client.delete(f"/api/projects/{pid}", headers=as_member(cast["outsider"]))
    assert r.status_code == 409 and "1 document" in r.text
    # empty: deleted, gone for everyone
    empty = _project(client, cast["outsider"], made)["project_id"]
    _ok(client.delete(f"/api/projects/{empty}", headers=as_member(cast["outsider"])))
    assert client.get(f"/api/projects/{empty}", headers=as_member(cast["outsider"])).status_code == 404


def test_rename_needs_edit_rights(client, cast, made):
    pid = _project(client, cast["outsider"], made)["project_id"]
    doc, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid)
    made["documents"].append(doc)
    _ok(client.patch(f"/api/workspaces/documents/{doc}", json={"title": "  Renamed   note "}, headers=as_member(cast["outsider"])))
    assert _ok(client.get(f"/api/documents/{doc}", headers=as_member(cast["outsider"])))["title"] == "Renamed note"
    assert client.patch(f"/api/workspaces/documents/{doc}", json={"title": "x"}, headers=as_member(cast["stranger"])).status_code in (403, 404)
    assert client.patch(f"/api/workspaces/documents/{doc}", json={"title": "   "}, headers=as_member(cast["outsider"])).status_code == 422


def test_library_sharing_reaches_only_the_people_shared_with(client, cast, made):
    owner, friend, other = cast["outsider"], cast["insider"], cast["stranger"]
    doc, _, _ = _upload(client, owner, made, kind="library")
    made["documents"].append(doc)
    assert client.get(f"/api/documents/{doc}", headers=as_member(friend)).status_code == 404
    shared = _ok(client.put(f"/api/workspaces/documents/{doc}/shares",
                            json={"principal_type": "member", "principal_id": friend, "level": "read"}, headers=as_member(owner)))
    assert [s["principal_id"] for s in shared["shares"]] == [friend]
    assert client.get(f"/api/documents/{doc}", headers=as_member(friend)).status_code == 200
    assert doc in [d["document_id"] for d in _ok(client.get("/api/workspaces/shared-with-me", headers=as_member(friend)))["documents"]]
    assert client.get(f"/api/documents/{doc}", headers=as_member(other)).status_code == 404
    assert doc not in json.dumps(_ok(client.get("/api/workspaces/shared-with-me", headers=as_member(other))))
    # only the owner shares, and only from their own library
    assert client.put(f"/api/workspaces/documents/{doc}/shares", json={"principal_type": "member", "principal_id": other, "level": "read"},
                      headers=as_member(friend)).status_code == 404
    # stop sharing
    _ok(client.put(f"/api/workspaces/documents/{doc}/shares", json={"principal_type": "member", "principal_id": friend, "level": None},
                   headers=as_member(owner)))
    assert client.get(f"/api/documents/{doc}", headers=as_member(friend)).status_code == 404


def test_the_readers_own_list_includes_their_projects_and_library_but_firm_lists_do_not(client, cast, made):
    word = f"wombat{uuid.uuid4().hex[:6]}"
    lib, _, _ = _upload(client, cast["outsider"], made, kind="library", name=f"{word}.txt")
    made["documents"].append(lib)
    mine = _ok(client.get("/api/documents", params={"q": word, "homes": "all"}, headers=as_member(cast["outsider"])))
    row = next(i for i in mine["items"] if i["document_id"] == lib)
    assert row["home_kind"] == "library" and row["home_label"] == "My library"
    # the default (firm-wide) list and other people never see it
    assert lib not in json.dumps(_ok(client.get("/api/documents", params={"q": word}, headers=as_member(cast["outsider"]))))
    assert lib not in json.dumps(_ok(client.get("/api/documents", params={"q": word, "homes": "all"}, headers=as_member(cast["stranger"]))))
    only = _ok(client.get("/api/documents", params={"q": word, "homes": "all", "home_kind": "matter"}, headers=as_member(cast["outsider"])))
    assert lib not in json.dumps(only)


def test_project_list_scopes_and_matter_filter(client, cast, made):
    own = _project(client, cast["outsider"], made)["project_id"]
    theirs = _project(client, cast["insider"], made)["project_id"]
    _ok(client.put(f"/api/projects/{theirs}/members", json={"principal_id": cast["outsider"], "role": "viewer"},
                   headers=as_member(cast["insider"])))
    ids = lambda scope: [p["project_id"] for p in _ok(client.get("/api/projects", params={"scope": scope, "limit": 200},  # noqa: E731
                                                                  headers=as_member(cast["outsider"])))["items"]]
    assert own in ids("mine") and theirs not in ids("mine")
    assert theirs in ids("shared") and own not in ids("shared")
    listed = _ok(client.get("/api/projects", params={"matter_id": "NO-SUCH-MATTER"}, headers=as_member(cast["outsider"])))
    assert listed["items"] == [] and listed["total"] == 0


def test_the_firm_templates_layout_is_saved(client, cast):
    _ok(client.put("/api/workspaces/firm/templates/state", json={"state": {"side": "search"}}, headers=as_member(cast["outsider"])))
    assert _ok(client.get("/api/workspaces/firm/templates/state", headers=as_member(cast["outsider"])))["state"]["side"] == "search"


def test_conversations_are_named_after_their_first_question():
    assert title_from("  What   relief was sought?  ") == "What relief was sought?"
    long = "Summarise the arguments filed so far in the matter and list every date mentioned in the pleadings please"
    t = title_from(long)
    assert len(t) <= 71 and t.endswith("…") and long.startswith(t[:-1])
