"""Projects router — enhanced with folders, document assignment, versioning, activity, export.

Endpoints:
  Projects:
    GET    /                              — list projects (ACL-filtered)
    POST   /                              — create project
    GET    /{project_id}                  — project detail + team + folders + recent activity
    PATCH  /{project_id}                  — update project metadata
    DELETE /{project_id}                  — delete project

  Milestones:
    PATCH  /{project_id}/milestones                — toggle milestone by body
    PATCH  /{project_id}/milestones/{idx}          — toggle milestone by index

  Folders:
    POST   /{project_id}/folders                    — create folder
    GET    /{project_id}/directory                   — folder tree with doc counts
    PATCH  /{project_id}/folders/{folder_id}         — rename / move (with cycle detection)
    DELETE /{project_id}/folders/{folder_id}          — delete folder (cascade docs)

  Documents in Project:
    GET    /{project_id}/documents                   — list project documents
    POST   /{project_id}/documents/{document_id}     — assign/copy document into project
    PATCH  /{project_id}/documents/{document_id}/folder — move doc to folder

  Activity:
    GET    /{project_id}/activity                    — paginated timeline

  Export:
    GET    /{project_id}/export                      — downloadable manifest
"""
import hashlib
import json
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row

from app.api.acl import ACL_CLAUSE
from app.api.schemas import (
    ProjectCreate,
    ProjectMilestoneUpdate,
    MilestoneToggleRequest,
    FolderCreate,
    FolderUpdate,
    DocumentFolderMove,
)
from app.auth.deps import resolve_member
from app.db.connection import connect
from app.projects import record_activity

router = APIRouter(tags=["projects"])

# ── Helpers ─────────────────────────────────────────────────────────────────


def _project_payload(row: dict, matter: dict | None = None) -> dict:
    return {
        "id": row["project_id"],
        "project_id": row["project_id"],
        "matter_id": row["matter_id"],
        "matter_code": (matter or {}).get("matter_code", ""),
        "matter_title": (matter or {}).get("title", ""),
        "client_id": (matter or {}).get("client_id", ""),
        "client_name": (matter or {}).get("client_name", ""),
        "title": row["title"],
        "team": row["practice_team"],
        "practice_team": row["practice_team"],
        "lead_id": row.get("lead_member_id"),
        "lead_lawyer": row.get("lead_lawyer") or "",
        "status": row.get("status") or "In Progress",
        "progress": row.get("progress") or 0,
        "deadline": str(row["deadline"]) if row.get("deadline") else None,
        "scope": row.get("scope") or "",
        "milestones": row.get("milestones") or [],
        "quantum": (matter or {}).get("claim_amount", "—"),
        "service": "projects",
    }


def _matter_from_row(row: dict) -> dict:
    return {
        "matter_code": row.get("matter_code"),
        "title": row.get("matter_title"),
        "client_id": row.get("client_id"),
        "client_name": row.get("client_name"),
        "claim_amount": row.get("claim_amount"),
    }


def _check_project_access(cur, project_id: str, member_id: str | None) -> dict:
    """Verify project exists and ACL allows access. Returns the project row."""
    params = {"project_id": project_id, "member_id": member_id}
    sql = f"""
        SELECT pr.*, m.matter_code, m.title AS matter_title, m.client_id,
               m.client_name, m.claim_amount
        FROM projects pr
        JOIN matters m ON m.matter_id = pr.matter_id
        LEFT JOIN permissions p2 ON p2.matter_id = pr.matter_id
        WHERE pr.project_id = %(project_id)s AND {ACL_CLAUSE.replace('p.', 'p2.')}
    """
    cur.execute(sql, params)
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found or access denied")
    return row


# ── Core CRUD ───────────────────────────────────────────────────────────────


@router.get("/health")
def projects_health() -> dict:
    return {"service": "projects", "status": "ok"}


