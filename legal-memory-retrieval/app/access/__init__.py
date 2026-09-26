"""Firm roles, teams and matter access (plan §5).

Source of truth: ``member_roles``/``role_permissions`` (what a person may
administer), ``teams``/``team_members``, and per matter ``matter_access``
(mode), ``matter_grants`` and ``matter_screens``. The ``permissions`` table that
every search and page query joins is compiled from these by the database
(``acl_compile_matter``), so a change here takes effect for retrieval, Ask the
Firm, the Assistant, documents and counts in the same transaction.

Admin roles never grant content access by themselves: a firm admin sees a
walled matter only through a grant, like anyone else.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.audit import events as audit

LEVELS = ("none", "read", "edit", "manage")
MODES = ("open", "team", "restricted")


class AccessError(Exception):
    """A request the caller is not allowed to make (maps to 403/404/409)."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _rows(conn, sql: str, params: dict[str, Any] | tuple = ()) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        if cur.description is None:
            return []
        cols = [c.name for c in cur.description]
        return [r if isinstance(r, dict) else dict(zip(cols, r)) for r in cur.fetchall()]


def _one(conn, sql: str, params: dict[str, Any] | tuple = ()) -> dict | None:
    rows = _rows(conn, sql, params)
    return rows[0] if rows else None


# ── Roles and permissions ────────────────────────────────────────────────────

ALL = "*"


def member_permissions(conn, member_id: str | None) -> set[str]:
    """Permission keys for a member. ``None`` (dev mode, no identity) has all."""
    if member_id is None:
        return {ALL}
    rows = _rows(
        conn,
        """
        SELECT DISTINCT rp.permission FROM member_roles mr
        JOIN role_permissions rp ON rp.role_key = mr.role_key
        WHERE mr.member_id = %s
        """,
        (member_id,),
    )
    return {r["permission"] for r in rows}


def has_permission(conn, member_id: str | None, permission: str) -> bool:
    perms = member_permissions(conn, member_id)
    return ALL in perms or permission in perms


def require_permission(conn, member_id: str | None, permission: str) -> None:
    if not has_permission(conn, member_id, permission):
        raise AccessError(403, f"Requires the '{permission}' permission")


def member_roles(conn, member_id: str) -> list[str]:
    return [r["role_key"] for r in _rows(conn, "SELECT role_key FROM member_roles WHERE member_id = %s ORDER BY role_key", (member_id,))]


def set_member_roles(conn, actor: str | None, member_id: str, roles: list[str]) -> list[str]:
    require_permission(conn, actor, "roles.manage")
    known = {r["role_key"] for r in _rows(conn, "SELECT role_key FROM firm_roles")}
    unknown = sorted(set(roles) - known)
    if unknown:
        raise AccessError(422, f"Unknown roles: {', '.join(unknown)}")
    if not _one(conn, "SELECT 1 AS ok FROM members WHERE member_id = %s", (member_id,)):
        raise AccessError(404, "Member not found")
    before = member_roles(conn, member_id)
    if actor == member_id and "firm_admin" in before and "firm_admin" not in roles:
        others = _one(conn, "SELECT count(*) AS n FROM member_roles WHERE role_key = 'firm_admin' AND member_id <> %s", (member_id,))
        if not others or others["n"] == 0:
            raise AccessError(409, "You are the last firm administrator; assign another first")
    conn.execute("DELETE FROM member_roles WHERE member_id = %s AND NOT (role_key = ANY(%s))", (member_id, roles))
    for role in roles:
        conn.execute(
            "INSERT INTO member_roles (member_id, role_key, granted_by) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (member_id, role, actor),
        )
    conn.commit()
    after = member_roles(conn, member_id)
    audit.record("admin.roles.set", member_id=actor, object_type="member", object_id=member_id,
                 detail={"before": before, "after": after})
    return after


# ── Matter level ─────────────────────────────────────────────────────────────

