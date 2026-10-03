"""Matters: open, edit, close; staffing with dates; timeline events; arguments; related matters."""
from __future__ import annotations

from datetime import date
from typing import Any

from app import access
from app.audit import events as audit
from app.firm import FirmError, check_version, emit, guard, new_id, one, refresh_matter_profile, require_level

STATUSES = ("Open", "On hold", "Closed")
ROLES = ("Lead", "Counsel", "Associate", "Junior", "Paralegal", "Knowledge Manager")
EDITABLE = ("title", "opposing_party", "practice_area", "matter_type", "jurisdiction", "court", "office", "status",
            "closed_date", "outcome", "claim_amount", "legal_issues", "facts")
MAX_TEXT = 500
MAX_LIST = 50


def _text(value: Any, field: str, required: bool = False, limit: int = MAX_TEXT) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise FirmError(422, f"{field} is required")
        return None
    text = str(value).strip()
    if len(text) > limit:
        raise FirmError(422, f"{field} is limited to {limit} characters")
    return text


def _list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_LIST:
        raise FirmError(422, f"{field} must be a list of at most {MAX_LIST} items")
    return [t for t in (_text(v, field, limit=2000) for v in value) if t]


def _member(conn, member_id: str, field: str = "member") -> dict:
    row = one(conn, "SELECT member_id, name FROM members WHERE member_id = %s", (member_id,))
    if row is None:
        raise FirmError(422, f"Unknown {field} {member_id}")
    return row


def _matter(conn, matter_id: str) -> dict:
    row = one(conn, "SELECT * FROM matters WHERE matter_id = %s", (matter_id,))
    if row is None:
        raise FirmError(404, "Matter not found or access denied")
    return row


def _code(practice: str, office: str | None, year: int, n: int) -> str:
    prefix = "".join(ch for ch in practice.upper() if ch.isalpha())[:4] or "GEN"
    place = "".join(ch for ch in (office or "HQ").upper() if ch.isalpha())[:3] or "HQ"
    return f"{prefix}/{place}/{n:05d}/{year}"


# ── matters ──────────────────────────────────────────────────────────────────

