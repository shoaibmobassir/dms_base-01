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
    row = one(conn, """SELECT member_id, name, role, office, email, is_lawyer, practice_areas, specializations, joined_year
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