def can_see_matter(conn, member_id: str | None, matter_id: str) -> bool:
    from app.api.acl import ACL_CLAUSE

    row = _one(
        conn,
        f"""
        SELECT 1 AS ok FROM matters m LEFT JOIN permissions p ON p.matter_id = m.matter_id
        WHERE m.matter_id = %(matter_id)s AND {ACL_CLAUSE}
        """,
        {"matter_id": matter_id, "member_id": member_id},
    )
    return row is not None


def matter_level(conn, member_id: str | None, matter_id: str) -> str:
    """none | read | edit | manage for one member on one matter.

    manage: walls.manage permission, a manage grant (direct or via team), or lead on the matter.
    edit:   an edit grant, or on the matter team.
    read:   can see the matter (compiled ACL).
    A screen always yields none (even for walls.manage it only allows managing the wall).
    """
    if member_id is None:
        return "manage"
    screened = _one(conn, "SELECT 1 AS ok FROM matter_screens WHERE matter_id = %s AND member_id = %s", (matter_id, member_id))
    walls = has_permission(conn, member_id, "walls.manage")
    if screened:
        return "manage" if walls else "none"
    if walls:
        return "manage"
    if not can_see_matter(conn, member_id, matter_id):
        return "none"
    grant = _one(
        conn,
        """
        SELECT max(CASE g.level WHEN 'manage' THEN 3 WHEN 'edit' THEN 2 ELSE 1 END) AS lvl
        FROM matter_grants g
        LEFT JOIN team_members tm ON g.principal_type = 'team' AND tm.team_id = g.principal_id
        WHERE g.matter_id = %(m)s AND (g.expires_at IS NULL OR g.expires_at > now())
          AND ((g.principal_type = 'member' AND g.principal_id = %(u)s) OR tm.member_id = %(u)s)
        """,
        {"m": matter_id, "u": member_id},
    )
    staff = _one(conn, "SELECT role_on_matter FROM matter_members WHERE matter_id = %s AND member_id = %s", (matter_id, member_id))
    level = grant["lvl"] if grant and grant["lvl"] else 1
    if staff:
        level = max(level, 3 if (staff["role_on_matter"] or "").lower() == "lead" else 2)
    return LEVELS[level]


def require_matter_level(conn, member_id: str | None, matter_id: str, needed: str) -> str:
    level = matter_level(conn, member_id, matter_id)
    if level == "none":
        raise AccessError(404, "Matter not found or access denied")
    if LEVELS.index(level) < LEVELS.index(needed):
        raise AccessError(403, f"Requires {needed} access to this matter")
    return level


# ── Matter access: read ──────────────────────────────────────────────────────