@guard
def create_matter(conn, actor: str | None, data: dict) -> dict:
    """Open a matter: the creator (or the named lead) leads it; access defaults to the team."""
    access.require_permission(conn, actor, "matters.create")
    title = _text(data.get("title"), "title", required=True)
    client = one(conn, "SELECT client_id, name, status FROM clients WHERE client_id = %s", (data.get("client_id"),))
    if client is None:
        raise FirmError(422, "Choose an existing client (new clients go through intake and a conflict check)")
    if client["status"] != "active":
        raise FirmError(422, f"{client['name']} is {client['status']}: clear the conflict check before opening matters")
    practice = _text(data.get("practice_area"), "practice_area", required=True)
    mode = data.get("access_mode") or "team"
    if mode not in access.MODES:
        raise FirmError(422, f"access_mode must be one of {', '.join(access.MODES)}")
    lead = data.get("lead_member_id") or actor
    if not lead:
        raise FirmError(422, "A matter needs a lead")
    _member(conn, lead, "lead")
    team = data.get("team") or []
    for t in team:
        _member(conn, t.get("member_id", ""))
        if (t.get("role") or "Associate") not in ROLES:
            raise FirmError(422, f"role must be one of {', '.join(ROLES)}")
    opened = data.get("opened_date") or date.today().isoformat()
    year = int(str(opened)[:4])
    number = one(conn, "SELECT nextval('matter_number_seq') AS n")["n"]
    matter_id = f"MTR-{year}-{number:05d}"
    code = _text(data.get("matter_code"), "matter_code", limit=40) or _code(practice, data.get("office"), year, number)
    if one(conn, "SELECT 1 AS ok FROM matters WHERE lower(matter_code) = lower(%s)", (code,)):
        raise FirmError(409, f"Matter code {code} is already used")

    conn.execute(
        """INSERT INTO matters (matter_id, matter_code, title, client_id, client_name, opposing_party, practice_area,
                                matter_type, jurisdiction, court, opened_date, status, office, claim_amount,
                                legal_issues, facts, created_by_member_id, created_at, updated_at)
           VALUES (%(id)s, %(code)s, %(title)s, %(client_id)s, %(client_name)s, %(opp)s, %(practice)s, %(type)s,
                   %(jur)s, %(court)s, %(opened)s, 'Open', %(office)s, %(claim)s, %(issues)s, %(facts)s,
                   %(actor)s, now(), now())""",
        {"id": matter_id, "code": code, "title": title, "client_id": client["client_id"], "client_name": client["name"],
         "opp": _text(data.get("opposing_party"), "opposing_party"), "practice": practice,
         "type": _text(data.get("matter_type"), "matter_type") or "General", "jur": _text(data.get("jurisdiction"), "jurisdiction"),
         "court": _text(data.get("court"), "court"), "opened": opened, "office": _text(data.get("office"), "office"),
         "claim": data.get("claim_amount"), "issues": _list(data.get("legal_issues"), "legal_issues"),
         "facts": _list(data.get("facts"), "facts"), "actor": actor},
    )
    # The insert trigger created matter_access (open); set the chosen mode.
    conn.execute("UPDATE matter_access SET mode = %s, updated_by = %s, updated_at = now() WHERE matter_id = %s",
                 (mode, actor, matter_id))
    staff = [{"member_id": lead, "role": "Lead"}] + [t for t in team if t.get("member_id") != lead]
    for s in staff:
        conn.execute("INSERT INTO matter_members (matter_id, member_id, role_on_matter, started_at) VALUES (%s, %s, %s, %s) "
                     "ON CONFLICT DO NOTHING", (matter_id, s["member_id"], s.get("role") or "Associate", opened))
        if mode == "restricted":  # restricted is grants-only
            conn.execute(
                """INSERT INTO matter_grants (grant_id, matter_id, principal_type, principal_id, level, reason, granted_by)
                   VALUES (%s, %s, 'member', %s, %s, 'Matter team at opening', %s) ON CONFLICT DO NOTHING""",
                (new_id("GRT"), matter_id, s["member_id"], "manage" if s["role"] == "Lead" else "edit", actor))
    emit(conn, "matter.created", "matter", matter_id, actor=actor, matter_id=matter_id, payload={"title": title, "code": code})
    conn.commit()
    audit.record("matter.create", member_id=actor, object_type="matter", object_id=matter_id, matter_id=matter_id,
                 detail={"code": code, "client_id": client["client_id"], "mode": mode, "lead": lead})
    refresh_matter_profile(matter_id)
    return get_matter_brief(conn, matter_id)


def get_matter_brief(conn, matter_id: str) -> dict:
    row = one(conn, """SELECT m.matter_id, m.matter_code, m.title, m.client_id, m.client_name, m.practice_area, m.matter_type,
                              m.status, m.opened_date, m.closed_date, m.outcome, m.row_version, a.mode AS access_mode
                       FROM matters m LEFT JOIN matter_access a USING (matter_id) WHERE m.matter_id = %s""", (matter_id,))
    return row


