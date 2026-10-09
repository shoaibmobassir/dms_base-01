"""Projects: free workspaces anyone can create, with their own members (owner / editor / viewer).

A project may be linked to a matter for context; it does not inherit the matter's members, and the matter's
documents shown in it keep the matter's access rules (a link never widens access).
"""
from __future__ import annotations

from typing import Any

from app import access
from app.audit import events as audit
from app.firm import FirmError, check_version, emit, guard, one
from app.workspaces import require_container, rows

ROLES = ("owner", "editor", "viewer")
MAX_TITLE = 200
MAX_DESCRIPTION = 4000


def _title(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise FirmError(422, "title is required")
    if len(text) > MAX_TITLE:
        raise FirmError(422, f"title is limited to {MAX_TITLE} characters")
    return text


def _description(value: Any) -> str | None:
    text = str(value or "").strip()
    if len(text) > MAX_DESCRIPTION:
        raise FirmError(422, f"description is limited to {MAX_DESCRIPTION} characters")
    return text or None


def _linked_matter(conn, actor: str | None, matter_id: str | None) -> str | None:
    """A project may name a matter the actor can see; it gains nothing from it but context."""
    if not matter_id:
        return None
    if access.container_level(conn, actor, "matter", matter_id) == "none":
        raise FirmError(422, "Choose a matter you can see")
    return matter_id


def _visible_matter(conn, actor: str | None, matter_id: str | None) -> dict | None:
    if not matter_id or access.container_level(conn, actor, "matter", matter_id) == "none":
        return None
    return one(conn, "SELECT matter_id, matter_code, title FROM matters WHERE matter_id = %s", (matter_id,))


def _event(conn, topic: str, project_id: str, actor: str | None, payload: dict | None = None) -> None:
    emit(conn, topic, "project", project_id, actor=actor, payload=payload)


# ── create / read ────────────────────────────────────────────────────────────

@guard
def create_project(conn, actor: str | None, data: dict) -> dict:
    """Anyone may create a project; the creator owns it."""
    title = _title(data.get("title"))
    description = _description(data.get("description"))
    matter_id = _linked_matter(conn, actor, data.get("matter_id"))
    number = one(conn, "SELECT nextval('project_id_seq') AS n")["n"]
    project_id = f"PRJ-{number:05d}"
    conn.execute(
        """INSERT INTO projects (project_id, matter_id, title, description, owner_member_id, lead_member_id,
                                 status, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, 'Active', now(), now())""",
        (project_id, matter_id, title, description, actor, actor),
    )
    if actor:
        conn.execute(
            "INSERT INTO project_members (project_id, principal_type, principal_id, role, added_by) "
            "VALUES (%s, 'member', %s, 'owner', %s)", (project_id, actor, actor))
    _event(conn, "project.created", project_id, actor, {"title": title})
    conn.commit()
    audit.record("project.create", member_id=actor, object_type="project", object_id=project_id,
                 matter_id=matter_id, detail={"title": title})
    return get_project(conn, actor, project_id)


def visible_project_ids(conn, actor: str | None) -> set[str] | None:
    """Projects the actor belongs to (directly or through a team); None = all (dev mode, no identity)."""
    if actor is None:
        return None
    return {r["project_id"] for r in rows(conn, """
        SELECT pm.project_id FROM project_members pm
        LEFT JOIN team_members tm ON pm.principal_type = 'team' AND tm.team_id = pm.principal_id
        WHERE (pm.principal_type = 'member' AND pm.principal_id = %(u)s) OR tm.member_id = %(u)s""", {"u": actor})}


@guard
def list_projects(conn, actor: str | None, *, q: str | None = None, archived: bool = False,
                  limit: int = 100, offset: int = 0, scope: str = "all", sort: str = "updated",
                  matter_id: str | None = None) -> dict:
    """Projects the member can open. ``scope``: all, mine (they own it) or shared (someone else's, they are in it)."""
    ids = visible_project_ids(conn, actor)
    params: dict[str, Any] = {"ids": list(ids) if ids is not None else None, "u": actor, "limit": limit,
                              "offset": offset, "archived": archived}
    where = ["(%(ids)s::text[] IS NULL OR p.project_id = ANY(%(ids)s))",
             "(p.archived_at IS NOT NULL) = %(archived)s"]
    if q and q.strip():
        params["q"] = f"%{q.strip()}%"
        where.append("(p.title ILIKE %(q)s OR p.description ILIKE %(q)s)")
    if scope == "mine" and actor:
        where.append("p.owner_member_id = %(u)s")
    elif scope == "shared" and actor:
        where.append("p.owner_member_id IS DISTINCT FROM %(u)s")
    if matter_id:
        params["matter_id"] = matter_id
        where.append("p.matter_id = %(matter_id)s")
    order = "lower(p.title), p.project_id" if sort == "title" else "p.updated_at DESC, p.project_id DESC"
    total = one(conn, f"SELECT count(*) AS n FROM projects p WHERE {' AND '.join(where)}", params)["n"]
    items = rows(conn, f"""
        SELECT p.project_id, p.title, p.description, p.matter_id, p.owner_member_id, o.name AS owner_name,
               p.created_at, p.updated_at, p.archived_at, p.row_version,
               (SELECT count(*) FROM documents d WHERE d.home_kind = 'project' AND d.home_id = p.project_id
                  AND d.archived_at IS NULL) +
               (SELECT count(*) FROM document_links l WHERE l.container_kind = 'project'
                  AND l.container_id = p.project_id) AS document_count,
               (SELECT count(*) FROM project_members pm WHERE pm.project_id = p.project_id) AS member_count,
               (SELECT max(CASE pm.role WHEN 'owner' THEN 3 WHEN 'editor' THEN 2 ELSE 1 END)
                  FROM project_members pm
                  LEFT JOIN team_members tm ON pm.principal_type = 'team' AND tm.team_id = pm.principal_id
                  WHERE pm.project_id = p.project_id
                    AND ((pm.principal_type = 'member' AND pm.principal_id = %(u)s) OR tm.member_id = %(u)s)) AS my_level
        FROM projects p LEFT JOIN members o ON o.member_id = p.owner_member_id
        WHERE {' AND '.join(where)}
        ORDER BY {order}
        LIMIT %(limit)s OFFSET %(offset)s""", params)
    for it in items:
        lvl = it.pop("my_level")
        it["my_role"] = {3: "owner", 2: "editor", 1: "viewer"}.get(lvl) if actor else "owner"
        it["matter"] = _visible_matter(conn, actor, it.pop("matter_id"))
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@guard
def get_project(conn, actor: str | None, project_id: str) -> dict:
    level = require_container(conn, actor, "project", project_id, "read")
    p = one(conn, """
        SELECT p.project_id, p.title, p.description, p.matter_id, p.owner_member_id, o.name AS owner_name,
               p.created_at, p.updated_at, p.archived_at, p.row_version
        FROM projects p LEFT JOIN members o ON o.member_id = p.owner_member_id
        WHERE p.project_id = %s""", (project_id,))
    p["matter"] = _visible_matter(conn, actor, p.pop("matter_id"))
    p["my_level"] = level
    p["my_role"] = {"manage": "owner", "edit": "editor", "read": "viewer"}[level]
    p["members"] = list_members(conn, project_id)
    return p


def list_members(conn, project_id: str) -> list[dict]:
    return rows(conn, """
        SELECT pm.principal_type, pm.principal_id, pm.role, pm.added_at,
               coalesce(mb.name, t.name) AS name, mb.role AS title,
               CASE WHEN pm.principal_type = 'team'
                    THEN (SELECT count(*) FROM team_members x WHERE x.team_id = pm.principal_id) END AS team_size
        FROM project_members pm
        LEFT JOIN members mb ON pm.principal_type = 'member' AND mb.member_id = pm.principal_id
        LEFT JOIN teams t ON pm.principal_type = 'team' AND t.team_id = pm.principal_id
        WHERE pm.project_id = %s
        ORDER BY CASE pm.role WHEN 'owner' THEN 0 WHEN 'editor' THEN 1 ELSE 2 END, name""", (project_id,))


# ── edit / archive ───────────────────────────────────────────────────────────

@guard
def update_project(conn, actor: str | None, project_id: str, changes: dict, row_version: int | None) -> dict:
    require_container(conn, actor, "project", project_id, "manage")
    before = one(conn, "SELECT * FROM projects WHERE project_id = %s FOR UPDATE", (project_id,))
    check_version(before["row_version"], row_version, "project")
    unknown = set(changes) - {"title", "description", "matter_id"}
    if unknown:
        raise FirmError(422, f"Cannot change {', '.join(sorted(unknown))}")
    clean: dict[str, Any] = {}
    if "title" in changes:
        clean["title"] = _title(changes["title"])
    if "description" in changes:
        clean["description"] = _description(changes["description"])
    if "matter_id" in changes:
        clean["matter_id"] = _linked_matter(conn, actor, changes["matter_id"])
    if clean:
        sets = ", ".join(f"{k} = %({k})s" for k in clean)
        conn.execute(f"UPDATE projects SET {sets}, updated_at = now(), row_version = row_version + 1 "
                     f"WHERE project_id = %(pid)s", {**clean, "pid": project_id})
        _event(conn, "project.updated", project_id, actor, {"fields": sorted(clean)})
    conn.commit()
    if clean:
        audit.record("project.update", member_id=actor, object_type="project", object_id=project_id,
                     detail={"fields": sorted(clean)})
    return get_project(conn, actor, project_id)


@guard
def set_archived(conn, actor: str | None, project_id: str, archived: bool) -> dict:
    level = access.container_level(conn, actor, "project", project_id)
    if level == "none":
        raise FirmError(404, "Workspace not found or access denied")
    if level != "manage":
        raise FirmError(403, "Only a project owner can archive or restore it")
    conn.execute("UPDATE projects SET archived_at = CASE WHEN %s THEN now() ELSE NULL END, updated_at = now(), "
                 "row_version = row_version + 1 WHERE project_id = %s", (archived, project_id))
    _event(conn, "project.archived" if archived else "project.restored", project_id, actor)
    conn.commit()
    audit.record("project.archive" if archived else "project.restore", member_id=actor,
                 object_type="project", object_id=project_id)
    return get_project(conn, actor, project_id)


@guard
def delete_project(conn, actor: str | None, project_id: str) -> dict:
    """Delete an empty project (owners only). Anything still in it — documents living there, documents shown there,
    open reviews — must be moved, filed or removed first, so nothing is lost by a delete."""
    level = access.container_level(conn, actor, "project", project_id)
    if level == "none":
        raise FirmError(404, "Workspace not found or access denied")
    if level != "manage":
        raise FirmError(403, "Only a project owner can delete it")
    held = one(conn, """
        SELECT (SELECT count(*) FROM documents WHERE home_kind = 'project' AND home_id = %(p)s AND archived_at IS NULL) AS docs,
               (SELECT count(*) FROM document_links WHERE container_kind = 'project' AND container_id = %(p)s) AS links,
               (SELECT count(*) FROM tab_reviews WHERE container_kind = 'project' AND container_id = %(p)s AND archived_at IS NULL) AS reviews""",
        {"p": project_id})
    if held and (held["docs"] or held["links"] or held["reviews"]):
        parts = [f"{n} {w}{'' if n == 1 else 's'}" for n, w in
                 ((held["docs"], "document"), (held["links"], "linked document"), (held["reviews"], "review")) if n]
        raise FirmError(409, "The project still holds " + ", ".join(parts) + ". Move or remove them first, or archive the project.")
    if one(conn, "SELECT 1 AS x FROM documents WHERE home_kind = 'project' AND home_id = %s", (project_id,)):
        # Only archived documents remain: they stay archived (readable by nobody), so the project is kept too.
        raise FirmError(409, "The project holds archived documents, so it can only be archived.")
    title = one(conn, "SELECT title FROM projects WHERE project_id = %s", (project_id,))
    for sql in ("DELETE FROM workspace_folders WHERE container_kind = 'project' AND container_id = %s",
                "DELETE FROM workbench_state WHERE scope_key = 'project:' || %s",
                "UPDATE chat_sessions SET workspace_kind = NULL, workspace_id = NULL WHERE workspace_kind = 'project' AND workspace_id = %s",
                "DELETE FROM projects WHERE project_id = %s"):
        conn.execute(sql, (project_id,))
    _event(conn, "project.deleted", project_id, actor)
    conn.commit()
    audit.record("project.delete", member_id=actor, object_type="project", object_id=project_id,
                 detail={"title": title["title"] if title else None})
    return {"deleted": True, "project_id": project_id}


# ── members ──────────────────────────────────────────────────────────────────

def _principal(conn, principal_type: str, principal_id: str) -> None:
    if principal_type == "member":
        row = one(conn, "SELECT active FROM members WHERE member_id = %s", (principal_id,))
        if row is None:
            raise FirmError(422, f"Unknown member {principal_id}")
        if row.get("active") is False:
            raise FirmError(422, "That person's account is deactivated")
    elif principal_type == "team":
        if one(conn, "SELECT 1 AS ok FROM teams WHERE team_id = %s", (principal_id,)) is None:
            raise FirmError(422, f"Unknown team {principal_id}")
    else:
        raise FirmError(422, "principal_type must be member or team")


def _owners_left(conn, project_id: str) -> int:
    return one(conn, "SELECT count(*) AS n FROM project_members WHERE project_id = %s AND role = 'owner' "
                     "AND principal_type = 'member'", (project_id,))["n"]


@guard
def set_member(conn, actor: str | None, project_id: str, principal_type: str, principal_id: str, role: str) -> dict:
    """Add someone (or a team) to the project, or change their role. Owners only."""
    require_container(conn, actor, "project", project_id, "manage")
    if role not in ROLES:
        raise FirmError(422, f"role must be one of {', '.join(ROLES)}")
    if principal_type == "team" and role == "owner":
        raise FirmError(422, "A team can be an editor or a viewer; owners are people")
    _principal(conn, principal_type, principal_id)
    before = one(conn, "SELECT role FROM project_members WHERE project_id = %s AND principal_type = %s "
                       "AND principal_id = %s FOR UPDATE", (project_id, principal_type, principal_id))
    conn.execute(
        """INSERT INTO project_members (project_id, principal_type, principal_id, role, added_by)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (project_id, principal_type, principal_id) DO UPDATE SET role = EXCLUDED.role""",
        (project_id, principal_type, principal_id, role, actor))
    if before and before["role"] == "owner" and role != "owner" and _owners_left(conn, project_id) == 0:
        conn.rollback()
        raise FirmError(409, "A project always keeps at least one owner")
    _event(conn, "project.member_set", project_id, actor,
           {"principal_type": principal_type, "principal_id": principal_id, "role": role})
    conn.execute("UPDATE projects SET updated_at = now() WHERE project_id = %s", (project_id,))
    conn.commit()
    audit.record("project.member.set", member_id=actor, object_type="project", object_id=project_id,
                 detail={"principal_type": principal_type, "principal_id": principal_id, "role": role,
                         "before": before["role"] if before else None})
    return {"members": list_members(conn, project_id)}


@guard
def remove_member(conn, actor: str | None, project_id: str, principal_type: str, principal_id: str) -> dict:
    """Owners remove anyone; anyone may leave (remove themselves)."""
    leaving = principal_type == "member" and principal_id == actor
    require_container(conn, actor, "project", project_id, "read" if leaving else "manage")
    gone = one(conn, "DELETE FROM project_members WHERE project_id = %s AND principal_type = %s "
                     "AND principal_id = %s RETURNING role", (project_id, principal_type, principal_id))
    if gone is None:
        raise FirmError(404, "Not a member of this project")
    if gone["role"] == "owner" and _owners_left(conn, project_id) == 0:
        conn.rollback()
        raise FirmError(409, "A project always keeps at least one owner; make someone else owner first")
    _event(conn, "project.member_removed", project_id, actor,
           {"principal_type": principal_type, "principal_id": principal_id})
    conn.commit()
    audit.record("project.member.remove", member_id=actor, object_type="project", object_id=project_id,
                 detail={"principal_type": principal_type, "principal_id": principal_id, "role": gone["role"]})
    return {"members": list_members(conn, project_id) if not leaving else []}
