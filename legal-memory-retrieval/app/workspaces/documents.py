"""Documents across workspaces: what a workspace shows, links, filing, copies, folders and tags (plan 22, W0).

- A workspace shows its *home* documents and the documents *linked* into it. A linked document the member
  cannot read at its home shows as a restricted placeholder (no title, no id): a link never widens access.
- Tags: people's own tags (``document_tags``) plus tags derived from where the document lives (home and the
  links the member can see), its client and its type — derived when read, so they follow every link, move and
  filing with no sync step.
"""
from __future__ import annotations

import uuid
from typing import Any

from app import access
from app.api.acl import ACL_CLAUSE, doc_read
from app.audit import events as audit
from app.firm import FirmError, emit, guard, one
from app.workspaces import (check_kind, clean_path, container_label, home_of, require_container, require_document,
                            rows)
from app.workspaces.projects import visible_project_ids

MAX_TAG = 60


def _home_where(kind: str) -> str:
    if kind == "matter":
        return "d.home_kind = 'matter' AND d.matter_id = %(cid)s"
    return "d.home_kind = %(kind)s AND d.home_id = %(cid)s"


def _visible_matter_ids(conn, actor: str | None) -> set[str] | None:
    if actor is None:
        return None
    return {r["matter_id"] for r in rows(conn, f"SELECT p.matter_id FROM permissions p WHERE {ACL_CLAUSE}",
                                         {"member_id": actor})}


def _can_see(kind: str, cid: str, actor: str | None, matters: set[str] | None, projects: set[str] | None) -> bool:
    if actor is None:
        return True
    if kind == "matter":
        return matters is not None and cid in matters
    if kind == "project":
        return projects is not None and cid in projects
    return cid == actor


# ── what a workspace shows ───────────────────────────────────────────────────

@guard
def list_items(conn, actor: str | None, kind: str, cid: str, *, folder: str | None = "", recursive: bool = False,
               q: str | None = None, tag: str | None = None, limit: int = 200, offset: int = 0) -> dict:
    """Folders directly under ``folder`` and the documents placed there (home or linked)."""
    level = require_container(conn, actor, kind, cid, "read")
    folder = clean_path(folder)
    params: dict[str, Any] = {"kind": kind, "cid": cid, "member_id": actor, "folder": folder,
                              "prefix": (folder + "/") if folder else "", "limit": limit, "offset": offset}
    folder_cond = ("(i.folder = %(folder)s OR i.folder LIKE %(prefix)s || '%%')" if recursive and folder
                   else "TRUE" if recursive else "i.folder = %(folder)s")
    filters = []
    if q and q.strip():
        params["q"] = f"%{q.strip()}%"
        filters.append("d.title ILIKE %(q)s")
    if tag and tag.strip():
        params["tag"] = tag.strip().lower()
        filters.append("EXISTS (SELECT 1 FROM document_tags t WHERE t.document_id = d.document_id AND t.tag = %(tag)s)")
    filtered = " AND ".join(filters)
    sql = f"""
        WITH items AS (
            SELECT d.document_id, NULL::bigint AS link_id, coalesce(d.folder_path, '') AS folder,
                   'home' AS placement, d.updated_at AS placed_at, d.author_id AS placed_by
            FROM documents d WHERE {_home_where(kind)}
            UNION ALL
            SELECT l.document_id, l.link_id, l.folder_path, 'link', l.added_at, l.added_by
            FROM document_links l WHERE l.container_kind = %(kind)s AND l.container_id = %(cid)s
        )
        SELECT i.link_id, i.folder, i.placement, i.placed_at, i.placed_by, {doc_read('d')} AS readable,
               d.document_id, d.title, d.document_type, d.mime_type, d.doc_date, d.updated_at, d.author_name,
               d.home_kind, d.home_id, d.matter_id, d.client_id, d.visible_to IS NOT NULL AND d.home_kind = 'matter' AS private,
               (SELECT dv.version_number FROM document_versions dv WHERE dv.version_id = d.current_version_id) AS version_number
        FROM items i
        JOIN documents d ON d.document_id = i.document_id
        LEFT JOIN permissions p ON p.matter_id = d.matter_id
        WHERE d.archived_at IS NULL AND {folder_cond}{(' AND ' + filtered) if filtered else ''}
        ORDER BY i.folder, lower(d.title), d.document_id
    """
    found = rows(conn, sql, params)
    documents = []
    for r in found:
        if not r["readable"]:
            # Home documents the member cannot read stay out (as in matter lists today); a link shows a
            # placeholder so the workspace's owner knows something is there, without revealing what.
            if r["placement"] == "link" and not filtered:
                documents.append({"restricted": True, "link_id": r["link_id"], "folder": r["folder"],
                                  "placement": "link", "placed_at": r["placed_at"]})
            continue
        r.pop("readable")
        documents.append(r)
    total = len(documents)
    documents = documents[offset:offset + limit]
    tags = document_tags(conn, actor, [d["document_id"] for d in documents if not d.get("restricted")])
    for d in documents:
        if not d.get("restricted"):
            d["tags"] = tags.get(d["document_id"], {"system": [], "user": []})
    return {"kind": kind, "id": cid, "label": container_label(conn, kind, cid), "my_level": level,
            "folder": folder, "folders": _subfolders(conn, kind, cid, folder, found),
            "documents": documents, "total": total, "limit": limit, "offset": offset}