@guard
def update_matter(conn, actor: str | None, matter_id: str, changes: dict, row_version: int | None) -> dict:
    require_level(conn, actor, matter_id, "manage")
    before = _matter(conn, matter_id)
    check_version(before["row_version"], row_version, "matter")
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise FirmError(422, f"Cannot change {', '.join(sorted(unknown))}")
    clean: dict[str, Any] = {}
    for key, value in changes.items():
        if key in ("legal_issues", "facts"):
            clean[key] = _list(value, key)
        elif key == "status":
            if value not in STATUSES:
                raise FirmError(422, f"status must be one of {', '.join(STATUSES)}")
            clean[key] = value
        elif key == "title":
            clean[key] = _text(value, key, required=True)
        elif key in ("closed_date", "claim_amount"):
            clean[key] = value
        else:
            clean[key] = _text(value, key, limit=2000 if key == "outcome" else MAX_TEXT)
    if clean.get("status") == "Closed" and not (clean.get("closed_date") or before["closed_date"]):
        clean["closed_date"] = date.today().isoformat()
    if clean.get("status") in ("Open", "On hold") and "closed_date" not in clean:
        clean["closed_date"] = None
    if not clean:
        return get_matter_brief(conn, matter_id)
    sets = ", ".join(f"{k} = %({k})s" for k in clean)
    conn.execute(f"UPDATE matters SET {sets}, updated_at = now(), row_version = row_version + 1 WHERE matter_id = %(mid)s",
                 {**clean, "mid": matter_id})
    diff = {k: {"from": before.get(k), "to": v} for k, v in clean.items() if before.get(k) != v}
    emit(conn, "matter.updated", "matter", matter_id, actor=actor, matter_id=matter_id, payload={"fields": sorted(diff)})
    conn.commit()
    audit.record("matter.update", member_id=actor, object_type="matter", object_id=matter_id, matter_id=matter_id,
                 detail={k: {"from": str(v["from"]), "to": str(v["to"])} for k, v in diff.items()})
    refresh_matter_profile(matter_id)
    return get_matter_brief(conn, matter_id)


# ── closing and reopening ────────────────────────────────────────────────────

def _open_items(conn, matter_id: str) -> dict:
    deadlines = conn.execute(
        """SELECT deadline_id, title, kind, due_date, owner_member_id, (confirmed_by_member_id IS NOT NULL) AS confirmed
           FROM court_deadlines WHERE matter_id = %s AND status = 'open' ORDER BY due_date""",
        (matter_id,),
    ).fetchall()
    requests = conn.execute(
        "SELECT request_id FROM access_requests WHERE matter_id = %s AND status = 'pending'", (matter_id,),
    ).fetchall()
    return {"deadlines": [dict(d) for d in deadlines], "pending_requests": len(requests)}


@guard
def close_check(conn, actor: str | None, matter_id: str) -> dict:
    """What is still open on the matter: shown before closing it."""
    require_level(conn, actor, matter_id, "manage")
    m = _matter(conn, matter_id)
    return {"matter_id": matter_id, "status": m["status"], **_open_items(conn, matter_id)}


@guard
def close_matter(conn, actor: str | None, matter_id: str, outcome: str, closed_date: str | None = None,
                 resolve_deadlines: bool = False, row_version: int | None = None) -> dict:
    """Resolve a matter: close it with an outcome. Open court dates must be handled first (or marked done here)."""
    require_level(conn, actor, matter_id, "manage")
    before = _matter(conn, matter_id)
    check_version(before["row_version"], row_version, "matter")
    if before["status"] == "Closed":
        raise FirmError(409, "The matter is already closed")
    outcome = _text(outcome, "outcome", required=True, limit=2000)
    day = str(closed_date or date.today().isoformat())
    if day < str(before.get("opened_date") or "0000-00-00"):
        raise FirmError(422, "The closing date is before the matter was opened")
    items = _open_items(conn, matter_id)
    if items["deadlines"] and not resolve_deadlines:
        raise FirmError(409, f"{len(items['deadlines'])} court date(s) are still open: complete them, or mark them done in this step",
                        {"open_deadlines": len(items["deadlines"])})
    if items["deadlines"]:
        conn.execute("UPDATE court_deadlines SET status = 'done' WHERE matter_id = %s AND status = 'open'", (matter_id,))
    conn.execute(
        "UPDATE matters SET status = 'Closed', outcome = %(o)s, closed_date = %(d)s, updated_at = now(), "
        "row_version = row_version + 1 WHERE matter_id = %(m)s",
        {"o": outcome, "d": day, "m": matter_id},
    )
    emit(conn, "matter.closed", "matter", matter_id, actor=actor, matter_id=matter_id, payload={"outcome": outcome[:200]})
    conn.commit()
    audit.record("matter.close", member_id=actor, object_type="matter", object_id=matter_id, matter_id=matter_id,
                 detail={"outcome": outcome[:500], "closed_date": day, "deadlines_marked_done": len(items["deadlines"]) if resolve_deadlines else 0})
    refresh_matter_profile(matter_id)
    return get_matter_brief(conn, matter_id)


