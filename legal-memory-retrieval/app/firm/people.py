"""People: everyone keeps their own expertise current; users.manage onboards and edits people."""
from __future__ import annotations

from typing import Any

from app import access
from app.audit import events as audit
from app.firm import FirmError, emit, guard, one

SELF_FIELDS = ("practice_areas", "specializations")
ADMIN_FIELDS = ("name", "role", "office", "email", "is_lawyer", "practice_areas", "specializations", "joined_year")
LIST_FIELDS = ("practice_areas", "specializations")


def _clean(data: dict, allowed: tuple[str, ...]) -> dict[str, Any]:
    unknown = set(data) - set(allowed)
    if unknown:
        raise FirmError(422 if data else 400, f"Cannot change {', '.join(sorted(unknown))}")
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key in LIST_FIELDS:
            if not isinstance(value, list) or len(value) > 30:
                raise FirmError(422, f"{key} must be a list of at most 30 items")
            out[key] = [str(v).strip()[:100] for v in value if str(v).strip()]
        elif key == "is_lawyer":
            out[key] = bool(value)
        elif key == "joined_year":
            out[key] = int(value) if value not in (None, "") else None
        elif key == "email":
            email = (value or "").strip().lower()
            if email and ("@" not in email or len(email) > 200):
                raise FirmError(422, "email is not valid")
            out[key] = email or None
        else:
            text = (value or "").strip()
            if key == "name" and not text:
                raise FirmError(422, "name is required")
            out[key] = text[:200] or None
    return out


def get_person(conn, member_id: str) -> dict:
    row = one(conn, """SELECT member_id, name, role, office, email, is_lawyer, practice_areas, specializations, joined_year, active
                       FROM members WHERE member_id = %s""", (member_id,))
    if row is None:
        raise FirmError(404, "Person not found")
    return {**row, "roles": access.member_roles(conn, member_id)}


def _write(conn, actor: str | None, member_id: str, fields: dict, action: str) -> dict:
    before = get_person(conn, member_id)
    if fields:
        sets = ", ".join(f"{k} = %({k})s" for k in fields)
        conn.execute(f"UPDATE members SET {sets} WHERE member_id = %(mid)s", {**fields, "mid": member_id})
        emit(conn, "person.updated", "member", member_id, actor=actor, payload={"fields": sorted(fields)})
        conn.commit()
        audit.record(action, member_id=actor, object_type="member", object_id=member_id,
                     detail={k: {"from": str(before.get(k)), "to": str(v)} for k, v in fields.items() if before.get(k) != v})
    return get_person(conn, member_id)


@guard
def update_me(conn, actor: str | None, data: dict) -> dict:
    """Your own practice areas and specialisations (what Ask the Firm finds you by)."""
    if actor is None:
        raise FirmError(400, "Sign in to edit your profile")
    return _write(conn, actor, actor, _clean(data, SELF_FIELDS), "person.update.self")


@guard
def update_person(conn, actor: str | None, member_id: str, data: dict) -> dict:
    access.require_permission(conn, actor, "users.manage")
    roles = data.pop("roles", None)
    out = _write(conn, actor, member_id, _clean(data, ADMIN_FIELDS), "person.update")
    if roles is not None:
        access.set_member_roles(conn, actor, member_id, roles)
        out = get_person(conn, member_id)
    return out


@guard
def create_person(conn, actor: str | None, data: dict) -> dict:
    """Onboard someone: their profile and firm roles (sign-in keys are issued separately)."""
    access.require_permission(conn, actor, "users.manage")
    roles = data.pop("roles", None) or ["fee_earner"]
    fields = _clean(data, ADMIN_FIELDS)
    if not fields.get("name"):
        raise FirmError(422, "name is required")
    if fields.get("email") and one(conn, "SELECT 1 AS ok FROM members WHERE lower(email) = %s", (fields["email"],)):
        raise FirmError(409, "Someone already has this email")
    n = one(conn, "SELECT coalesce(max(substring(member_id FROM 'MEM-(\\d+)')::int), 0) + 1 AS n FROM members")["n"]
    member_id = f"MEM-{n:05d}"
    fields.setdefault("practice_areas", [])
    fields.setdefault("specializations", [])
    fields.setdefault("is_lawyer", True)
    cols = ["member_id", *fields]
    conn.execute(f"INSERT INTO members ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})", (member_id, *fields.values()))
    emit(conn, "person.created", "member", member_id, actor=actor, payload={"name": fields["name"]})
    conn.commit()
    audit.record("person.create", member_id=actor, object_type="member", object_id=member_id, detail={"name": fields["name"]})
    access.set_member_roles(conn, actor, member_id, roles)
    return get_person(conn, member_id)


# ── leaving and returning ────────────────────────────────────────────────────

def _forget(member_id: str) -> None:
    from app.auth.deps import forget_active

    forget_active(member_id)


@guard
def deactivate_person(conn, actor: str | None, member_id: str, reason: str) -> dict:
    """Someone has left (or is away): they can no longer sign in or be staffed; their history stays."""
    access.require_permission(conn, actor, "users.manage")
    person = get_person(conn, member_id)
    if not person["active"]:
        raise FirmError(409, "This person is already deactivated")
    if actor == member_id:
        raise FirmError(409, "You cannot deactivate yourself")
    reason = (reason or "").strip()
    if not reason or len(reason) > 500:
        raise FirmError(422, "Say why (at most 500 characters)")
    if "firm_admin" in person["roles"]:
        others = one(conn, "SELECT count(*) AS n FROM member_roles r JOIN members m USING (member_id) "
                           "WHERE r.role_key = 'firm_admin' AND m.active AND r.member_id <> %s", (member_id,))["n"]
        if not others:
            raise FirmError(409, "This is the last active firm administrator; assign another first")
    leads = conn.execute(
        """SELECT m.matter_code FROM matter_members mm JOIN matters m USING (matter_id)
           WHERE mm.member_id = %s AND lower(mm.role_on_matter) = 'lead' AND m.status IN ('Open', 'On hold')
             AND (mm.ended_at IS NULL OR mm.ended_at >= current_date) ORDER BY m.matter_code""", (member_id,)).fetchall()
    if leads:
        codes = ", ".join(r["matter_code"] for r in leads[:6])
        raise FirmError(409, f"Hand over the lead on {len(leads)} open matter(s) first: {codes}", {"lead_on": [r["matter_code"] for r in leads]})
    conn.execute("UPDATE members SET active = FALSE, deactivated_at = now(), deactivated_by = %s WHERE member_id = %s", (actor, member_id))
    conn.execute("DELETE FROM api_keys WHERE member_id = %s", (member_id,))
    conn.execute("DELETE FROM auth_sessions WHERE member_id = %s", (member_id,))
    emit(conn, "person.updated", "member", member_id, actor=actor, payload={"active": False})
    conn.commit()
    audit.record("person.deactivate", member_id=actor, object_type="member", object_id=member_id, detail={"reason": reason})
    _forget(member_id)
    return get_person(conn, member_id)


@guard
def reactivate_person(conn, actor: str | None, member_id: str) -> dict:
    access.require_permission(conn, actor, "users.manage")
    person = get_person(conn, member_id)
    if person["active"]:
        raise FirmError(409, "This person is already active")
    conn.execute("UPDATE members SET active = TRUE, deactivated_at = NULL, deactivated_by = NULL WHERE member_id = %s", (member_id,))
    emit(conn, "person.updated", "member", member_id, actor=actor, payload={"active": True})
    conn.commit()
    audit.record("person.reactivate", member_id=actor, object_type="member", object_id=member_id, detail={})
    _forget(member_id)
    return get_person(conn, member_id)