def _subfolders(conn, kind: str, cid: str, folder: str, found: list[dict]) -> list[dict]:
    """Immediate child folders of ``folder``: kept empty folders plus folders that hold documents."""
    paths = {r["path"] for r in rows(conn, "SELECT path FROM workspace_folders WHERE container_kind = %s "
                                           "AND container_id = %s", (kind, cid))}
    counts: dict[str, int] = {}
    for p in paths:
        counts.setdefault(p, 0)
    for r in rows(conn, f"""
            SELECT folder, count(*) AS n FROM (
                SELECT coalesce(d.folder_path, '') AS folder FROM documents d
                WHERE {_home_where(kind)} AND d.archived_at IS NULL
                UNION ALL
                SELECT l.folder_path FROM document_links l
                WHERE l.container_kind = %(kind)s AND l.container_id = %(cid)s) x
            WHERE folder <> '' GROUP BY folder""", {"kind": kind, "cid": cid}):
        counts[r["folder"]] = counts.get(r["folder"], 0) + r["n"]
    prefix = (folder + "/") if folder else ""
    children: dict[str, dict] = {}
    for path, n in counts.items():
        if not path.startswith(prefix) or path == folder:
            continue
        name = path[len(prefix):].split("/", 1)[0]
        child = prefix + name
        entry = children.setdefault(child, {"path": child, "name": name, "document_count": 0})
        entry["document_count"] += n
    return sorted(children.values(), key=lambda c: c["name"].lower())


def document_tags(conn, actor: str | None, document_ids: list[str]) -> dict[str, dict]:
    """Derived (system) and personal (user) tags for documents the caller has already checked."""
    if not document_ids:
        return {}
    matters = _visible_matter_ids(conn, actor)
    projects = visible_project_ids(conn, actor)
    out: dict[str, dict] = {i: {"system": [], "user": []} for i in document_ids}
    docs = rows(conn, """
        SELECT d.document_id, d.home_kind, d.home_id, d.matter_id, m.matter_code, pr.title AS project_title,
               c.name AS client_name, d.document_type
        FROM documents d
        LEFT JOIN matters m ON m.matter_id = d.matter_id
        LEFT JOIN projects pr ON d.home_kind = 'project' AND pr.project_id = d.home_id
        LEFT JOIN clients c ON c.client_id = coalesce(d.client_id, m.client_id)
        WHERE d.document_id = ANY(%s)""", (document_ids,))
    for d in docs:
        tags = out[d["document_id"]]["system"]
        kind, cid = home_of(d)
        if _can_see(kind, cid, actor, matters, projects):
            tags.append(_place_tag(kind, cid, d["matter_code"], d["project_title"], home=True))
        if d["client_name"]:
            tags.append({"key": f"client:{d['client_name']}", "label": d["client_name"], "kind": "client"})
        if d["document_type"]:
            tags.append({"key": f"type:{d['document_type'].lower()}", "label": d["document_type"], "kind": "type"})
    for link in rows(conn, """
            SELECT l.document_id, l.container_kind, l.container_id, m.matter_code, pr.title AS project_title
            FROM document_links l
            LEFT JOIN matters m ON l.container_kind = 'matter' AND m.matter_id = l.container_id
            LEFT JOIN projects pr ON l.container_kind = 'project' AND pr.project_id = l.container_id
            WHERE l.document_id = ANY(%s) ORDER BY l.added_at""", (document_ids,)):
        if _can_see(link["container_kind"], link["container_id"], actor, matters, projects):
            out[link["document_id"]]["system"].append(
                _place_tag(link["container_kind"], link["container_id"], link["matter_code"], link["project_title"],
                           home=False))
    for t in rows(conn, "SELECT document_id, tag FROM document_tags WHERE document_id = ANY(%s) ORDER BY tag",
                  (document_ids,)):
        out[t["document_id"]]["user"].append(t["tag"])
    return out