@router.get("")
def projects_endpoint(
    matter_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    member_id: str | None = Depends(resolve_member),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    params: dict = {"member_id": member_id, "limit": limit, "offset": offset}
    wheres = [ACL_CLAUSE.replace("p.", "p2.")]
    if matter_id:
        wheres.append("pr.matter_id = %(matter_id)s")
        params["matter_id"] = matter_id
    if status:
        wheres.append("pr.status = %(status)s")
        params["status"] = status
    where = " AND ".join(wheres)
    sql = f"""
        SELECT pr.*, m.matter_code, m.title AS matter_title, m.client_id,
               m.client_name, m.claim_amount
        FROM projects pr
        JOIN matters m ON m.matter_id = pr.matter_id
        LEFT JOIN permissions p2 ON p2.matter_id = pr.matter_id
        WHERE {where}
        ORDER BY pr.deadline DESC NULLS LAST, pr.project_id
        LIMIT %(limit)s OFFSET %(offset)s
    """
    count_sql = f"""
        SELECT COUNT(*) AS n FROM projects pr
        LEFT JOIN permissions p2 ON p2.matter_id = pr.matter_id
        WHERE {where}
    """
    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = list(cur.fetchall())
            cur.execute(count_sql, count_params)
            total = cur.fetchone()["n"]
    items = [_project_payload(r, _matter_from_row(r)) for r in rows]
    return {"service": "projects", "total": total, "items": items}


@router.get("/{project_id}")
def project_detail_endpoint(
    project_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            row = _check_project_access(cur, project_id, member_id)

            # Documents
            cur.execute(
                """
                SELECT document_id, title, document_type, author_name,
                       doc_date, status, folder_id, current_version_id
                FROM documents WHERE matter_id = %(matter_id)s
                ORDER BY doc_date DESC NULLS LAST LIMIT 50
                """,
                {"matter_id": row["matter_id"]},
            )
            docs = list(cur.fetchall())

            # Team members
            cur.execute(
                """
                SELECT mm.member_id, m.name, m.role, mm.role_on_matter
                FROM matter_members mm
                JOIN members m ON m.member_id = mm.member_id
                WHERE mm.matter_id = %(matter_id)s
                """,
                {"matter_id": row["matter_id"]},
            )
            team = list(cur.fetchall())

            # Folders
            cur.execute(
                "SELECT * FROM project_folders WHERE project_id = %(pid)s ORDER BY name",
                {"pid": project_id},
            )
            folders = list(cur.fetchall())

            # Recent activity
            cur.execute(
                """
                SELECT * FROM project_activity
                WHERE project_id = %(pid)s
                ORDER BY created_at DESC LIMIT 10
                """,
                {"pid": project_id},
            )
            recent_activity = list(cur.fetchall())

            # Document count
            cur.execute(
                "SELECT COUNT(*) AS n FROM documents WHERE matter_id = %(mid)s",
                {"mid": row["matter_id"]},
            )
            doc_count = cur.fetchone()["n"]

    payload = _project_payload(row, _matter_from_row(row))
    payload["documents"] = docs
    payload["team"] = team
    payload["folders"] = folders
    payload["recent_activity"] = recent_activity
    payload["document_count"] = doc_count
    return payload


@router.post("")
def create_project_endpoint(
    body: ProjectCreate,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    project_id = f"PRJ-{uuid.uuid4().hex[:8].upper()}"
    milestones = body.milestones or [
        {"title": "Kickoff & scope review", "done": False, "due": str(date.today() + timedelta(days=14))},
        {"title": "Drafting & delivery", "done": False, "due": body.deadline or str(date.today() + timedelta(days=30))},
    ]
    params = {
        "project_id": project_id,
        "matter_id": body.matter_id,
        "title": body.title,
        "practice_team": body.practice_team,
        "lead_member_id": body.lead_member_id,
        "lead_lawyer": body.lead_lawyer,
        "deadline": body.deadline,
        "scope": body.scope or "",
        "milestones": milestones,
        "member_id": member_id,
    }
    access_sql = f"""
        SELECT 1 FROM matters m
        LEFT JOIN permissions p ON p.matter_id = m.matter_id
        WHERE m.matter_id = %(matter_id)s AND {ACL_CLAUSE}
    """
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(access_sql, params)
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Matter not found or access denied")
            cur.execute(
                """
                INSERT INTO projects (
                    project_id, matter_id, title, practice_team, lead_member_id,
                    lead_lawyer, status, progress, deadline, scope, milestones
                ) VALUES (
                    %(project_id)s, %(matter_id)s, %(title)s, %(practice_team)s,
                    %(lead_member_id)s, %(lead_lawyer)s, 'In Progress', 0,
                    %(deadline)s, %(scope)s, %(milestones)s::jsonb
                )
                RETURNING project_id
                """,
                {**params, "milestones": json.dumps(milestones)},
            )
            record_activity(project_id, "project.created", actor_id=member_id,
                            target_title=body.title, cur=cur)
            conn.commit()
    return project_detail_endpoint(project_id, member_id)


@router.patch("/{project_id}")
def update_project_endpoint(
    project_id: str,
    body: dict,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    allowed = {"title", "scope", "deadline", "lead_member_id", "lead_lawyer", "practice_team", "status"}
    updates = {k: v for k, v in body.items() if k in allowed and v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    set_clauses = ", ".join(f"{k} = %({k})s" for k in updates)
    params = {**updates, "project_id": project_id, "member_id": member_id}

    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            _check_project_access(cur, project_id, member_id)
            cur.execute(
                f"UPDATE projects SET {set_clauses} WHERE project_id = %(project_id)s",
                params,
            )
            record_activity(project_id, "project.updated", actor_id=member_id,
                            metadata=updates, cur=cur)
            conn.commit()
    return project_detail_endpoint(project_id, member_id)


@router.delete("/{project_id}")
def delete_project_endpoint(
    project_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            _check_project_access(cur, project_id, member_id)
            cur.execute("DELETE FROM projects WHERE project_id = %(pid)s", {"pid": project_id})
            conn.commit()
    return {"service": "projects", "status": "deleted", "project_id": project_id}


# ── Milestones ──────────────────────────────────────────────────────────────


@router.patch("/{project_id}/milestones/{milestone_index}")
def update_project_milestone_by_path(
    project_id: str,
    milestone_index: int,
    body: MilestoneToggleRequest,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    update = ProjectMilestoneUpdate(milestone_index=milestone_index, done=body.done)
    return update_project_milestone_endpoint(project_id, update, member_id)


@router.patch("/{project_id}/milestones")
def update_project_milestone_endpoint(
    project_id: str,
    body: ProjectMilestoneUpdate,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            row = _check_project_access(cur, project_id, member_id)
            milestones = list(row["milestones"] or [])
            if body.milestone_index < 0 or body.milestone_index >= len(milestones):
                raise HTTPException(status_code=400, detail="Invalid milestone index")
            milestones[body.milestone_index]["done"] = body.done
            done = sum(1 for m in milestones if m.get("done"))
            progress = round(100 * done / len(milestones)) if milestones else 0
            status = "Completed" if progress == 100 else "In Progress"
            cur.execute(
                """
                UPDATE projects SET milestones = %(milestones)s::jsonb,
                    progress = %(progress)s, status = %(status)s
                WHERE project_id = %(project_id)s
                """,
                {
                    "milestones": json.dumps(milestones),
                    "progress": progress,
                    "status": status,
                    "project_id": project_id,
                },
            )
            record_activity(
                project_id, "milestone.toggled", actor_id=member_id,
                target_title=milestones[body.milestone_index].get("title"),
                metadata={"index": body.milestone_index, "done": body.done},
                cur=cur,
            )
            conn.commit()
    return project_detail_endpoint(project_id, member_id)


# ── Folders ─────────────────────────────────────────────────────────────────

MAX_FOLDER_DEPTH = 5


def _check_folder_depth(cur, project_id: str, parent_folder_id: str | None) -> int:
    """Walk up the tree to count depth. Raise if exceeding MAX_FOLDER_DEPTH."""
    depth = 1
    current = parent_folder_id
    while current:
        if depth > MAX_FOLDER_DEPTH:
            raise HTTPException(status_code=400, detail=f"Maximum folder depth of {MAX_FOLDER_DEPTH} exceeded")
        cur.execute(
            "SELECT parent_folder_id FROM project_folders WHERE folder_id = %(fid)s AND project_id = %(pid)s",
            {"fid": current, "pid": project_id},
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Parent folder not found")
        current = row["parent_folder_id"]
        depth += 1
    return depth


def _check_cycle(cur, project_id: str, folder_id: str, new_parent_id: str | None) -> None:
    """Ensure moving folder_id under new_parent_id doesn't create a cycle."""
    if not new_parent_id:
        return
    current = new_parent_id
    while current:
        if current == folder_id:
            raise HTTPException(status_code=400, detail="Cannot move a folder into itself or a descendant")
        cur.execute(
            "SELECT parent_folder_id FROM project_folders WHERE folder_id = %(fid)s AND project_id = %(pid)s",
            {"fid": current, "pid": project_id},
        )
        row = cur.fetchone()
        if not row:
            break
        current = row["parent_folder_id"]


@router.post("/{project_id}/folders")
def create_folder(
    project_id: str,
    body: FolderCreate,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    folder_id = f"FLD-{uuid.uuid4().hex[:8].upper()}"
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            _check_project_access(cur, project_id, member_id)

            if body.parent_folder_id:
                _check_folder_depth(cur, project_id, body.parent_folder_id)

            cur.execute(
                """
                INSERT INTO project_folders (folder_id, project_id, name, parent_folder_id, created_by)
                VALUES (%(fid)s, %(pid)s, %(name)s, %(parent)s, %(creator)s)
                RETURNING *
                """,
                {
                    "fid": folder_id,
                    "pid": project_id,
                    "name": body.name.strip(),
                    "parent": body.parent_folder_id,
                    "creator": member_id,
                },
            )
            folder = cur.fetchone()
            record_activity(project_id, "folder.created", actor_id=member_id,
                            target_id=folder_id, target_title=body.name, cur=cur)
            conn.commit()
    return {"service": "projects", **dict(folder)}


@router.get("/{project_id}/directory")
def project_directory(
    project_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            row = _check_project_access(cur, project_id, member_id)

            cur.execute(
                "SELECT * FROM project_folders WHERE project_id = %(pid)s ORDER BY name",
                {"pid": project_id},
            )
            folders = list(cur.fetchall())

            # Count docs per folder
            cur.execute(
                """
                SELECT COALESCE(d.folder_id, '__root__') AS fid, COUNT(*) AS n
                FROM documents d
                WHERE d.matter_id = %(mid)s
                GROUP BY d.folder_id
                """,
                {"mid": row["matter_id"]},
            )
            counts = {r["fid"]: r["n"] for r in cur.fetchall()}

    # Build tree
    by_id = {f["folder_id"]: {**dict(f), "children": [], "document_count": counts.get(f["folder_id"], 0)} for f in folders}
    roots = []
    for f in by_id.values():
        parent = f.get("parent_folder_id")
        if parent and parent in by_id:
            by_id[parent]["children"].append(f)
        else:
            roots.append(f)

    return {
        "service": "projects",
        "project_id": project_id,
        "root_document_count": counts.get("__root__", 0),
        "folder_tree": roots,
    }


@router.patch("/{project_id}/folders/{folder_id}")
def update_folder(
    project_id: str,
    folder_id: str,
    body: FolderUpdate,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            _check_project_access(cur, project_id, member_id)

            # Verify folder exists
            cur.execute(
                "SELECT * FROM project_folders WHERE folder_id = %(fid)s AND project_id = %(pid)s",
                {"fid": folder_id, "pid": project_id},
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Folder not found")

            updates = {}
            if body.name is not None:
                updates["name"] = body.name.strip()
            if body.parent_folder_id is not None:
                _check_cycle(cur, project_id, folder_id, body.parent_folder_id or None)
                if body.parent_folder_id:
                    _check_folder_depth(cur, project_id, body.parent_folder_id)
                updates["parent_folder_id"] = body.parent_folder_id or None

            if not updates:
                raise HTTPException(status_code=400, detail="No valid fields to update")

            set_clauses = ", ".join(f"{k} = %({k})s" for k in updates)
            cur.execute(
                f"UPDATE project_folders SET {set_clauses}, updated_at = NOW() WHERE folder_id = %(fid)s AND project_id = %(pid)s RETURNING *",
                {**updates, "fid": folder_id, "pid": project_id},
            )
            folder = cur.fetchone()
            record_activity(project_id, "folder.updated", actor_id=member_id,
                            target_id=folder_id, metadata=updates, cur=cur)
            conn.commit()
    return {"service": "projects", **dict(folder)}


@router.delete("/{project_id}/folders/{folder_id}")
def delete_folder(
    project_id: str,
    folder_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            _check_project_access(cur, project_id, member_id)

            cur.execute(
                "SELECT * FROM project_folders WHERE folder_id = %(fid)s AND project_id = %(pid)s",
                {"fid": folder_id, "pid": project_id},
            )
            folder = cur.fetchone()
            if not folder:
                raise HTTPException(status_code=404, detail="Folder not found")

            # Collect all descendant folder IDs
            folder_ids = set()
            stack = [folder_id]
            while stack:
                fid = stack.pop()
                if fid in folder_ids:
                    continue
                folder_ids.add(fid)
                cur.execute(
                    "SELECT folder_id FROM project_folders WHERE parent_folder_id = %(fid)s AND project_id = %(pid)s",
                    {"fid": fid, "pid": project_id},
                )
                stack.extend(r["folder_id"] for r in cur.fetchall())

            # Unassign documents from these folders (don't delete the documents themselves)
            if folder_ids:
                cur.execute(
                    "UPDATE documents SET folder_id = NULL WHERE folder_id = ANY(%(fids)s)",
                    {"fids": list(folder_ids)},
                )

            # Delete the folder (CASCADE handles children via FK)
            cur.execute(
                "DELETE FROM project_folders WHERE folder_id = %(fid)s AND project_id = %(pid)s",
                {"fid": folder_id, "pid": project_id},
            )
            record_activity(project_id, "folder.deleted", actor_id=member_id,
                            target_id=folder_id, target_title=folder["name"], cur=cur)
            conn.commit()
    return {"service": "projects", "status": "deleted", "folder_id": folder_id}


# ── Documents in Project ────────────────────────────────────────────────────


@router.get("/{project_id}/documents")
def project_documents(
    project_id: str,
    folder_id: str | None = Query(default=None),
    member_id: str | None = Depends(resolve_member),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            row = _check_project_access(cur, project_id, member_id)

            wheres = ["d.matter_id = %(mid)s"]
            params: dict = {"mid": row["matter_id"], "limit": limit, "offset": offset}
            if folder_id:
                wheres.append("d.folder_id = %(folder_id)s")
                params["folder_id"] = folder_id
            elif folder_id == "":
                wheres.append("d.folder_id IS NULL")

            where = " AND ".join(wheres)
            cur.execute(
                f"""
                SELECT d.document_id, d.title, d.document_type, d.author_name,
                       d.doc_date, d.status, d.version, d.folder_id, d.current_version_id,
                       (SELECT COUNT(*) FROM document_versions dv WHERE dv.document_id = d.document_id) AS version_count,
                       (SELECT dv.version_status FROM document_versions dv
                        WHERE dv.version_id = d.current_version_id) AS version_status
                FROM documents d WHERE {where}
                ORDER BY d.doc_date DESC NULLS LAST
                LIMIT %(limit)s OFFSET %(offset)s
                """,
                params,
            )
            docs = list(cur.fetchall())

            count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
            cur.execute(f"SELECT COUNT(*) AS n FROM documents d WHERE {where}", count_params)
            total = cur.fetchone()["n"]

    return {"service": "projects", "project_id": project_id, "total": total, "documents": docs}


@router.post("/{project_id}/documents/{document_id}")
def assign_document_to_project(
    project_id: str,
    document_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    """Assign a document to this project's matter. If the document already belongs
    to a different matter, it's a cross-matter copy (creates a new document row)."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            row = _check_project_access(cur, project_id, member_id)
            project_matter = row["matter_id"]

            cur.execute(
                "SELECT * FROM documents WHERE document_id = %(did)s",
                {"did": document_id.upper()},
            )
            doc = cur.fetchone()
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found")

            if doc["matter_id"] == project_matter:
                # Already in this project's matter — idempotent, just update folder
                return {"service": "projects", "status": "already_assigned", "document_id": document_id}

            # Cross-matter: create a copy
            cur.execute("SELECT COUNT(*) AS n FROM documents")
            count_row = cur.fetchone()
            new_doc_id = f"DOC-{(count_row['n'] + 1):05d}"

            cur.execute(
                """
                INSERT INTO documents (
                    document_id, matter_id, matter_code, client_id, title,
                    document_type, author_name, doc_date, status, version, body
                )
                SELECT %(new_id)s, %(new_matter)s, %(matter_code)s, %(client_id)s,
                       title, document_type, author_name, doc_date, status, version, body
                FROM documents WHERE document_id = %(old_id)s
                RETURNING document_id
                """,
                {
                    "new_id": new_doc_id,
                    "new_matter": project_matter,
                    "matter_code": row.get("matter_code"),
                    "client_id": row.get("client_id"),
                    "old_id": document_id.upper(),
                },
            )
            record_activity(
                project_id, "document.copied", actor_id=member_id,
                target_id=new_doc_id, target_title=doc["title"],
                metadata={"source_document_id": document_id},
                cur=cur,
            )
            conn.commit()

    return {"service": "projects", "status": "copied", "document_id": new_doc_id, "source_document_id": document_id}


@router.patch("/{project_id}/documents/{document_id}/folder")
def move_document_to_folder(
    project_id: str,
    document_id: str,
    body: DocumentFolderMove,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            row = _check_project_access(cur, project_id, member_id)

            # Verify document belongs to this project's matter
            cur.execute(
                "SELECT document_id, title FROM documents WHERE document_id = %(did)s AND matter_id = %(mid)s",
                {"did": document_id.upper(), "mid": row["matter_id"]},
            )
            doc = cur.fetchone()
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found in this project")

            # Verify target folder exists (if specified)
            if body.folder_id:
                cur.execute(
                    "SELECT folder_id FROM project_folders WHERE folder_id = %(fid)s AND project_id = %(pid)s",
                    {"fid": body.folder_id, "pid": project_id},
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Folder not found")

            cur.execute(
                "UPDATE documents SET folder_id = %(fid)s, updated_at = NOW() WHERE document_id = %(did)s",
                {"fid": body.folder_id, "did": document_id.upper()},
            )
            record_activity(
                project_id, "document.moved", actor_id=member_id,
                target_id=document_id, target_title=doc["title"],
                metadata={"folder_id": body.folder_id},
                cur=cur,
            )
            conn.commit()

    return {"service": "projects", "status": "moved", "document_id": document_id, "folder_id": body.folder_id}


# ── Activity ────────────────────────────────────────────────────────────────


@router.get("/{project_id}/activity")
def project_activity_endpoint(
    project_id: str,
    member_id: str | None = Depends(resolve_member),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            _check_project_access(cur, project_id, member_id)
            cur.execute(
                """
                SELECT pa.*, m.name AS actor_name
                FROM project_activity pa
                LEFT JOIN members m ON m.member_id = pa.actor_id
                WHERE pa.project_id = %(pid)s
                ORDER BY pa.created_at DESC
                LIMIT %(limit)s OFFSET %(offset)s
                """,
                {"pid": project_id, "limit": limit, "offset": offset},
            )
            items = list(cur.fetchall())
            cur.execute(
                "SELECT COUNT(*) AS n FROM project_activity WHERE project_id = %(pid)s",
                {"pid": project_id},
            )
            total = cur.fetchone()["n"]
    return {"service": "projects", "project_id": project_id, "total": total, "activity": items}


# ── Export ──────────────────────────────────────────────────────────────────


@router.get("/{project_id}/export")
def project_export(
    project_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    """Export project manifest with document hashes for integrity verification."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            row = _check_project_access(cur, project_id, member_id)

            # Documents with versions
            cur.execute(
                """
                SELECT d.document_id, d.title, d.document_type, d.author_name,
                       d.doc_date, d.status, d.version, d.content_sha256,
                       d.current_version_id
                FROM documents d WHERE d.matter_id = %(mid)s
                ORDER BY d.doc_date DESC NULLS LAST
                """,
                {"mid": row["matter_id"]},
            )
            docs = list(cur.fetchall())

            # Version history per document
            doc_ids = [d["document_id"] for d in docs]
            versions_by_doc: dict[str, list] = {}
            if doc_ids:
                cur.execute(
                    """
                    SELECT version_id, document_id, version_number, title,
                           content_sha256, author_name, source, created_at
                    FROM document_versions
                    WHERE document_id = ANY(%(ids)s)
                    ORDER BY document_id, version_number DESC
                    """,
                    {"ids": doc_ids},
                )
                for v in cur.fetchall():
                    versions_by_doc.setdefault(v["document_id"], []).append(dict(v))

            # Folders
            cur.execute(
                "SELECT * FROM project_folders WHERE project_id = %(pid)s ORDER BY name",
                {"pid": project_id},
            )
            folders = list(cur.fetchall())

    for d in docs:
        d["versions"] = versions_by_doc.get(d["document_id"], [])

    # Build manifest digest
    manifest_content = json.dumps(
        {"documents": docs, "milestones": row.get("milestones", [])},
        sort_keys=True, default=str,
    )
    manifest_sha = hashlib.sha256(manifest_content.encode()).hexdigest()

    return {
        "service": "projects",
        "export": {
            "project_id": project_id,
            "title": row["title"],
            "matter_id": row["matter_id"],
            "matter_code": row.get("matter_code"),
            "exported_at": str(date.today()),
            "manifest_sha256": manifest_sha,
            "documents": docs,
            "folders": [dict(f) for f in folders],
            "milestones": row.get("milestones", []),
            "team": [],  # Already populated in detail; omitted here for size
        },
    }