def matter_access_summary(conn, actor: str | None, matter_id: str) -> dict[str, Any]:
    require_matter_level(conn, actor, matter_id, "manage")
    access = _one(conn, "SELECT mode, hide_existence, updated_by, updated_at, row_version FROM matter_access WHERE matter_id = %s", (matter_id,))
    if access is None:
        raise AccessError(404, "Matter not found")
    grants = _rows(
        conn,
        """
        SELECT g.grant_id, g.principal_type, g.principal_id, g.level, g.reason, g.expires_at,
               g.granted_by, g.granted_at,
               coalesce(mb.name, t.name) AS principal_name,
               CASE WHEN g.principal_type = 'team' THEN (SELECT count(*) FROM team_members x WHERE x.team_id = g.principal_id) END AS team_size
        FROM matter_grants g
        LEFT JOIN members mb ON g.principal_type = 'member' AND mb.member_id = g.principal_id
        LEFT JOIN teams t ON g.principal_type = 'team' AND t.team_id = g.principal_id
        WHERE g.matter_id = %s ORDER BY g.principal_type, principal_name
        """,
        (matter_id,),
    )
    screens = _rows(
        conn,
        """
        SELECT s.member_id, mb.name, s.reason, s.created_by, s.created_at
        FROM matter_screens s JOIN members mb USING (member_id)
        WHERE s.matter_id = %s ORDER BY mb.name
        """,
        (matter_id,),
    )
    team = _rows(
        conn,
        """
        SELECT mm.member_id, mb.name, mb.role, mm.role_on_matter, mm.started_at, mm.ended_at
        FROM matter_members mm JOIN members mb USING (member_id)
        WHERE mm.matter_id = %s ORDER BY CASE WHEN mm.role_on_matter = 'Lead' THEN 0 ELSE 1 END, mb.name
        """,
        (matter_id,),
    )
    compiled = _one(conn, "SELECT restricted, cardinality(allowed_members) AS allowed, cardinality(denied_members) AS denied, compiled_at FROM permissions WHERE matter_id = %s", (matter_id,))
    requests = _rows(
        conn,
        """
        SELECT r.request_id, r.requester_id, mb.name AS requester_name, r.level, r.reason, r.status, r.created_at
        FROM access_requests r JOIN members mb ON mb.member_id = r.requester_id
        WHERE r.matter_id = %s AND r.status = 'pending' ORDER BY r.created_at
        """,
        (matter_id,),
    )
    history = _rows(
        conn,
        """
        SELECT occurred_at, member_id, action, detail FROM audit_events
        WHERE matter_id = %s AND action LIKE 'access.%%' ORDER BY seq DESC LIMIT 50
        """,
        (matter_id,),
    )
    return {
        "matter_id": matter_id,
        "mode": access["mode"],
        "hide_existence": access["hide_existence"],
        "row_version": access["row_version"],
        "updated_by": access["updated_by"],
        "updated_at": access["updated_at"],
        "grants": grants,
        "screens": screens,
        "team": team,
        "compiled": compiled,
        "pending_requests": requests,
        "history": history,
        "can_manage_screens": has_permission(conn, actor, "walls.manage"),
    }


# ── Matter access: write ─────────────────────────────────────────────────────

def _audit(actor: str | None, action: str, matter_id: str, detail: dict[str, Any]) -> None:
    audit.record(action, member_id=actor, object_type="matter", object_id=matter_id, matter_id=matter_id, detail=detail)


def set_matter_mode(conn, actor: str | None, matter_id: str, mode: str, hide_existence: bool | None, row_version: int | None) -> dict[str, Any]:
    if mode not in MODES:
        raise AccessError(422, f"mode must be one of {', '.join(MODES)}")
    require_matter_level(conn, actor, matter_id, "manage")
    current = _one(conn, "SELECT mode, hide_existence, row_version FROM matter_access WHERE matter_id = %s FOR UPDATE", (matter_id,))
    if current is None:
        raise AccessError(404, "Matter not found")
    if row_version is not None and row_version != current["row_version"]:
        conn.rollback()
        raise AccessError(409, "Access settings changed since you loaded them; reload and try again")
    hide = current["hide_existence"] if hide_existence is None else bool(hide_existence)
    if mode == "open":
        hide = False
    conn.execute(
        """
        UPDATE matter_access SET mode = %s, hide_existence = %s, updated_by = %s, updated_at = now(),
               row_version = row_version + 1
        WHERE matter_id = %s
        """,
        (mode, hide, actor, matter_id),
    )
    if mode == "restricted" and actor is not None and not has_permission(conn, actor, "walls.manage"):
        # Restricted is grants-only: keep the person who walled the matter inside the wall.
        conn.execute(
            """
            INSERT INTO matter_grants (grant_id, matter_id, principal_type, principal_id, level, reason, granted_by)
            VALUES (%s, %s, 'member', %s, 'manage', 'Restricted the matter', %s)
            ON CONFLICT (matter_id, principal_type, principal_id) DO UPDATE SET level = 'manage'
            """,
            (f"GRT-{uuid.uuid4().hex[:12].upper()}", matter_id, actor, actor),
        )
    conn.commit()
    _audit(actor, "access.mode", matter_id, {"from": current["mode"], "to": mode, "hide_existence": hide})
    return {"mode": mode, "hide_existence": hide, "row_version": current["row_version"] + 1}