def _place_tag(kind: str, cid: str, matter_code: str | None, project_title: str | None, *, home: bool) -> dict:
    label = matter_code or cid if kind == "matter" else project_title or cid if kind == "project" else "My library"
    return {"key": f"{kind}:{cid}", "label": label, "kind": kind, "id": cid, "home": home}


@guard
def document_places(conn, actor: str | None, document_id: str) -> dict:
    """Where a document lives: its home and the links the member can see, plus its tags."""
    info = require_document(conn, actor, document_id, "read", via="workspaces")
    doc_id = document_id.upper()
    doc = one(conn, "SELECT document_id, home_kind, home_id, matter_id, folder_path, derived_from_document_id, "
                    "derived_from_version_id FROM documents WHERE document_id = %s", (doc_id,))
    matters = _visible_matter_ids(conn, actor)
    projects = visible_project_ids(conn, actor)
    kind, cid = home_of(doc)
    places = []
    if _can_see(kind, cid, actor, matters, projects):
        places.append({"kind": kind, "id": cid, "label": container_label(conn, kind, cid),
                       "folder": doc["folder_path"] or "", "home": True})
    else:
        places.append({"kind": kind, "home": True, "hidden": True})
    for l in rows(conn, "SELECT link_id, container_kind, container_id, folder_path, added_by, added_via, added_at "
                        "FROM document_links WHERE document_id = %s ORDER BY added_at", (doc_id,)):
        if _can_see(l["container_kind"], l["container_id"], actor, matters, projects):
            places.append({"kind": l["container_kind"], "id": l["container_id"], "link_id": l["link_id"],
                           "label": container_label(conn, l["container_kind"], l["container_id"]),
                           "folder": l["folder_path"], "home": False, "added_via": l["added_via"],
                           "added_at": l["added_at"]})
    derived = None
    if doc["derived_from_document_id"]:
        src = access.document_access(conn, actor, doc["derived_from_document_id"])
        if src["level"] != "none":
            title = one(conn, "SELECT title FROM documents WHERE document_id = %s", (doc["derived_from_document_id"],))
            derived = {"document_id": doc["derived_from_document_id"], "version_id": doc["derived_from_version_id"],
                       "title": title["title"] if title else None}
    return {"document_id": doc_id, "my_level": info["level"], "places": places, "derived_from": derived,
            "tags": document_tags(conn, actor, [doc_id]).get(doc_id, {"system": [], "user": []})}


# ── links ────────────────────────────────────────────────────────────────────

@guard
def link_document(conn, actor: str | None, document_id: str, kind: str, cid: str, folder: str | None = "",
                  via: str = "link") -> dict:
    """Show a document in another workspace. Needs read on the document and edit on the workspace."""
    doc_id = document_id.upper()
    require_document(conn, actor, doc_id, "read", via="link")
    require_container(conn, actor, kind, cid, "edit")
    doc = one(conn, "SELECT document_id, home_kind, home_id, matter_id, title FROM documents WHERE document_id = %s",
              (doc_id,))
    if home_of(doc) == (kind, cid):
        raise FirmError(409, "The document already lives in this workspace")
    folder = clean_path(folder)
    link = one(conn, """
        INSERT INTO document_links (document_id, container_kind, container_id, folder_path, added_by, added_via)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (document_id, container_kind, container_id) DO UPDATE SET folder_path = EXCLUDED.folder_path
        RETURNING link_id, (xmax = 0) AS created""", (doc_id, kind, cid, folder, actor, via))
    emit(conn, "document.linked", "document", doc_id, actor=actor, document_id=doc_id,
         matter_id=cid if kind == "matter" else None, payload={"kind": kind, "id": cid, "folder": folder})
    conn.commit()
    audit.record("document.link", member_id=actor, object_type="document", object_id=doc_id,
                 matter_id=doc["matter_id"], detail={"kind": kind, "id": cid, "folder": folder, "via": via})
    return {"link_id": link["link_id"], "created": link["created"], "document_id": doc_id, "kind": kind, "id": cid,
            "folder": folder}