@guard
def reopen_matter(conn, actor: str | None, matter_id: str, reason: str) -> dict:
    """Reopen a closed matter; the reason is recorded."""
    require_level(conn, actor, matter_id, "manage")
    before = _matter(conn, matter_id)
    if before["status"] != "Closed":
        raise FirmError(409, "Only a closed matter can be reopened")
    reason = _text(reason, "reason", required=True, limit=1000)
    conn.execute(
        "UPDATE matters SET status = 'Open', closed_date = NULL, updated_at = now(), row_version = row_version + 1 WHERE matter_id = %s",
        (matter_id,),
    )
    emit(conn, "matter.reopened", "matter", matter_id, actor=actor, matter_id=matter_id, payload={"reason": reason[:200]})
    conn.commit()
    audit.record("matter.reopen", member_id=actor, object_type="matter", object_id=matter_id, matter_id=matter_id,
                 detail={"reason": reason, "previous_outcome": str(before.get("outcome") or "")[:500]})
    refresh_matter_profile(matter_id)
    return get_matter_brief(conn, matter_id)


# ── staffing ─────────────────────────────────────────────────────────────────

@guard
def set_staff(conn, actor: str | None, matter_id: str, member_id: str, role: str, started_at: str | None,
              ended_at: str | None) -> dict:
    """Add someone to the matter team or change their role/dates (dates control team access)."""
    require_level(conn, actor, matter_id, "manage")
    _member(conn, member_id)
    if role not in ROLES:
        raise FirmError(422, f"role must be one of {', '.join(ROLES)}")
    if started_at and ended_at and str(ended_at) < str(started_at):
        raise FirmError(422, "ended_at is before started_at")
    if role != "Lead":
        leads = [r["member_id"] for r in conn.execute(
            "SELECT member_id FROM matter_members WHERE matter_id = %s AND lower(role_on_matter) = 'lead' "
            "AND (ended_at IS NULL OR ended_at >= current_date)", (matter_id,))]
        if leads == [member_id]:
            raise FirmError(409, "The matter needs a lead: make someone else lead first")
    if role == "Lead" and ended_at and str(ended_at) < date.today().isoformat():
        raise FirmError(422, "A lead's assignment cannot have ended")
    screened = one(conn, "SELECT 1 AS ok FROM matter_screens WHERE matter_id = %s AND member_id = %s", (matter_id, member_id))
    if screened:
        raise FirmError(409, "This person is screened from the matter and cannot be staffed on it")
    conn.execute(
        """INSERT INTO matter_members (matter_id, member_id, role_on_matter, started_at, ended_at)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (matter_id, member_id) DO UPDATE SET role_on_matter = EXCLUDED.role_on_matter,
               started_at = EXCLUDED.started_at, ended_at = EXCLUDED.ended_at""",
        (matter_id, member_id, role, started_at, ended_at),
    )
    emit(conn, "matter.team", "matter", matter_id, actor=actor, matter_id=matter_id,
         payload={"member_id": member_id, "role": role, "ended_at": ended_at})
    conn.commit()
    audit.record("matter.team.set", member_id=actor, object_type="matter", object_id=matter_id, matter_id=matter_id,
                 detail={"member_id": member_id, "role": role, "started_at": started_at, "ended_at": ended_at})
    return {"matter_id": matter_id, "team": team(conn, matter_id)}