def add_grant(conn, actor: str | None, matter_id: str, principal_type: str, principal_id: str,
              level: str = "read", reason: str = "", expires_at: str | None = None) -> dict[str, Any]:
    if principal_type not in ("member", "team"):
        raise AccessError(422, "principal_type must be member or team")
    if level not in ("read", "edit", "manage"):
        raise AccessError(422, "level must be read, edit or manage")
    require_matter_level(conn, actor, matter_id, "manage")
    table = "members" if principal_type == "member" else "teams"
    key = "member_id" if principal_type == "member" else "team_id"
    if not _one(conn, f"SELECT 1 AS ok FROM {table} WHERE {key} = %s", (principal_id,)):
        raise AccessError(404, f"{principal_type.title()} not found")
    if principal_type == "member" and _one(conn, "SELECT 1 AS ok FROM matter_screens WHERE matter_id = %s AND member_id = %s", (matter_id, principal_id)):
        raise AccessError(409, "This person is screened from the matter; remove the screen first")
    grant_id = f"GRT-{uuid.uuid4().hex[:12].upper()}"
    row = _one(
        conn,
        """
        INSERT INTO matter_grants (grant_id, matter_id, principal_type, principal_id, level, reason, expires_at, granted_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (matter_id, principal_type, principal_id) DO UPDATE
          SET level = EXCLUDED.level, reason = EXCLUDED.reason, expires_at = EXCLUDED.expires_at,
              granted_by = EXCLUDED.granted_by, granted_at = now()
        RETURNING grant_id, principal_type, principal_id, level, reason, expires_at
        """,
        (grant_id, matter_id, principal_type, principal_id, level, reason, expires_at, actor),
    )
    conn.commit()
    _audit(actor, "access.grant", matter_id, {k: str(v) for k, v in (row or {}).items()})
    return row or {}


def remove_grant(conn, actor: str | None, matter_id: str, grant_id: str) -> None:
    require_matter_level(conn, actor, matter_id, "manage")
    row = _one(conn, "DELETE FROM matter_grants WHERE matter_id = %s AND grant_id = %s RETURNING principal_type, principal_id, level", (matter_id, grant_id))
    if row is None:
        conn.rollback()
        raise AccessError(404, "Grant not found")
    conn.commit()
    _audit(actor, "access.revoke", matter_id, {"grant_id": grant_id, **row})


def add_screen(conn, actor: str | None, matter_id: str, member_id: str, reason: str) -> dict[str, Any]:
    require_permission(conn, actor, "walls.manage")
    if not (reason or "").strip():
        raise AccessError(422, "A screen needs a reason")
    if not _one(conn, "SELECT 1 AS ok FROM matters WHERE matter_id = %s", (matter_id,)):
        raise AccessError(404, "Matter not found")
    if not _one(conn, "SELECT 1 AS ok FROM members WHERE member_id = %s", (member_id,)):
        raise AccessError(404, "Member not found")
    conn.execute(
        """
        INSERT INTO matter_screens (matter_id, member_id, reason, created_by) VALUES (%s, %s, %s, %s)
        ON CONFLICT (matter_id, member_id) DO UPDATE SET reason = EXCLUDED.reason
        """,
        (matter_id, member_id, reason.strip(), actor),
    )
    conn.commit()
    _audit(actor, "access.screen", matter_id, {"member_id": member_id, "reason": reason.strip()})
    return {"matter_id": matter_id, "member_id": member_id, "reason": reason.strip()}


def remove_screen(conn, actor: str | None, matter_id: str, member_id: str) -> None:
    require_permission(conn, actor, "walls.manage")
    row = _one(conn, "DELETE FROM matter_screens WHERE matter_id = %s AND member_id = %s RETURNING member_id", (matter_id, member_id))
    if row is None:
        conn.rollback()
        raise AccessError(404, "Screen not found")
    conn.commit()
    _audit(actor, "access.unscreen", matter_id, {"member_id": member_id})