@guard
def unlink_document(conn, actor: str | None, document_id: str, kind: str, cid: str) -> dict:
    """Remove a document from a workspace it is linked into (its home copy is untouched)."""
    doc_id = document_id.upper()
    check_kind(kind)
    link = one(conn, "SELECT link_id, added_by FROM document_links WHERE document_id = %s AND container_kind = %s "
                     "AND container_id = %s", (doc_id, kind, cid))
    if link is None:
        raise FirmError(404, "That document is not linked here")
    if not (actor is not None and link["added_by"] == actor
            and access.container_level(conn, actor, kind, cid) != "none"):
        require_container(conn, actor, kind, cid, "edit")
    conn.execute("DELETE FROM document_links WHERE link_id = %s", (link["link_id"],))
    emit(conn, "document.unlinked", "document", doc_id, actor=actor, document_id=doc_id,
         matter_id=cid if kind == "matter" else None, payload={"kind": kind, "id": cid})
    conn.commit()
    audit.record("document.unlink", member_id=actor, object_type="document", object_id=doc_id,
                 detail={"kind": kind, "id": cid})
    return {"document_id": doc_id, "kind": kind, "id": cid, "removed": True}


# ── moving a document's home (filing) ────────────────────────────────────────

@guard
def move_home(conn, actor: str | None, document_id: str, kind: str, cid: str, folder: str | None = "") -> dict:
    """Make another workspace the document's home: file a project or library document into a matter, or move a
    library document into a project. Matter documents stay in their matter (firm records). The old home keeps a
    link, so the document still shows there to those who can read it."""
    doc_id = document_id.upper()
    require_document(conn, actor, doc_id, "edit", via="move_home")
    require_container(conn, actor, kind, cid, "edit")
    doc = one(conn, "SELECT * FROM documents WHERE document_id = %s FOR UPDATE", (doc_id,))
    old = home_of(doc)
    if old == (kind, cid):
        raise FirmError(409, "The document already lives in this workspace")
    if doc["home_kind"] == "matter":
        raise FirmError(409, "A matter's documents stay in their matter; link it to show it elsewhere")
    if doc["home_kind"] == "firm":
        raise FirmError(409, "Firm templates stay in the template library; use New from template to make a working copy")
    if doc["home_kind"] == "project" and kind == "library":
        raise FirmError(409, "A project document can be filed into a matter, not taken into a personal library")
    folder = clean_path(folder)
    if kind == "matter":
        matter = one(conn, "SELECT matter_id, matter_code, client_id FROM matters WHERE matter_id = %s", (cid,))
        if doc["content_sha256"] and one(conn, "SELECT document_id FROM documents WHERE matter_id = %s "
                                               "AND content_sha256 = %s", (cid, doc["content_sha256"])):
            raise FirmError(409, "This matter already holds the same file; link that document instead")
        conn.execute("""UPDATE documents SET home_kind = 'matter', home_id = NULL, matter_id = %s, matter_code = %s,
                                             client_id = %s, folder_path = %s, updated_at = now()
                        WHERE document_id = %s""",
                     (cid, matter["matter_code"], matter["client_id"], folder, doc_id))
    else:
        conn.execute("""UPDATE documents SET home_kind = %s, home_id = %s, matter_id = NULL, matter_code = NULL,
                                             folder_path = %s, updated_at = now()
                        WHERE document_id = %s""", (kind, cid, folder, doc_id))
    conn.execute("UPDATE chunks SET matter_id = %s, folder_path = %s WHERE document_id = %s",
                 (cid if kind == "matter" else None, folder, doc_id))
    conn.execute("DELETE FROM document_links WHERE document_id = %s AND container_kind = %s AND container_id = %s",
                 (doc_id, kind, cid))
    conn.execute("""INSERT INTO document_links (document_id, container_kind, container_id, folder_path, added_by, added_via)
                    VALUES (%s, %s, %s, %s, %s, 'file_into') ON CONFLICT DO NOTHING""",
                 (doc_id, old[0], old[1], doc["folder_path"] or "", actor))
    emit(conn, "document.moved_home", "document", doc_id, actor=actor, document_id=doc_id,
         matter_id=cid if kind == "matter" else None,
         payload={"from": {"kind": old[0], "id": old[1]}, "to": {"kind": kind, "id": cid}})
    conn.commit()
    audit.record("document.file_into" if kind == "matter" else "document.move_home", member_id=actor,
                 object_type="document", object_id=doc_id, matter_id=cid if kind == "matter" else None,
                 detail={"from": {"kind": old[0], "id": old[1]}, "to": {"kind": kind, "id": cid}, "folder": folder})
    return document_places(conn, actor, doc_id)


