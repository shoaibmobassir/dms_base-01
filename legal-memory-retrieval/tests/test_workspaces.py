"""Workspaces (plan 22, W0) through the HTTP API and the real database: projects anyone can create, documents
stored once and shown in several workspaces by links, tags, folders, filing, copies, de-duplicated storage.

The rule under test throughout: a document's home governs who may read it, and a link never widens that.
Everything a test creates is removed afterwards.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta

import pytest

from app import access
from app.db.connection import connect
from tests.conftest import as_member


def _rows(sql, params=()):
    with connect() as conn:
        return list(conn.execute(sql, params).fetchall())


@pytest.fixture(scope="module")
def cast(walls):
    """A walled matter's insider and outsider, a stranger, and a matter the outsider is staffed on (all without
    walls.manage, which would let them read anything)."""
    with connect() as conn:
        plain = [r["member_id"] for r in conn.execute("SELECT member_id FROM members WHERE active ORDER BY member_id")
                 if not access.has_permission(conn, r["member_id"], "walls.manage")]
        for w in walls:
            if w.insider not in plain or w.outsider not in plain:
                continue
            allowed = set(conn.execute("SELECT allowed_members FROM permissions WHERE matter_id = %s",
                                       (w.matter_id,)).fetchone()["allowed_members"])
            strangers = [m for m in plain if m not in allowed and m not in (w.insider, w.outsider)]
            staffed = conn.execute(
                """SELECT mm.matter_id FROM matter_members mm JOIN permissions p USING (matter_id)
                   WHERE mm.member_id = %s AND (mm.ended_at IS NULL OR mm.ended_at >= current_date)
                     AND NOT (%s = ANY(p.denied_members)) AND NOT p.restricted LIMIT 1""",
                (w.outsider, strangers[0] if strangers else "")).fetchone()
            if strangers and staffed:
                return {"wall": w, "insider": w.insider, "outsider": w.outsider, "stranger": strangers[0],
                        "own_matter": staffed["matter_id"]}
    pytest.skip("needs a walled matter with an insider and outsider without walls.manage, a stranger, and a matter "
                "the outsider is staffed on")


@pytest.fixture
def made():
    out = {"projects": [], "batches": [], "documents": []}
    yield out
    from app.ingest.purge import purge_documents, purge_projects, purge_upload_batches
    from app.storage.blobs import collect

    shas = [r["content_sha256"] for r in _rows(
        "SELECT DISTINCT content_sha256 FROM upload_batch_files WHERE batch_id = ANY(%s)", (out["batches"],))]
    purge_upload_batches(out["batches"])
    if out["documents"]:
        with connect() as conn, conn.transaction():
            purge_documents(conn, out["documents"])
    purge_projects(out["projects"])
    if shas:
        with connect() as conn:
            collect(conn, grace=timedelta(0), only=shas)


def _ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text[:500])
    return r.json() if r.content else None


def _project(client, member, made, title="E2E-TMP project"):
    p = _ok(client.post("/api/projects", json={"title": f"{title} {uuid.uuid4().hex[:6]}"}, headers=as_member(member)), 201)
    made["projects"].append(p["project_id"])
    return p


def _upload(client, member, made, *, kind, cid=None, name="note.txt", body=None, folder=""):
    body = body or f"E2E-TMP {uuid.uuid4().hex} the notice period is ninety days".encode()
    data = {"container_kind": kind, "folder_prefix": folder}
    if cid:
        data["container_id"] = cid
    b = _ok(client.post("/api/uploads/batches", data=data, files=[("files", (name, body, "text/plain"))],
                        headers=as_member(member)))
    made["batches"].append(b["batch_id"])
    r = _ok(client.post(f"/api/uploads/batches/{b['batch_id']}/run", headers=as_member(member)))
    f = r["batch"]["files"][0]
    return f["document_id"], b, body


# ── projects ─────────────────────────────────────────────────────────────────

def test_anyone_creates_projects_and_only_members_see_them(client, cast, made):
    p = _project(client, cast["outsider"], made)
    assert p["my_role"] == "owner" and p["members"][0]["principal_id"] == cast["outsider"]
    assert client.get(f"/api/projects/{p['project_id']}", headers=as_member(cast["stranger"])).status_code == 404
    mine = _ok(client.get("/api/projects", headers=as_member(cast["outsider"])))["items"]
    assert p["project_id"] in [x["project_id"] for x in mine]
    theirs = _ok(client.get("/api/projects", headers=as_member(cast["stranger"])))["items"]
    assert p["project_id"] not in [x["project_id"] for x in theirs]


def test_project_roles_and_last_owner(client, cast, made):
    p = _project(client, cast["insider"], made)
    pid = p["project_id"]
    _ok(client.put(f"/api/projects/{pid}/members", json={"principal_id": cast["outsider"], "role": "viewer"},
                   headers=as_member(cast["insider"])))
    # a viewer cannot edit the project, add members or upload
    r = client.patch(f"/api/projects/{pid}", json={"title": "x"}, headers=as_member(cast["outsider"]))
    assert r.status_code == 403
    r = client.put(f"/api/projects/{pid}/members", json={"principal_id": cast["stranger"], "role": "viewer"},
                   headers=as_member(cast["outsider"]))
    assert r.status_code == 403
    r = client.post("/api/uploads/batches", data={"container_kind": "project", "container_id": pid},
                    files=[("files", ("x.txt", b"x", "text/plain"))], headers=as_member(cast["outsider"]))
    assert r.status_code == 403
    # the only owner cannot step down or leave
    r = client.put(f"/api/projects/{pid}/members", json={"principal_id": cast["insider"], "role": "editor"},
                   headers=as_member(cast["insider"]))
    assert r.status_code == 409
    r = client.delete(f"/api/projects/{pid}/members/member/{cast['insider']}", headers=as_member(cast["insider"]))
    assert r.status_code == 409
    # stale edit refused
    r = client.patch(f"/api/projects/{pid}", json={"title": "Renamed", "row_version": 99},
                     headers=as_member(cast["insider"]))
    assert r.status_code == 409
    # a member may leave
    _ok(client.delete(f"/api/projects/{pid}/members/member/{cast['outsider']}", headers=as_member(cast["outsider"])))
    assert client.get(f"/api/projects/{pid}", headers=as_member(cast["outsider"])).status_code == 404


def test_archived_project_is_read_only(client, cast, made):
    pid = _project(client, cast["outsider"], made)["project_id"]
    _ok(client.post(f"/api/projects/{pid}/archive", headers=as_member(cast["outsider"])))
    r = client.post("/api/uploads/batches", data={"container_kind": "project", "container_id": pid},
                    files=[("files", ("x.txt", b"x", "text/plain"))], headers=as_member(cast["outsider"]))
    assert r.status_code == 409
    assert client.post(f"/api/workspaces/project/{pid}/folders", json={"path": "A"},
                       headers=as_member(cast["outsider"])).status_code == 409
    _ok(client.get(f"/api/workspaces/project/{pid}/items", headers=as_member(cast["outsider"])))
    _ok(client.post(f"/api/projects/{pid}/restore", headers=as_member(cast["outsider"])))


# ── a link never widens access ───────────────────────────────────────────────

def test_walled_document_linked_into_a_project_stays_walled(client, cast, made):
    wall = cast["wall"]
    pid = _project(client, cast["insider"], made)["project_id"]
    _ok(client.put(f"/api/projects/{pid}/members", json={"principal_id": cast["outsider"], "role": "editor"},
                   headers=as_member(cast["insider"])))
    _ok(client.post(f"/api/workspaces/documents/{wall.document_id}/links",
                    json={"kind": "project", "id": pid, "folder": "Evidence"}, headers=as_member(cast["insider"])), 201)
    seen = _ok(client.get(f"/api/workspaces/project/{pid}/items", params={"folder": "Evidence"},
                          headers=as_member(cast["outsider"])))["documents"]
    assert len(seen) == 1 and seen[0]["restricted"] and "title" not in seen[0] and "document_id" not in seen[0]
    assert wall.title not in json.dumps(seen)
    for path in (f"/api/documents/{wall.document_id}", f"/api/documents/{wall.document_id}/text",
                 f"/api/workspaces/documents/{wall.document_id}"):
        assert client.get(path, headers=as_member(cast["outsider"])).status_code == 404, path
    for body in ({"kind": "library", "id": "me"},):
        assert client.post(f"/api/workspaces/documents/{wall.document_id}/copy", json=body,
                           headers=as_member(cast["outsider"])).status_code == 404
    # an outsider cannot link what they cannot read
    own = _project(client, cast["outsider"], made)["project_id"]
    assert client.post(f"/api/workspaces/documents/{wall.document_id}/links", json={"kind": "project", "id": own},
                       headers=as_member(cast["outsider"])).status_code == 404
    # the insider sees the real document, marked as a link
    mine = _ok(client.get(f"/api/workspaces/project/{pid}/items", params={"folder": "Evidence"},
                          headers=as_member(cast["insider"])))["documents"]
    assert mine[0]["document_id"] == wall.document_id and mine[0]["placement"] == "link"


def test_project_documents_never_reach_firm_lists_search_or_strangers(client, cast, made):
    pid = _project(client, cast["outsider"], made)["project_id"]
    phrase = f"zephyr{uuid.uuid4().hex[:8]}"
    doc, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid, name=f"{phrase}.txt",
                        body=f"E2E-TMP {phrase} indemnity cap".encode())
    assert _ok(client.get(f"/api/documents/{doc}", headers=as_member(cast["outsider"])))
    for path in (f"/api/documents/{doc}", f"/api/documents/{doc}/text", f"/api/documents/{doc}/versions",
                 f"/api/workspaces/documents/{doc}", f"/api/editor/documents/{doc}"):
        assert client.get(path, headers=as_member(cast["stranger"])).status_code in (403, 404), path
    for m in (cast["outsider"], cast["stranger"]):
        assert doc not in json.dumps(_ok(client.get("/api/documents", params={"q": phrase}, headers=as_member(m))))
        assert doc not in json.dumps(_ok(client.get("/api/search", params={"q": phrase}, headers=as_member(m))))
    with connect() as conn:
        row = conn.execute("SELECT matter_id, home_kind, home_id, visible_to FROM documents WHERE document_id = %s",
                           (doc,)).fetchone()
        chunks = conn.execute("SELECT count(*) AS n, count(*) FILTER (WHERE matter_id IS NULL "
                              "AND %s = ANY(visible_to)) AS ok FROM chunks WHERE document_id = %s",
                              (cast["outsider"], doc)).fetchone()
    assert row["matter_id"] is None and row["home_kind"] == "project" and row["home_id"] == pid
    assert cast["outsider"] in row["visible_to"] and cast["stranger"] not in row["visible_to"]
    assert chunks["n"] > 0 and chunks["n"] == chunks["ok"]


def test_membership_changes_follow_through_to_documents(client, cast, made):
    pid = _project(client, cast["insider"], made)["project_id"]
    doc, _, _ = _upload(client, cast["insider"], made, kind="project", cid=pid)
    assert client.get(f"/api/documents/{doc}", headers=as_member(cast["stranger"])).status_code == 404
    _ok(client.put(f"/api/projects/{pid}/members", json={"principal_id": cast["stranger"], "role": "viewer"},
                   headers=as_member(cast["insider"])))
    assert client.get(f"/api/documents/{doc}", headers=as_member(cast["stranger"])).status_code == 200
    _ok(client.delete(f"/api/projects/{pid}/members/member/{cast['stranger']}", headers=as_member(cast["insider"])))
    assert client.get(f"/api/documents/{doc}", headers=as_member(cast["stranger"])).status_code == 404


def test_project_events_reach_members_only(client, cast, made):
    with connect() as conn:
        since = conn.execute("SELECT coalesce(max(seq), 0) AS n FROM domain_events").fetchone()["n"]
    pid = _project(client, cast["outsider"], made)["project_id"]

    def project_events(m):
        items = _ok(client.get("/api/events", params={"since": since}, headers=as_member(m)))["items"]
        return [e for e in items if e["entity_id"] == pid]

    assert project_events(cast["outsider"])
    assert project_events(cast["stranger"]) == []


# ── library, de-duplication, copies, filing ──────────────────────────────────

def test_library_is_private_and_storage_is_shared(client, cast, made):
    body = f"E2E-TMP {uuid.uuid4().hex} same bytes twice".encode()
    sha = hashlib.sha256(body).hexdigest()
    lib_doc, b1, _ = _upload(client, cast["outsider"], made, kind="library", body=body)
    for m in (cast["insider"], cast["stranger"]):
        assert client.get(f"/api/documents/{lib_doc}", headers=as_member(m)).status_code == 404
    # only documents the caller can read are named by the duplicate check
    d = _ok(client.post("/api/workspaces/duplicates", json={"kind": "library", "id": "me", "hashes": [sha]},
                        headers=as_member(cast["outsider"])))
    assert d["matches"][sha][0]["document_id"] == lib_doc and d["matches"][sha][0]["already_here"]
    d = _ok(client.post("/api/workspaces/duplicates", json={"kind": "library", "id": "me", "hashes": [sha]},
                        headers=as_member(cast["stranger"])))
    assert d["matches"] == {}
    # the same bytes uploaded by someone else are stored once
    other, b2, _ = _upload(client, cast["stranger"], made, kind="library", body=body)
    assert b1["files"][0]["storage_uri"] == b2["files"][0]["storage_uri"]
    assert len(_rows("SELECT 1 FROM blobs WHERE content_sha256 = %s", (sha,))) == 1
    # re-uploading into the same workspace is recognised as a duplicate
    b3 = _ok(client.post("/api/uploads/batches", data={"container_kind": "library"},
                         files=[("files", ("again.txt", body, "text/plain"))], headers=as_member(cast["outsider"])))
    made["batches"].append(b3["batch_id"])
    r = _ok(client.post(f"/api/uploads/batches/{b3['batch_id']}/run", headers=as_member(cast["outsider"])))
    assert r["skipped"] == 1 and r["batch"]["files"][0]["document_id"] == lib_doc


def test_copy_is_a_separate_document_sharing_the_file(client, cast, made):
    pid = _project(client, cast["outsider"], made)["project_id"]
    doc, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid)
    cp = _ok(client.post(f"/api/workspaces/documents/{doc}/copy", json={"kind": "library", "id": "me", "title": "Mine"},
                         headers=as_member(cast["outsider"])), 201)
    made["documents"].append(cp["document_id"])
    rows = {r["document_id"]: r for r in _rows(
        """SELECT d.document_id, d.home_kind, d.derived_from_document_id, v.storage_uri FROM documents d
           JOIN document_versions v ON v.version_id = d.current_version_id WHERE d.document_id = ANY(%s)""",
        ([doc, cp["document_id"]],))}
    assert rows[cp["document_id"]]["home_kind"] == "library"
    assert rows[cp["document_id"]]["derived_from_document_id"] == doc
    assert rows[cp["document_id"]]["storage_uri"] == rows[doc]["storage_uri"]
    places = _ok(client.get(f"/api/workspaces/documents/{cp['document_id']}", headers=as_member(cast["outsider"])))
    assert places["derived_from"]["document_id"] == doc
    # a project member who is not the library owner cannot read the copy
    _ok(client.put(f"/api/projects/{pid}/members", json={"principal_id": cast["stranger"], "role": "viewer"},
                   headers=as_member(cast["outsider"])))
    assert client.get(f"/api/documents/{cp['document_id']}", headers=as_member(cast["stranger"])).status_code == 404


def test_filing_into_a_matter_moves_the_home_and_keeps_a_link(client, cast, made):
    pid = _project(client, cast["outsider"], made)["project_id"]
    doc, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid, folder="Drafts")
    made["documents"].append(doc)
    matter = cast["own_matter"]
    # a project viewer cannot file
    _ok(client.put(f"/api/projects/{pid}/members", json={"principal_id": cast["stranger"], "role": "viewer"},
                   headers=as_member(cast["outsider"])))
    assert client.post(f"/api/workspaces/documents/{doc}/move-home", json={"kind": "matter", "id": matter},
                       headers=as_member(cast["stranger"])).status_code in (403, 404)
    places = _ok(client.post(f"/api/workspaces/documents/{doc}/move-home",
                             json={"kind": "matter", "id": matter, "folder": "Pleadings"},
                             headers=as_member(cast["outsider"])))
    home = [p for p in places["places"] if p["home"]][0]
    assert home["kind"] == "matter" and home["id"] == matter and home["folder"] == "Pleadings"
    assert any(p["kind"] == "project" and p["id"] == pid and not p["home"] for p in places["places"])
    row = _rows("SELECT matter_id, home_kind, home_id, visible_to FROM documents WHERE document_id = %s", (doc,))[0]
    assert row["matter_id"] == matter and row["home_kind"] == "matter" and row["home_id"] is None
    assert row["visible_to"] is None  # follows the matter now
    assert {r["matter_id"] for r in _rows("SELECT DISTINCT matter_id FROM chunks WHERE document_id = %s", (doc,))} == {matter}
    # matter documents stay in their matter
    r = client.post(f"/api/workspaces/documents/{doc}/move-home", json={"kind": "project", "id": pid},
                    headers=as_member(cast["outsider"]))
    assert r.status_code == 409


def test_tags_follow_links_and_filter(client, cast, made):
    pid = _project(client, cast["outsider"], made)["project_id"]
    other = _project(client, cast["outsider"], made)["project_id"]
    doc, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid)
    _ok(client.post(f"/api/workspaces/documents/{doc}/links", json={"kind": "project", "id": other},
                    headers=as_member(cast["outsider"])), 201)
    _ok(client.post(f"/api/workspaces/documents/{doc}/tags", json={"tag": "  Notice  Period "},
                    headers=as_member(cast["outsider"])))
    places = _ok(client.get(f"/api/workspaces/documents/{doc}", headers=as_member(cast["outsider"])))
    keys = [t["key"] for t in places["tags"]["system"]]
    assert f"project:{pid}" in keys and f"project:{other}" in keys
    assert places["tags"]["user"] == ["notice period"]
    hit = _ok(client.get(f"/api/workspaces/project/{other}/items", params={"tag": "notice period", "recursive": True},
                         headers=as_member(cast["outsider"])))["documents"]
    assert [d["document_id"] for d in hit] == [doc]
    assert client.post(f"/api/workspaces/documents/{doc}/tags", json={"tag": "matter:x"},
                       headers=as_member(cast["outsider"])).status_code == 422
    _ok(client.delete(f"/api/workspaces/documents/{doc}/links/project/{other}", headers=as_member(cast["outsider"])))
    keys = [t["key"] for t in _ok(client.get(f"/api/workspaces/documents/{doc}",
                                             headers=as_member(cast["outsider"])))["tags"]["system"]]
    assert f"project:{other}" not in keys


def test_folders_rename_and_delete(client, cast, made):
    pid = _project(client, cast["outsider"], made)["project_id"]
    doc, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid, folder="Notes/2026")
    _ok(client.post(f"/api/workspaces/project/{pid}/folders", json={"path": "Empty/Inner"},
                    headers=as_member(cast["outsider"])), 201)
    root = _ok(client.get(f"/api/workspaces/project/{pid}/items", headers=as_member(cast["outsider"])))
    assert {f["path"]: f["document_count"] for f in root["folders"]} == {"Empty": 0, "Notes": 1}
    assert client.post(f"/api/workspaces/project/{pid}/folders", json={"path": "../x"},
                       headers=as_member(cast["outsider"])).status_code == 422
    _ok(client.patch(f"/api/workspaces/project/{pid}/folders", json={"path": "Notes", "new_path": "Archive/Notes"},
                     headers=as_member(cast["outsider"])))
    assert _rows("SELECT folder_path FROM documents WHERE document_id = %s", (doc,))[0]["folder_path"] == "Archive/Notes/2026"
    assert client.patch(f"/api/workspaces/project/{pid}/folders", json={"path": "Archive", "new_path": "Archive/x"},
                        headers=as_member(cast["outsider"])).status_code == 422
    assert client.request("DELETE", f"/api/workspaces/project/{pid}/folders", params={"path": "Archive"},
                          headers=as_member(cast["outsider"])).status_code == 409
    _ok(client.request("DELETE", f"/api/workspaces/project/{pid}/folders", params={"path": "Empty"},
                       headers=as_member(cast["outsider"])))
    _ok(client.patch(f"/api/workspaces/documents/{doc}/folder", json={"kind": "project", "id": pid, "folder": ""},
                     headers=as_member(cast["outsider"])))
    root = _ok(client.get(f"/api/workspaces/project/{pid}/items", headers=as_member(cast["outsider"])))
    assert [d["document_id"] for d in root["documents"]] == [doc]


def test_matter_uploads_unchanged(client, cast, made):
    """Uploading into a matter still makes a matter document that follows the matter's access."""
    doc, b, _ = _upload(client, cast["outsider"], made, kind="matter", cid=cast["own_matter"])
    row = _rows("SELECT matter_id, home_kind, home_id, visible_to FROM documents WHERE document_id = %s", (doc,))[0]
    assert row == {"matter_id": cast["own_matter"], "home_kind": "matter", "home_id": None, "visible_to": None}
    assert "/blobs/sha256/" in b["files"][0]["storage_uri"]