# ── Access requests ──────────────────────────────────────────────────────────

def access_status(conn, member_id: str | None, matter_id: str) -> dict[str, Any]:
    """What a member may know about a matter they may not be able to open.

    A hidden (existence-restricted) matter is indistinguishable from a missing one.
    """
    level = matter_level(conn, member_id, matter_id)
    info = _one(
        conn,
        """
        SELECT m.matter_id, m.matter_code, m.title, a.mode, a.hide_existence
        FROM matters m LEFT JOIN matter_access a USING (matter_id) WHERE m.matter_id = %s
        """,
        (matter_id,),
    )
    if info is None or (level == "none" and (info["hide_existence"] or _screened(conn, member_id, matter_id))):
        raise AccessError(404, "Matter not found or access denied")
    pending = _one(conn, "SELECT request_id FROM access_requests WHERE matter_id = %s AND requester_id = %s AND status = 'pending'", (matter_id, member_id)) if member_id else None
    return {
        "matter_id": info["matter_id"],
        "matter_code": info["matter_code"],
        "title": info["title"],
        "level": level,
        "can_request": level in ("none", "read") and member_id is not None and pending is None,
        "pending_request_id": pending["request_id"] if pending else None,
    }


def _screened(conn, member_id: str | None, matter_id: str) -> bool:
    return bool(member_id and _one(conn, "SELECT 1 AS ok FROM matter_screens WHERE matter_id = %s AND member_id = %s", (matter_id, member_id)))


def request_access(conn, member_id: str | None, matter_id: str, level: str, reason: str) -> dict[str, Any]:
    if member_id is None:
        raise AccessError(400, "Sign in to request access")
    if level not in ("read", "edit"):
        raise AccessError(422, "level must be read or edit")
    if not (reason or "").strip():
        raise AccessError(422, "Say why you need access")
    status = access_status(conn, member_id, matter_id)  # 404 for hidden / screened
    if not status["can_request"]:
        raise AccessError(409, "You already have this access or a pending request")
    request_id = f"ARQ-{uuid.uuid4().hex[:12].upper()}"
    row = _one(
        conn,
        """
        INSERT INTO access_requests (request_id, matter_id, requester_id, level, reason)
        VALUES (%s, %s, %s, %s, %s) RETURNING request_id, matter_id, level, reason, status, created_at
        """,
        (request_id, matter_id, member_id, level, reason.strip()),
    )
    conn.commit()
    _audit(member_id, "access.request", matter_id, {"request_id": request_id, "level": level})
    return row or {}


def list_requests(conn, actor: str | None, scope: str = "to_decide") -> list[dict]:
    """``mine``: requests I made. ``to_decide``: pending requests on matters I manage (or all, for walls.manage)."""
    if scope == "mine":
        return _rows(
            conn,
            """
            SELECT r.*, m.matter_code, m.title AS matter_title FROM access_requests r
            JOIN matters m USING (matter_id) WHERE r.requester_id = %s ORDER BY r.created_at DESC LIMIT 100
            """,
            (actor,),
        )
    rows = _rows(
        conn,
        """
        SELECT r.*, m.matter_code, m.title AS matter_title, mb.name AS requester_name
        FROM access_requests r JOIN matters m USING (matter_id)
        JOIN members mb ON mb.member_id = r.requester_id
        WHERE r.status = 'pending' ORDER BY r.created_at LIMIT 200
        """,
    )
    if has_permission(conn, actor, "walls.manage"):
        return rows
    return [r for r in rows if matter_level(conn, actor, r["matter_id"]) == "manage"]