# ── copies ───────────────────────────────────────────────────────────────────

@guard
def copy_document(conn, actor: str | None, document_id: str, kind: str, cid: str, folder: str | None = "",
                  title: str | None = None) -> dict:
    """A separate document with its own history, starting from the source's current version. The stored file is
    shared (versions are immutable), so a copy costs no storage until it is edited."""
    src_id = document_id.upper()
    require_document(conn, actor, src_id, "read", via="copy")
    require_container(conn, actor, kind, cid, "edit")
    src = one(conn, """SELECT d.*, v.version_id AS cur_version_id, v.version_number AS cur_version_number,
                              v.storage_uri AS cur_storage_uri, v.mime_type AS cur_mime, v.page_count AS cur_pages,
                              v.file_size_bytes AS cur_size
                       FROM documents d LEFT JOIN document_versions v ON v.version_id = d.current_version_id
                       WHERE d.document_id = %s""", (src_id,))
    folder = clean_path(folder)
    name = (title or "").strip() or src["title"]
    if len(name) > 300:
        raise FirmError(422, "title is limited to 300 characters")
    new_id = f"DOC-{uuid.uuid4().hex[:10].upper()}"
    matter = None
    if kind == "matter":
        matter = one(conn, "SELECT matter_id, matter_code, client_id FROM matters WHERE matter_id = %s", (cid,))
    author = one(conn, "SELECT name FROM members WHERE member_id = %s", (actor,)) if actor else None
    conn.execute(
        """INSERT INTO documents (document_id, matter_id, matter_code, client_id, title, document_type, body,
                                  author_id, author_name, doc_date, status, version, mime_type, folder_path,
                                  home_kind, home_id, derived_from_document_id, derived_from_version_id, source_uri)
           VALUES (%(id)s, %(mid)s, %(mcode)s, %(client)s, %(title)s, %(type)s, %(body)s, %(author_id)s,
                   %(author)s, CURRENT_DATE, 'Draft', 'v1.0', %(mime)s, %(folder)s, %(kind)s, %(home)s,
                   %(src)s, %(srcv)s, %(uri)s)""",
        {"id": new_id, "mid": cid if kind == "matter" else None, "mcode": matter["matter_code"] if matter else None,
         "client": matter["client_id"] if matter else src["client_id"], "title": name,
         "type": src["document_type"], "body": src["body"], "author_id": actor,
         "author": author["name"] if author else None, "mime": src["cur_mime"] or src["mime_type"], "folder": folder,
         "kind": kind, "home": None if kind == "matter" else cid, "src": src_id, "srcv": src["cur_version_id"],
         "uri": src["cur_storage_uri"] or src["source_uri"]})
    emit(conn, "document.copied", "document", new_id, actor=actor, document_id=new_id,
         matter_id=cid if kind == "matter" else None, payload={"from": src_id})
    conn.commit()
    from app.documents import create_version

    version = create_version(
        document_id=new_id, body=src["body"] or "", title=name,
        author_name=author["name"] if author else (actor or "copy"), source="copy", version_status="draft",
        change_summary=f"Copied from {src['title']} (v{src['cur_version_number'] or 1})",
        storage_uri=src["cur_storage_uri"], folder_path=folder)
    conn.execute("UPDATE document_versions SET page_count = %s, file_size_bytes = %s, mime_type = %s, "
                 "created_by_member_id = %s, origin = 'copy' WHERE version_id = %s",
                 (src["cur_pages"], src["cur_size"], src["cur_mime"], actor, version["version_id"]))
    conn.commit()
    try:
        from app.embeddings.pending import embed_pending_chunks

        embed_pending_chunks([new_id])
    except Exception:  # noqa: BLE001 — keyword search works; embed.py can backfill
        pass
    audit.record("document.copy", member_id=actor, object_type="document", object_id=new_id,
                 matter_id=cid if kind == "matter" else None,
                 detail={"from": src_id, "from_version": src["cur_version_id"], "kind": kind, "id": cid})
    return {"document_id": new_id, "title": name, "version_id": version["version_id"], "kind": kind, "id": cid,
            "derived_from": {"document_id": src_id, "version_id": src["cur_version_id"]}}