@guard
def remove_staff(conn, actor: str | None, matter_id: str, member_id: str) -> dict:
    require_level(conn, actor, matter_id, "manage")
    row = one(conn, "SELECT role_on_matter FROM matter_members WHERE matter_id = %s AND member_id = %s", (matter_id, member_id))
    if row is None:
        raise FirmError(404, "Not on the matter team")
    if (row["role_on_matter"] or "").lower() == "lead":
        raise FirmError(409, "Make someone else lead before removing the lead")
    conn.execute("DELETE FROM matter_members WHERE matter_id = %s AND member_id = %s", (matter_id, member_id))
    emit(conn, "matter.team", "matter", matter_id, actor=actor, matter_id=matter_id, payload={"member_id": member_id, "removed": True})
    conn.commit()
    audit.record("matter.team.remove", member_id=actor, object_type="matter", object_id=matter_id, matter_id=matter_id,
                 detail={"member_id": member_id})
    return {"matter_id": matter_id, "team": team(conn, matter_id)}


def team(conn, matter_id: str) -> list[dict]:
    return conn.execute(
        """SELECT mm.member_id, mb.name, mb.role, mm.role_on_matter, mm.started_at, mm.ended_at,
                  (mm.ended_at IS NULL OR mm.ended_at >= current_date) AS active
           FROM matter_members mm JOIN members mb USING (member_id) WHERE mm.matter_id = %s
           ORDER BY (lower(mm.role_on_matter) = 'lead') DESC, active DESC, mb.name""", (matter_id,)).fetchall()


# ── timeline events ──────────────────────────────────────────────────────────

EVENT_KINDS = ("event", "filing", "hearing", "order", "correspondence", "meeting", "milestone")


def _event_fields(conn, matter_id: str, data: dict, partial: bool) -> dict:
    out: dict[str, Any] = {}
    if not partial or "occurred_on" in data:
        if not data.get("occurred_on"):
            raise FirmError(422, "occurred_on is required")
        out["occurred_on"] = data["occurred_on"]
    if not partial or "title" in data:
        out["title"] = _text(data.get("title"), "title", required=True)
    if "detail" in data:
        out["detail"] = _text(data.get("detail"), "detail", limit=5000) or ""
    if "kind" in data:
        if data["kind"] not in EVENT_KINDS:
            raise FirmError(422, f"kind must be one of {', '.join(EVENT_KINDS)}")
        out["kind"] = data["kind"]
    if data.get("source_document_id"):
        doc = one(conn, "SELECT matter_id FROM documents WHERE document_id = %s", (data["source_document_id"],))
        if doc is None or doc["matter_id"] != matter_id:
            raise FirmError(422, "The source document must belong to this matter")
        out["source_document_id"] = data["source_document_id"]
    return out