def test_workspace_search_finds_words_inside_project_documents(client, cast, made):
    pid = _project(client, cast["outsider"], made)["project_id"]
    word = f"quokka{uuid.uuid4().hex[:6]}"
    doc, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid, name="memo.txt",
                        body=f"E2E-TMP the {word} clause survives termination".encode())
    hits = _ok(client.get(f"/api/workspaces/project/{pid}/search", params={"q": word},
                          headers=as_member(cast["outsider"])))["results"]
    assert [h["document_id"] for h in hits] == [doc] and hits[0]["match_kind"] == "content"
    assert "{MARK_START}" in hits[0]["snippet"]
    assert client.get(f"/api/workspaces/project/{pid}/search", params={"q": word},
                      headers=as_member(cast["stranger"])).status_code == 404


def test_saved_layout_drops_tabs_the_member_can_no_longer_read(client, cast, made):
    pid = _project(client, cast["insider"], made)["project_id"]
    _ok(client.put(f"/api/projects/{pid}/members", json={"principal_id": cast["outsider"], "role": "editor"},
                   headers=as_member(cast["insider"])))
    doc, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid)
    wall_doc = cast["wall"].document_id
    state = {"groups": [{"tabs": [{"id": "a", "kind": "document", "documentId": doc},
                                  {"id": "b", "kind": "document", "documentId": wall_doc}], "active": "a"}]}
    _ok(client.put(f"/api/workspaces/project/{pid}/state", json={"state": state}, headers=as_member(cast["outsider"])))
    got = _ok(client.get(f"/api/workspaces/project/{pid}/state", headers=as_member(cast["outsider"])))["state"]
    assert [t["documentId"] for t in got["groups"][0]["tabs"]] == [doc]
    # layouts are per person
    assert _ok(client.get(f"/api/workspaces/project/{pid}/state", headers=as_member(cast["insider"])))["state"] == {}
    too_many = {"groups": [{"tabs": [{"id": str(i)} for i in range(41)]}]}
    assert client.put(f"/api/workspaces/project/{pid}/state", json={"state": too_many},
                      headers=as_member(cast["outsider"])).status_code == 422
    with connect() as conn:
        conn.execute("DELETE FROM workbench_state WHERE scope_key = %s", (f"project:{pid}",))
        conn.commit()