# ── folders ──────────────────────────────────────────────────────────────────

@guard
def create_folder(conn, actor: str | None, kind: str, cid: str, path: str) -> dict:
    require_container(conn, actor, kind, cid, "edit")
    path = clean_path(path)
    if not path:
        raise FirmError(422, "Name the folder")
    parts = path.split("/")
    for i in range(1, len(parts) + 1):
        conn.execute("INSERT INTO workspace_folders (container_kind, container_id, path, created_by) "
                     "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", (kind, cid, "/".join(parts[:i]), actor))
    conn.commit()
    audit.record("workspace.folder.create", member_id=actor, object_type=kind, object_id=cid, detail={"path": path})
    return {"kind": kind, "id": cid, "path": path}


@guard
def rename_folder(conn, actor: str | None, kind: str, cid: str, path: str, new_path: str) -> dict:
    """Rename or move a folder: everything under it follows (home documents, links, kept empty folders)."""
    require_container(conn, actor, kind, cid, "edit")
    path, new_path = clean_path(path), clean_path(new_path)
    if not path or not new_path:
        raise FirmError(422, "Name the folder")
    if new_path == path or new_path.startswith(path + "/"):
        raise FirmError(422, "A folder cannot be moved into itself")
    p = {"kind": kind, "cid": cid, "old": path, "new": new_path, "like": path + "/%"}
    swap = "%(new)s || substr({col}, char_length(%(old)s) + 1)"
    conn.execute(f"""UPDATE documents d SET folder_path = {swap.format(col='folder_path')}
                     WHERE {_home_where(kind)} AND (folder_path = %(old)s OR folder_path LIKE %(like)s)""", p)
    conn.execute(f"""UPDATE chunks c SET folder_path = {swap.format(col='c.folder_path')}
                     FROM documents d WHERE c.document_id = d.document_id AND {_home_where(kind)}
                       AND (c.folder_path = %(old)s OR c.folder_path LIKE %(like)s)""", p)
    conn.execute(f"""UPDATE document_links SET folder_path = {swap.format(col='folder_path')}
                     WHERE container_kind = %(kind)s AND container_id = %(cid)s
                       AND (folder_path = %(old)s OR folder_path LIKE %(like)s)""", p)
    conn.execute(f"""INSERT INTO workspace_folders (container_kind, container_id, path, created_by)
                     SELECT container_kind, container_id, {swap.format(col='path')}, created_by FROM workspace_folders
                     WHERE container_kind = %(kind)s AND container_id = %(cid)s AND (path = %(old)s OR path LIKE %(like)s)
                     ON CONFLICT DO NOTHING""", p)
    conn.execute("""DELETE FROM workspace_folders WHERE container_kind = %(kind)s AND container_id = %(cid)s
                    AND (path = %(old)s OR path LIKE %(like)s)""", p)
    parts = new_path.split("/")
    for i in range(1, len(parts)):
        conn.execute("INSERT INTO workspace_folders (container_kind, container_id, path, created_by) "
                     "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", (kind, cid, "/".join(parts[:i]), actor))
    conn.commit()
    audit.record("workspace.folder.rename", member_id=actor, object_type=kind, object_id=cid,
                 detail={"from": path, "to": new_path})
    return {"kind": kind, "id": cid, "path": new_path}


@guard
def delete_folder(conn, actor: str | None, kind: str, cid: str, path: str) -> dict:
    """Only empty folders are deleted (documents are moved or removed first)."""
    require_container(conn, actor, kind, cid, "edit")
    path = clean_path(path)
    p = {"kind": kind, "cid": cid, "old": path, "like": path + "/%"}
    used = one(conn, f"""SELECT (SELECT count(*) FROM documents d WHERE {_home_where(kind)} AND d.archived_at IS NULL
                                  AND (d.folder_path = %(old)s OR d.folder_path LIKE %(like)s))
                              + (SELECT count(*) FROM document_links WHERE container_kind = %(kind)s
                                  AND container_id = %(cid)s AND (folder_path = %(old)s OR folder_path LIKE %(like)s)) AS n""", p)
    if used["n"]:
        raise FirmError(409, f"The folder is not empty ({used['n']} documents)")
    conn.execute("DELETE FROM workspace_folders WHERE container_kind = %(kind)s AND container_id = %(cid)s "
                 "AND (path = %(old)s OR path LIKE %(like)s)", p)
    conn.commit()
    audit.record("workspace.folder.delete", member_id=actor, object_type=kind, object_id=cid, detail={"path": path})
    return {"kind": kind, "id": cid, "path": path, "deleted": True}