@guard
def add_event(conn, actor: str | None, matter_id: str, data: dict) -> dict:
    require_level(conn, actor, matter_id, "edit")
    fields = _event_fields(conn, matter_id, data, partial=False)
    event_id = new_id("EVT")
    cols = ["event_id", "matter_id", "created_by", *fields]
    conn.execute(f"INSERT INTO matter_events ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                 (event_id, matter_id, actor, *fields.values()))
    emit(conn, "matter.timeline", "matter_event", event_id, actor=actor, matter_id=matter_id, payload={"title": fields["title"]})
    conn.commit()
    audit.record("matter.event.add", member_id=actor, object_type="matter", object_id=matter_id, matter_id=matter_id,
                 detail={"event_id": event_id, "title": fields["title"], "occurred_on": str(fields["occurred_on"])})
    return one(conn, "SELECT * FROM matter_events WHERE event_id = %s", (event_id,))


@guard
def update_event(conn, actor: str | None, matter_id: str, event_id: str, data: dict, row_version: int | None) -> dict:
    require_level(conn, actor, matter_id, "edit")
    row = one(conn, "SELECT * FROM matter_events WHERE event_id = %s AND matter_id = %s", (event_id, matter_id))
    if row is None:
        raise FirmError(404, "Timeline entry not found")
    check_version(row["row_version"], row_version, "timeline entry")
    fields = _event_fields(conn, matter_id, data, partial=True)
    if fields:
        sets = ", ".join(f"{k} = %({k})s" for k in fields)
        conn.execute(f"UPDATE matter_events SET {sets}, updated_at = now(), row_version = row_version + 1 WHERE event_id = %(eid)s",
                     {**fields, "eid": event_id})
        emit(conn, "matter.timeline", "matter_event", event_id, actor=actor, matter_id=matter_id, payload={"updated": sorted(fields)})
        conn.commit()
        audit.record("matter.event.update", member_id=actor, object_type="matter", object_id=matter_id, matter_id=matter_id,
                     detail={"event_id": event_id, "fields": sorted(fields)})
    return one(conn, "SELECT * FROM matter_events WHERE event_id = %s", (event_id,))


@guard
def delete_event(conn, actor: str | None, matter_id: str, event_id: str) -> None:
    require_level(conn, actor, matter_id, "edit")
    row = one(conn, "DELETE FROM matter_events WHERE event_id = %s AND matter_id = %s RETURNING title", (event_id, matter_id))
    if row is None:
        raise FirmError(404, "Timeline entry not found")
    emit(conn, "matter.timeline", "matter_event", event_id, actor=actor, matter_id=matter_id, payload={"deleted": True})
    conn.commit()
    audit.record("matter.event.delete", member_id=actor, object_type="matter", object_id=matter_id, matter_id=matter_id,
                 detail={"event_id": event_id, "title": row["title"]})


# ── arguments ────────────────────────────────────────────────────────────────

POSITIONS = ("claimant", "respondent", "applicant", "defendant", "our client", "opposing party", "court")


def _argument_fields(data: dict, partial: bool) -> dict:
    out: dict[str, Any] = {}
    for key, required, limit in (("issue", True, 500), ("position", False, 100), ("argument", True, 20000), ("outcome", False, 2000)):
        if not partial or key in data:
            value = _text(data.get(key), key, required=required and not partial, limit=limit)
            if required and partial and key in data and not value:
                raise FirmError(422, f"{key} is required")
            out[key] = value
    if "supporting_documents" in data:
        out["supporting_documents"] = _list(data.get("supporting_documents"), "supporting_documents")
    return out


@guard
def add_argument(conn, actor: str | None, matter_id: str, data: dict) -> dict:
    require_level(conn, actor, matter_id, "edit")
    fields = _argument_fields(data, partial=False)
    if fields.get("supporting_documents"):
        _check_docs(conn, matter_id, fields["supporting_documents"])
    arg_id = new_id("ARG")
    cols = ["argument_id", "matter_id", "author_member_id", "created_at", "updated_at", *fields]
    conn.execute(f"INSERT INTO arguments ({', '.join(cols)}) VALUES (%s, %s, %s, now(), now(){', %s' * len(fields)})",
                 (arg_id, matter_id, actor, *fields.values()))
    emit(conn, "matter.arguments", "argument", arg_id, actor=actor, matter_id=matter_id, payload={"issue": fields["issue"]})
    conn.commit()
    audit.record("matter.argument.add", member_id=actor, object_type="matter", object_id=matter_id, matter_id=matter_id,
                 detail={"argument_id": arg_id, "issue": fields["issue"]})
    return one(conn, "SELECT * FROM arguments WHERE argument_id = %s", (arg_id,))


def _check_docs(conn, matter_id: str, doc_ids: list[str]) -> None:
    found = {r["document_id"] for r in conn.execute(
        "SELECT document_id FROM documents WHERE document_id = ANY(%s) AND matter_id = %s", (doc_ids, matter_id))}
    missing = [d for d in doc_ids if d not in found]
    if missing:
        raise FirmError(422, f"Supporting documents must belong to this matter: {', '.join(missing)}")


@guard
def update_argument(conn, actor: str | None, matter_id: str, argument_id: str, data: dict, row_version: int | None) -> dict:
    require_level(conn, actor, matter_id, "edit")
    row = one(conn, "SELECT * FROM arguments WHERE argument_id = %s AND matter_id = %s", (argument_id, matter_id))
    if row is None:
        raise FirmError(404, "Argument not found")
    check_version(row["row_version"], row_version, "argument")
    fields = _argument_fields(data, partial=True)
    if fields.get("supporting_documents"):
        _check_docs(conn, matter_id, fields["supporting_documents"])
    if fields:
        sets = ", ".join(f"{k} = %({k})s" for k in fields)
        conn.execute(f"UPDATE arguments SET {sets}, updated_at = now(), row_version = row_version + 1 WHERE argument_id = %(aid)s",
                     {**fields, "aid": argument_id})
        emit(conn, "matter.arguments", "argument", argument_id, actor=actor, matter_id=matter_id, payload={"updated": sorted(fields)})
        conn.commit()
        audit.record("matter.argument.update", member_id=actor, object_type="matter", object_id=matter_id, matter_id=matter_id,
                     detail={"argument_id": argument_id, "fields": sorted(fields)})
    return one(conn, "SELECT * FROM arguments WHERE argument_id = %s", (argument_id,))


@guard
def delete_argument(conn, actor: str | None, matter_id: str, argument_id: str) -> None:
    require_level(conn, actor, matter_id, "edit")
    row = one(conn, "DELETE FROM arguments WHERE argument_id = %s AND matter_id = %s RETURNING issue", (argument_id, matter_id))
    if row is None:
        raise FirmError(404, "Argument not found")
    emit(conn, "matter.arguments", "argument", argument_id, actor=actor, matter_id=matter_id, payload={"deleted": True})
    conn.commit()
    audit.record("matter.argument.delete", member_id=actor, object_type="matter", object_id=matter_id, matter_id=matter_id,
                 detail={"argument_id": argument_id, "issue": row["issue"]})


# ── related matters ──────────────────────────────────────────────────────────

RELATIONS = ("related", "follow_up_to", "parallel_proceeding", "appeal_of", "same_transaction", "precedent_for")


@guard
def link_matters(conn, actor: str | None, matter_id: str, related_id: str, relation: str, note: str) -> dict:
    """Linking needs edit on both matters: a link reveals each matter to the other's readers."""
    if matter_id == related_id:
        raise FirmError(422, "A matter cannot be related to itself")
    if relation not in RELATIONS:
        raise FirmError(422, f"relation must be one of {', '.join(RELATIONS)}")
    require_level(conn, actor, matter_id, "edit")
    try:
        require_level(conn, actor, related_id, "edit")
    except (access.AccessError, FirmError) as exc:
        raise FirmError(404 if getattr(exc, "status", 404) == 404 else 403,
                        "You need edit access to both matters to link them") from exc
    a, b = sorted((matter_id, related_id))
    conn.execute(
        """INSERT INTO matter_links (matter_id, related_matter_id, relation, note, created_by) VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (matter_id, related_matter_id) DO UPDATE SET relation = EXCLUDED.relation, note = EXCLUDED.note""",
        (a, b, relation, _text(note, "note", limit=1000) or "", actor),
    )
    for mid in (matter_id, related_id):
        emit(conn, "matter.related", "matter", mid, actor=actor, matter_id=mid, payload={"linked": related_id if mid == matter_id else matter_id})
    conn.commit()
    audit.record("matter.link", member_id=actor, object_type="matter", object_id=matter_id, matter_id=matter_id,
                 detail={"related_matter_id": related_id, "relation": relation})
    return {"matter_id": matter_id, "related_matter_id": related_id, "relation": relation}


@guard
def unlink_matters(conn, actor: str | None, matter_id: str, related_id: str) -> None:
    require_level(conn, actor, matter_id, "edit")
    a, b = sorted((matter_id, related_id))
    row = one(conn, "DELETE FROM matter_links WHERE matter_id = %s AND related_matter_id = %s RETURNING relation", (a, b))
    if row is None:
        raise FirmError(404, "These matters are not linked")
    emit(conn, "matter.related", "matter", matter_id, actor=actor, matter_id=matter_id, payload={"unlinked": related_id})
    conn.commit()
    audit.record("matter.unlink", member_id=actor, object_type="matter", object_id=matter_id, matter_id=matter_id,
                 detail={"related_matter_id": related_id})