def test_archived_project_document_is_hidden(client, cast, made):
    pid = _project(client, cast["outsider"], made)["project_id"]
    doc, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid)
    with connect() as conn:
        conn.execute("UPDATE documents SET archived_at = now() WHERE document_id = %s", (doc,))
        conn.commit()
        row = conn.execute("SELECT visible_to FROM documents WHERE document_id = %s", (doc,)).fetchone()
    assert row["visible_to"] == []
    assert client.get(f"/api/documents/{doc}", headers=as_member(cast["outsider"])).status_code == 404
    items = _ok(client.get(f"/api/workspaces/project/{pid}/items", headers=as_member(cast["outsider"])))["documents"]
    assert doc not in json.dumps(items)


def test_firm_templates_are_read_by_everyone_curated_by_publishers_and_copied_not_edited(client, cast, made):
    with connect() as conn:
        pub = next((r["member_id"] for r in conn.execute("SELECT DISTINCT member_id FROM member_roles ORDER BY member_id")
                    if access.has_permission(conn, r["member_id"], "km.publish")
                    and not access.has_permission(conn, r["member_id"], "walls.manage")), None)
        plain = [r["member_id"] for r in conn.execute("SELECT member_id FROM members WHERE active ORDER BY member_id")
                 if not access.has_permission(conn, r["member_id"], "km.publish")
                 and not access.has_permission(conn, r["member_id"], "walls.manage")]
    if not pub or not plain:
        pytest.skip("needs a publisher and a member without km.publish")
    word = f"ocelot{uuid.uuid4().hex[:6]}"
    tmpl, b, _ = _upload(client, pub, made, kind="firm", cid="templates", folder="NDAs",
                         body=f"E2E-TMP Mutual NDA template {word}: the Recipient shall keep [PARTY] information confidential.".encode())
    made["documents"].append(tmpl)
    reader = plain[0]
    assert client.get(f"/api/documents/{tmpl}", headers=as_member(reader)).status_code == 200
    items = _ok(client.get("/api/workspaces/firm/templates/items", params={"folder": "NDAs"}, headers=as_member(reader)))
    assert tmpl in [d["document_id"] for d in items["documents"]] and items["my_level"] == "read"
    # only publishers add templates
    r = client.post("/api/uploads/batches", data={"container_kind": "firm"}, files=[("files", ("x.txt", b"x", "text/plain"))],
                    headers=as_member(reader))
    assert r.status_code == 403
    # not part of firm search
    assert tmpl not in json.dumps(_ok(client.get("/api/search", params={"q": word}, headers=as_member(reader))))
    # a template stays in the library; drafting works on a copy
    pid = _project(client, reader, made)["project_id"]
    own = _project(client, pub, made)["project_id"]
    assert client.post(f"/api/workspaces/documents/{tmpl}/move-home", json={"kind": "project", "id": own},
                       headers=as_member(pub)).status_code == 409
    cp = _ok(client.post(f"/api/workspaces/documents/{tmpl}/copy", json={"kind": "project", "id": pid, "title": "NDA — Acme"},
                         headers=as_member(reader)), 201)
    places = _ok(client.get(f"/api/workspaces/documents/{cp['document_id']}", headers=as_member(reader)))
    assert places["derived_from"]["document_id"] == tmpl and places["places"][0]["kind"] == "project"
    assert client.get(f"/api/editor/documents/{tmpl}", headers=as_member(reader)).json().get("editable") in (False, None)