@guard
def place_in_folder(conn, actor: str | None, document_id: str, kind: str, cid: str, folder: str | None) -> dict:
    """Move a document to another folder of one workspace (its home folder, or where it is linked)."""
    doc_id = document_id.upper()
    require_container(conn, actor, kind, cid, "edit")
    require_document(conn, actor, doc_id, "read", via="folder")
    folder = clean_path(folder)
    doc = one(conn, "SELECT home_kind, home_id, matter_id FROM documents WHERE document_id = %s", (doc_id,))
    if home_of(doc) == (kind, cid):
        conn.execute("UPDATE documents SET folder_path = %s, updated_at = now() WHERE document_id = %s", (folder, doc_id))
        conn.execute("UPDATE chunks SET folder_path = %s WHERE document_id = %s", (folder, doc_id))
    else:
        moved = one(conn, "UPDATE document_links SET folder_path = %s WHERE document_id = %s AND container_kind = %s "
                          "AND container_id = %s RETURNING link_id", (folder, doc_id, kind, cid))
        if moved is None:
            raise FirmError(404, "That document is not in this workspace")
    conn.commit()
    audit.record("document.folder.move", member_id=actor, object_type="document", object_id=doc_id,
                 detail={"kind": kind, "id": cid, "folder": folder})
    return {"document_id": doc_id, "kind": kind, "id": cid, "folder": folder}


# ── people's tags ────────────────────────────────────────────────────────────

def _tag(value: Any) -> str:
    tag = " ".join(str(value or "").strip().lower().split())
    if not tag or len(tag) > MAX_TAG:
        raise FirmError(422, f"A tag is 1–{MAX_TAG} characters")
    if ":" in tag:
        raise FirmError(422, "Tags with ':' are reserved for where a document lives")
    return tag