def decide_request(conn, actor: str | None, request_id: str, approve: bool, note: str = "") -> dict[str, Any]:
    req = _one(conn, "SELECT * FROM access_requests WHERE request_id = %s", (request_id,))
    if req is None:
        raise AccessError(404, "Request not found")
    if not (has_permission(conn, actor, "access_requests.decide") or matter_level(conn, actor, req["matter_id"]) == "manage"):
        raise AccessError(403, "Only the matter's managers or risk & compliance can decide")
    if req["status"] != "pending":
        raise AccessError(409, f"Request is already {req['status']}")
    if actor is not None and actor == req["requester_id"]:
        raise AccessError(403, "You cannot decide your own request")
    status = "approved" if approve else "denied"
    conn.execute(
        """
        UPDATE access_requests SET status = %s, decided_by = %s, decided_at = now(), decision_note = %s
        WHERE request_id = %s
        """,
        (status, actor, note, request_id),
    )
    if approve:
        conn.execute(
            """
            INSERT INTO matter_grants (grant_id, matter_id, principal_type, principal_id, level, reason, granted_by)
            VALUES (%s, %s, 'member', %s, %s, %s, %s)
            ON CONFLICT (matter_id, principal_type, principal_id) DO UPDATE
              SET level = EXCLUDED.level, reason = EXCLUDED.reason, granted_by = EXCLUDED.granted_by, granted_at = now()
            """,
            (f"GRT-{uuid.uuid4().hex[:12].upper()}", req["matter_id"], req["requester_id"], req["level"],
             f"Access request {request_id}: {req['reason']}", actor),
        )
    conn.commit()
    _audit(actor, "access.request.decide", req["matter_id"], {"request_id": request_id, "status": status, "note": note})
    return {"request_id": request_id, "status": status}


# ── Teams ────────────────────────────────────────────────────────────────────

def list_teams(conn) -> list[dict]:
    return _rows(
        conn,
        """
        SELECT t.team_id, t.name, t.kind, t.description, t.external_group_id,
               count(tm.member_id) AS member_count,
               coalesce(json_agg(json_build_object('member_id', mb.member_id, 'name', mb.name, 'role', mb.role, 'team_role', tm.team_role)
                                 ORDER BY mb.name) FILTER (WHERE mb.member_id IS NOT NULL), '[]') AS members
        FROM teams t
        LEFT JOIN team_members tm ON tm.team_id = t.team_id
        LEFT JOIN members mb ON mb.member_id = tm.member_id
        GROUP BY t.team_id ORDER BY t.kind, t.name
        """,
    )


@dataclass
class TeamInput:
    name: str
    kind: str = "custom"
    description: str = ""
    external_group_id: str | None = None


def create_team(conn, actor: str | None, data: TeamInput) -> dict[str, Any]:
    require_permission(conn, actor, "teams.manage")
    if not data.name.strip():
        raise AccessError(422, "Team name is required")
    if data.kind not in ("practice", "office", "matter", "custom"):
        raise AccessError(422, "Unknown team kind")
    if _one(conn, "SELECT 1 AS ok FROM teams WHERE lower(name) = lower(%s)", (data.name.strip(),)):
        raise AccessError(409, "A team with that name exists")
    team_id = f"TEAM-{uuid.uuid4().hex[:10].upper()}"
    row = _one(
        conn,
        """
        INSERT INTO teams (team_id, name, kind, description, external_group_id, created_by)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING team_id, name, kind, description, external_group_id
        """,
        (team_id, data.name.strip(), data.kind, data.description, data.external_group_id, actor),
    )
    conn.commit()
    audit.record("admin.team.create", member_id=actor, object_type="team", object_id=team_id, detail={"name": data.name})
    return row or {}


def update_team(conn, actor: str | None, team_id: str, name: str | None, description: str | None) -> dict[str, Any]:
    require_permission(conn, actor, "teams.manage")
    row = _one(
        conn,
        """
        UPDATE teams SET name = coalesce(%s, name), description = coalesce(%s, description), updated_at = now()
        WHERE team_id = %s RETURNING team_id, name, kind, description
        """,
        (name.strip() if name else None, description, team_id),
    )
    if row is None:
        conn.rollback()
        raise AccessError(404, "Team not found")
    conn.commit()
    audit.record("admin.team.update", member_id=actor, object_type="team", object_id=team_id, detail={"name": name})
    return row