@guard
def add_tag(conn, actor: str | None, document_id: str, tag: str) -> dict:
    doc_id = document_id.upper()
    require_document(conn, actor, doc_id, "edit", via="tags")
    tag = _tag(tag)
    conn.execute("INSERT INTO document_tags (document_id, tag, created_by) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                 (doc_id, tag, actor))
    conn.commit()
    audit.record("document.tag.add", member_id=actor, object_type="document", object_id=doc_id, detail={"tag": tag})
    return document_tags(conn, actor, [doc_id])[doc_id]


@guard
def remove_tag(conn, actor: str | None, document_id: str, tag: str) -> dict:
    doc_id = document_id.upper()
    require_document(conn, actor, doc_id, "edit", via="tags")
    conn.execute("DELETE FROM document_tags WHERE document_id = %s AND tag = %s", (doc_id, _tag(tag)))
    conn.commit()
    audit.record("document.tag.remove", member_id=actor, object_type="document", object_id=doc_id, detail={"tag": _tag(tag)})
    return document_tags(conn, actor, [doc_id])[doc_id]


@guard
def tag_suggestions(conn, actor: str | None, prefix: str = "", limit: int = 20) -> list[dict]:
    """Tags in use on documents the member can read, most used first."""
    return rows(conn, f"""
        SELECT t.tag, count(*) AS n FROM document_tags t
        JOIN documents d ON d.document_id = t.document_id
        LEFT JOIN permissions p ON p.matter_id = d.matter_id
        WHERE t.tag LIKE %(prefix)s AND d.archived_at IS NULL AND {doc_read('d')}
        GROUP BY t.tag ORDER BY n DESC, t.tag LIMIT %(limit)s""",
        {"prefix": _like_prefix(prefix), "limit": limit, "member_id": actor})


def _like_prefix(prefix: str) -> str:
    p = (prefix or "").strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return p + "%"


# ── duplicates before upload ─────────────────────────────────────────────────

@guard
def check_duplicates(conn, actor: str | None, hashes: list[str], kind: str, cid: str) -> dict:
    """For each file hash: documents with the same file the member can already read, so the upload can link the
    existing document instead of storing a second one. Only readable documents are ever named."""
    require_container(conn, actor, kind, cid, "edit")
    clean = sorted({h.lower() for h in hashes if isinstance(h, str) and len(h) == 64
                    and all(c in "0123456789abcdef" for c in h.lower())})[:500]
    if not clean:
        return {"matches": {}}
    found = rows(conn, f"""
        SELECT d.document_id, d.title, d.content_sha256, d.home_kind, d.home_id, d.matter_id, d.folder_path,
               EXISTS (SELECT 1 FROM document_links l WHERE l.document_id = d.document_id
                       AND l.container_kind = %(kind)s AND l.container_id = %(cid)s) AS linked_here
        FROM documents d LEFT JOIN permissions p ON p.matter_id = d.matter_id
        WHERE d.content_sha256 = ANY(%(h)s) AND d.archived_at IS NULL AND {doc_read('d')}
        ORDER BY d.updated_at DESC""", {"h": clean, "kind": kind, "cid": cid, "member_id": actor})
    matches: dict[str, list[dict]] = {}
    for d in found:
        here = home_of(d) == (kind, cid) or d.pop("linked_here")
        d.pop("linked_here", None)
        hkind, hid = home_of(d)
        bucket = matches.setdefault(d["content_sha256"], [])
        if len(bucket) < 5:
            bucket.append({"document_id": d["document_id"], "title": d["title"], "already_here": bool(here),
                           "home": {"kind": hkind, "id": hid, "label": container_label(conn, hkind, hid)}})
    return {"matches": matches}


# ── search inside one workspace ──────────────────────────────────────────────

@guard
def search_workspace(conn, actor: str | None, kind: str, cid: str, q: str, limit: int = 30) -> dict:
    """Documents of one workspace (home or linked, readable) by title or by words inside them, with the best
    passage and its page, so a hit opens where it matched."""
    require_container(conn, actor, kind, cid, "read")
    text = (q or "").strip()
    if len(text) < 2:
        return {"query": text, "results": []}
    params = {"kind": kind, "cid": cid, "member_id": actor, "q": text, "like": f"%{text}%", "limit": limit}
    results = rows(conn, f"""
        WITH scope AS (
            SELECT d.document_id FROM documents d WHERE {_home_where(kind)}
            UNION SELECT l.document_id FROM document_links l
                  WHERE l.container_kind = %(kind)s AND l.container_id = %(cid)s
        ),
        readable AS (
            SELECT d.document_id, d.title, d.document_type, d.folder_path, d.current_version_id
            FROM scope s JOIN documents d ON d.document_id = s.document_id
            LEFT JOIN permissions p ON p.matter_id = d.matter_id
            WHERE d.archived_at IS NULL AND {doc_read('d')}
        ),
        tq AS (SELECT websearch_to_tsquery('english', %(q)s) AS tq),
        hits AS (
            SELECT DISTINCT ON (c.document_id) c.document_id, c.chunk_id, c.page_number, c.text,
                   ts_rank_cd(c.tsv_full, tq.tq) AS rank
            FROM chunks c JOIN readable r ON r.document_id = c.document_id, tq
            WHERE c.tsv_full @@ tq.tq AND NOT coalesce(c.is_parent, false)
              AND (c.version_id IS NULL OR c.version_id = r.current_version_id)
            ORDER BY c.document_id, rank DESC
        )
        SELECT r.document_id, r.title, r.document_type, r.folder_path,
               (r.title ILIKE %(like)s) AS title_hit, h.chunk_id, h.page_number, h.rank,
               CASE WHEN h.text IS NULL THEN NULL ELSE ts_headline('english', h.text, (SELECT tq FROM tq),
                   'StartSel={{MARK_START}}, StopSel={{MARK_END}}, MaxWords=26, MinWords=10, MaxFragments=1') END AS snippet
        FROM readable r LEFT JOIN hits h ON h.document_id = r.document_id
        WHERE r.title ILIKE %(like)s OR h.document_id IS NOT NULL
        ORDER BY title_hit DESC, h.rank DESC NULLS LAST, lower(r.title)
        LIMIT %(limit)s""", params)
    for r in results:
        r["match_kind"] = "title" if r.pop("title_hit") else "content"
    return {"query": text, "results": results}