def delete_team(conn, actor: str | None, team_id: str) -> None:
    require_permission(conn, actor, "teams.manage")
    in_use = _one(conn, "SELECT count(*) AS n FROM matter_grants WHERE principal_type = 'team' AND principal_id = %s", (team_id,))
    if in_use and in_use["n"]:
        raise AccessError(409, f"The team is granted access to {in_use['n']} matter(s); remove those grants first")
    row = _one(conn, "DELETE FROM teams WHERE team_id = %s RETURNING team_id", (team_id,))
    if row is None:
        conn.rollback()
        raise AccessError(404, "Team not found")
    conn.commit()
    audit.record("admin.team.delete", member_id=actor, object_type="team", object_id=team_id)


def set_team_member(conn, actor: str | None, team_id: str, member_id: str, present: bool, team_role: str = "member") -> None:
    require_permission(conn, actor, "teams.manage")
    if not _one(conn, "SELECT 1 AS ok FROM teams WHERE team_id = %s", (team_id,)):
        raise AccessError(404, "Team not found")
    if present:
        if not _one(conn, "SELECT 1 AS ok FROM members WHERE member_id = %s", (member_id,)):
            raise AccessError(404, "Member not found")
        conn.execute(
            """
            INSERT INTO team_members (team_id, member_id, team_role, added_by) VALUES (%s, %s, %s, %s)
            ON CONFLICT (team_id, member_id) DO UPDATE SET team_role = EXCLUDED.team_role
            """,
            (team_id, member_id, team_role, actor),
        )
    else:
        conn.execute("DELETE FROM team_members WHERE team_id = %s AND member_id = %s", (team_id, member_id))
    conn.commit()
    audit.record("admin.team.member", member_id=actor, object_type="team", object_id=team_id,
                 detail={"member_id": member_id, "present": present, "team_role": team_role})


# ── Admin overviews ──────────────────────────────────────────────────────────

def list_users(conn, actor: str | None) -> list[dict]:
    if not (has_permission(conn, actor, "users.manage") or has_permission(conn, actor, "roles.manage")
            or has_permission(conn, actor, "walls.manage")):
        raise AccessError(403, "Requires users.manage")
    return _rows(
        conn,
        """
        SELECT mb.member_id, mb.name, mb.role, mb.office, mb.email, mb.practice_areas, mb.is_lawyer,
               coalesce((SELECT array_agg(role_key ORDER BY role_key) FROM member_roles r WHERE r.member_id = mb.member_id), '{}') AS roles,
               coalesce((SELECT array_agg(t.name ORDER BY t.name) FROM team_members tm JOIN teams t USING (team_id)
                         WHERE tm.member_id = mb.member_id), '{}') AS teams,
               (SELECT count(*) FROM matter_members mm WHERE mm.member_id = mb.member_id) AS matter_count
        FROM members mb ORDER BY mb.name
        """,
    )


def walls_overview(conn, actor: str | None) -> list[dict]:
    if not (has_permission(conn, actor, "walls.manage") or has_permission(conn, actor, "audit.read")):
        raise AccessError(403, "Requires walls.manage")
    return _rows(
        conn,
        """
        SELECT m.matter_id, m.matter_code, m.title, cl.name AS client_name, a.mode, a.hide_existence,
               cardinality(p.allowed_members) AS allowed, cardinality(p.denied_members) AS screened,
               (SELECT count(*) FROM access_requests r WHERE r.matter_id = m.matter_id AND r.status = 'pending') AS pending_requests,
               a.updated_by, a.updated_at
        FROM matter_access a JOIN matters m USING (matter_id) JOIN clients cl ON cl.client_id = m.client_id
        JOIN permissions p ON p.matter_id = m.matter_id
        WHERE a.mode <> 'open' OR cardinality(p.denied_members) > 0
        ORDER BY a.mode DESC, m.matter_code
        """,
    )
