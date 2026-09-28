"""Calendar: court deadlines and events, scoped Mine / My team / Matter / Firm; second-lawyer
confirmation of court deadlines; private ICS subscriptions.

Visibility: matter-linked items follow the matter ACL; personal events (no matter) are seen
by their owner and attendees only.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from app import access
from app.audit import events as audit
from app.firm import FirmError, check_version, emit, guard, new_id, one, require_level
from app.firm.feed import _visible_matters

EVENT_KINDS = ("hearing", "filing", "limitation", "compliance", "meeting", "internal", "out_of_office")
DEADLINE_KINDS = ("hearing", "filing", "limitation", "compliance")
CONFIRM_KINDS = ("hearing", "filing", "limitation")   # court dates a second lawyer must confirm
SCOPES = ("mine", "team", "matter", "firm")
MAX_RANGE_DAYS = 400


def _day(value: Any, field: str) -> date:
    try:
        return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise FirmError(422, f"{field} must be a date (YYYY-MM-DD)") from exc


def _when(value: Any, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise FirmError(422, f"{field} must be a date-time") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _my_people(conn, member_id: str) -> set[str]:
    """My team: people who share a team with me or are staffed on my (current) matters."""
    rows = conn.execute(
        """SELECT tm2.member_id FROM team_members tm1 JOIN team_members tm2 USING (team_id) WHERE tm1.member_id = %(m)s
           UNION
           SELECT mm2.member_id FROM matter_members mm1 JOIN matter_members mm2 USING (matter_id)
           WHERE mm1.member_id = %(m)s AND (mm1.ended_at IS NULL OR mm1.ended_at >= current_date)
             AND (mm2.ended_at IS NULL OR mm2.ended_at >= current_date)""", {"m": member_id}).fetchall()
    return {r["member_id"] for r in rows} | {member_id}


def _my_matters(conn, member_id: str) -> set[str]:
    return {r["matter_id"] for r in conn.execute(
        "SELECT matter_id FROM matter_members WHERE member_id = %s AND (ended_at IS NULL OR ended_at >= current_date)", (member_id,))}


@guard
def list_items(conn, member_id: str | None, start: Any, end: Any, scope: str = "mine", matter_id: str | None = None) -> dict:
    lo, hi = _day(start, "from"), _day(end, "to")
    if hi < lo or (hi - lo).days > MAX_RANGE_DAYS:
        raise FirmError(422, f"Choose a range of at most {MAX_RANGE_DAYS} days")
    if scope not in SCOPES:
        raise FirmError(422, f"scope must be one of {', '.join(SCOPES)}")
    if scope == "matter":
        if not matter_id:
            raise FirmError(422, "Choose a matter")
        require_level(conn, member_id, matter_id, "read")
    visible = _visible_matters(conn, member_id)
    people = _my_people(conn, member_id) if member_id and scope == "team" else set()
    mine = _my_matters(conn, member_id) if member_id and scope in ("team",) else set()

    deadlines = conn.execute(
        """SELECT c.*, m.matter_code, m.title AS matter_title, a.mode AS access_mode, o.name AS owner_name,
                  cf.name AS confirmed_by_name
           FROM court_deadlines c JOIN matters m USING (matter_id)
           LEFT JOIN matter_access a ON a.matter_id = c.matter_id
           LEFT JOIN members o ON o.member_id = c.owner_member_id
           LEFT JOIN members cf ON cf.member_id = c.confirmed_by_member_id
           WHERE c.due_date >= %s AND c.due_date <= %s""", (lo, hi)).fetchall()
    events = conn.execute(
        """SELECT e.*, m.matter_code, m.title AS matter_title, a.mode AS access_mode, o.name AS owner_name
           FROM calendar_events e LEFT JOIN matters m USING (matter_id)
           LEFT JOIN matter_access a ON a.matter_id = e.matter_id
           LEFT JOIN members o ON o.member_id = e.owner_member_id
           WHERE e.starts_at < %s AND e.ends_at >= %s""",
        (datetime.combine(hi + timedelta(days=1), time.min, timezone.utc), datetime.combine(lo, time.min, timezone.utc))).fetchall()

    def can_see(row: dict) -> bool:
        if row.get("matter_id"):
            return visible is None or row["matter_id"] in visible
        return member_id is None or row["owner_member_id"] == member_id or member_id in (row.get("attendees") or [])

    def in_scope(row: dict, is_event: bool) -> bool:
        if scope == "firm" or member_id is None:
            return True
        if scope == "matter":
            return row.get("matter_id") == matter_id
        involved = {row.get("owner_member_id"), row.get("created_by_member_id"), *(row.get("attendees") or [])}
        if scope == "mine":
            return member_id in involved
        return bool(involved & people) or row.get("matter_id") in mine

    items = []
    for d in deadlines:
        if can_see(d) and in_scope(d, False):
            items.append(_deadline_item(conn, d, member_id))
    for e in events:
        if can_see(e) and in_scope(e, True):
            items.append(_event_item(conn, e, member_id))
    items.sort(key=lambda x: (x["start"], x["title"]))
    return {"from": lo.isoformat(), "to": hi.isoformat(), "scope": scope, "items": items}


def _level(conn, member_id: str | None, matter_id: str | None) -> str:
    return access.matter_level(conn, member_id, matter_id) if matter_id else "none"


def _deadline_item(conn, d: dict, member_id: str | None) -> dict:
    needs = d["kind"] in CONFIRM_KINDS
    return {
        "id": d["deadline_id"], "source": "deadline", "title": d["title"], "kind": d["kind"],
        "start": d["due_date"].isoformat(), "end": d["due_date"].isoformat(), "all_day": True,
        "matter_id": d["matter_id"], "matter_code": d["matter_code"], "matter_title": d["matter_title"],
        "owner_id": d["owner_member_id"], "owner_name": d["owner_name"], "attendees": [], "status": d["status"],
        "court": d["court"], "notes": d["notes"], "location": d["court"] or "",
        "confirmed": (d["confirmed_at"] is not None) if needs else None,
        "confirmed_by": d["confirmed_by_name"], "created_by": d.get("created_by_member_id"),
        "restricted": d.get("access_mode") == "restricted", "row_version": d["row_version"],
        "can_edit": _level(conn, member_id, d["matter_id"]) in ("edit", "manage"),
    }


def _event_item(conn, e: dict, member_id: str | None) -> dict:
    return {
        "id": e["event_id"], "source": "event", "title": e["title"], "kind": e["kind"],
        "start": e["starts_at"].isoformat(), "end": e["ends_at"].isoformat(), "all_day": e["all_day"],
        "matter_id": e["matter_id"], "matter_code": e["matter_code"], "matter_title": e["matter_title"],
        "owner_id": e["owner_member_id"], "owner_name": e["owner_name"], "attendees": e["attendees"], "status": "open",
        "location": e["location"], "notes": e["detail"], "confirmed": None,
        "restricted": e.get("access_mode") == "restricted", "row_version": e["row_version"],
        "can_edit": member_id is None or e["owner_member_id"] == member_id
        or (bool(e["matter_id"]) and _level(conn, member_id, e["matter_id"]) in ("edit", "manage")),
    }


# ── events ───────────────────────────────────────────────────────────────────

def _event_fields(conn, member_id: str | None, data: dict, partial: bool, matter_id: str | None) -> dict:
    out: dict[str, Any] = {}
    if not partial or "title" in data:
        title = (data.get("title") or "").strip()
        if not title or len(title) > 300:
            raise FirmError(422, "title is required (at most 300 characters)")
        out["title"] = title
    if "kind" in data or not partial:
        kind = data.get("kind") or "meeting"
        if kind not in EVENT_KINDS:
            raise FirmError(422, f"kind must be one of {', '.join(EVENT_KINDS)}")
        out["kind"] = kind
    if "all_day" in data:
        out["all_day"] = bool(data["all_day"])
    if not partial or "starts_at" in data:
        out["starts_at"] = _when(data.get("starts_at"), "starts_at")
    if not partial or "ends_at" in data or "starts_at" in data:
        start = out.get("starts_at")
        out["ends_at"] = _when(data["ends_at"], "ends_at") if data.get("ends_at") else (start + timedelta(hours=1) if start else None)
        if out["ends_at"] is None:
            out.pop("ends_at")
        elif start and out["ends_at"] < start:
            raise FirmError(422, "The event ends before it starts")
    for key, limit in (("location", 300), ("detail", 5000)):
        if key in data:
            out[key] = (data.get(key) or "")[:limit]
    if "attendees" in data:
        attendees = list(dict.fromkeys(str(a) for a in (data.get("attendees") or [])))[:100]
        known = {r["member_id"] for r in conn.execute("SELECT member_id FROM members WHERE member_id = ANY(%s)", (attendees,))}
        missing = [a for a in attendees if a not in known]
        if missing:
            raise FirmError(422, f"Unknown attendees: {', '.join(missing)}")
        if matter_id:
            outside = [a for a in attendees if not access.can_see_matter(conn, a, matter_id)]
            if outside:
                raise FirmError(422, "Some attendees cannot see this matter; give them access first")
        out["attendees"] = attendees
    return out


@guard
def create_event(conn, member_id: str | None, data: dict) -> dict:
    if member_id is None:
        raise FirmError(400, "Sign in to add events")
    matter_id = data.get("matter_id") or None
    if matter_id:
        require_level(conn, member_id, matter_id, "edit")
    fields = _event_fields(conn, member_id, data, partial=False, matter_id=matter_id)
    event_id = new_id("CAL")
    cols = ["event_id", "matter_id", "owner_member_id", "created_by", *fields]
    conn.execute(f"INSERT INTO calendar_events ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                 (event_id, matter_id, member_id, member_id, *fields.values()))
    emit(conn, "calendar.event", "calendar_event", event_id, actor=member_id, matter_id=matter_id, payload={"title": fields["title"]})
    conn.commit()
    audit.record("calendar.event.create", member_id=member_id, object_type="calendar_event", object_id=event_id, matter_id=matter_id,
                 detail={"title": fields["title"], "starts_at": str(fields["starts_at"])})
    return _event_item(conn, _event_row(conn, event_id), member_id)


def _event_row(conn, event_id: str) -> dict:
    row = one(conn, """SELECT e.*, m.matter_code, m.title AS matter_title, a.mode AS access_mode, o.name AS owner_name
                       FROM calendar_events e LEFT JOIN matters m USING (matter_id)
                       LEFT JOIN matter_access a ON a.matter_id = e.matter_id
                       LEFT JOIN members o ON o.member_id = e.owner_member_id WHERE e.event_id = %s""", (event_id,))
    if row is None:
        raise FirmError(404, "Event not found")
    return row


def _require_event_edit(conn, member_id: str | None, row: dict) -> None:
    if member_id is None or row["owner_member_id"] == member_id:
        return
    if row["matter_id"] and _level(conn, member_id, row["matter_id"]) in ("edit", "manage"):
        return
    visible = row["matter_id"] and access.can_see_matter(conn, member_id, row["matter_id"])
    if visible or member_id in (row["attendees"] or []):
        raise FirmError(403, "Only the organiser or someone who can edit the matter can change this event")
    raise FirmError(404, "Event not found")


@guard
def update_event(conn, member_id: str | None, event_id: str, data: dict, row_version: int | None) -> dict:
    row = _event_row(conn, event_id)
    _require_event_edit(conn, member_id, row)
    check_version(row["row_version"], row_version, "event")
    if "starts_at" not in data and "ends_at" in data:
        data = {**data, "starts_at": row["starts_at"]}
    fields = _event_fields(conn, member_id, data, partial=True, matter_id=row["matter_id"])
    if fields:
        sets = ", ".join(f"{k} = %({k})s" for k in fields)
        conn.execute(f"UPDATE calendar_events SET {sets}, updated_at = now(), row_version = row_version + 1 WHERE event_id = %(eid)s",
                     {**fields, "eid": event_id})
        emit(conn, "calendar.event", "calendar_event", event_id, actor=member_id, matter_id=row["matter_id"], payload={"updated": sorted(fields)})
        conn.commit()
        audit.record("calendar.event.update", member_id=member_id, object_type="calendar_event", object_id=event_id,
                     matter_id=row["matter_id"], detail={"fields": sorted(fields)})
    return _event_item(conn, _event_row(conn, event_id), member_id)


@guard
def delete_event(conn, member_id: str | None, event_id: str) -> None:
    row = _event_row(conn, event_id)
    _require_event_edit(conn, member_id, row)
    conn.execute("DELETE FROM calendar_events WHERE event_id = %s", (event_id,))
    emit(conn, "calendar.event", "calendar_event", event_id, actor=member_id, matter_id=row["matter_id"], payload={"deleted": True})
    conn.commit()
    audit.record("calendar.event.delete", member_id=member_id, object_type="calendar_event", object_id=event_id,
                 matter_id=row["matter_id"], detail={"title": row["title"]})


# ── court deadlines ──────────────────────────────────────────────────────────

def _deadline_row(conn, deadline_id: str) -> dict:
    row = one(conn, """SELECT c.*, m.matter_code, m.title AS matter_title, a.mode AS access_mode, o.name AS owner_name,
                              cf.name AS confirmed_by_name
                       FROM court_deadlines c JOIN matters m USING (matter_id)
                       LEFT JOIN matter_access a ON a.matter_id = c.matter_id
                       LEFT JOIN members o ON o.member_id = c.owner_member_id
                       LEFT JOIN members cf ON cf.member_id = c.confirmed_by_member_id
                       WHERE c.deadline_id = %s""", (deadline_id,))
    if row is None:
        raise FirmError(404, "Deadline not found")
    return row


@guard
def create_deadline(conn, member_id: str | None, data: dict) -> dict:
    matter_id = data.get("matter_id")
    if not matter_id:
        raise FirmError(422, "A court deadline belongs to a matter")
    require_level(conn, member_id, matter_id, "edit")
    title = (data.get("title") or "").strip()
    if not title:
        raise FirmError(422, "title is required")
    kind = data.get("kind") or "filing"
    if kind not in DEADLINE_KINDS:
        raise FirmError(422, f"kind must be one of {', '.join(DEADLINE_KINDS)}")
    due = _day(data.get("due_date"), "due_date")
    owner = data.get("owner_member_id") or member_id
    if owner and not access.can_see_matter(conn, owner, matter_id):
        raise FirmError(422, "The owner must be able to see the matter")
    deadline_id = new_id("DL")
    confirmed_at = None if kind in CONFIRM_KINDS else datetime.now(timezone.utc)
    conn.execute(
        """INSERT INTO court_deadlines (deadline_id, matter_id, title, kind, due_date, court, owner_member_id, status, notes,
                                        created_by_member_id, confirmed_by_member_id, confirmed_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s, %s, %s, %s)""",
        (deadline_id, matter_id, title[:300], kind, due, (data.get("court") or None), owner, (data.get("notes") or None),
         member_id, member_id if confirmed_at else None, confirmed_at),
    )
    emit(conn, "calendar.deadline", "deadline", deadline_id, actor=member_id, matter_id=matter_id, payload={"title": title, "due": due})
    conn.commit()
    audit.record("deadline.create", member_id=member_id, object_type="deadline", object_id=deadline_id, matter_id=matter_id,
                 detail={"title": title, "kind": kind, "due_date": due.isoformat()})
    return _deadline_item(conn, _deadline_row(conn, deadline_id), member_id)


@guard
def update_deadline(conn, member_id: str | None, deadline_id: str, data: dict, row_version: int | None) -> dict:
    row = _deadline_row(conn, deadline_id)
    require_level(conn, member_id, row["matter_id"], "edit")
    check_version(row["row_version"], row_version, "deadline")
    fields: dict[str, Any] = {}
    if "title" in data:
        if not (data["title"] or "").strip():
            raise FirmError(422, "title is required")
        fields["title"] = data["title"].strip()[:300]
    if "kind" in data:
        if data["kind"] not in DEADLINE_KINDS:
            raise FirmError(422, f"kind must be one of {', '.join(DEADLINE_KINDS)}")
        fields["kind"] = data["kind"]
    if "due_date" in data:
        fields["due_date"] = _day(data["due_date"], "due_date")
    if "status" in data:
        if data["status"] not in ("open", "done"):
            raise FirmError(422, "status must be open or done")
        fields["status"] = data["status"]
    for key in ("court", "notes"):
        if key in data:
            fields[key] = data[key] or None
    if "owner_member_id" in data:
        if not access.can_see_matter(conn, data["owner_member_id"], row["matter_id"]):
            raise FirmError(422, "The owner must be able to see the matter")
        fields["owner_member_id"] = data["owner_member_id"]
    # A new date or kind is a new court date: it needs confirming again.
    kind = fields.get("kind", row["kind"])
    changed_date = "due_date" in fields and fields["due_date"] != row["due_date"]
    if kind in CONFIRM_KINDS and (changed_date or ("kind" in fields and fields["kind"] != row["kind"])):
        fields["confirmed_at"] = None
        fields["confirmed_by_member_id"] = None
    if fields:
        sets = ", ".join(f"{k} = %({k})s" for k in fields)
        conn.execute(f"UPDATE court_deadlines SET {sets}, row_version = row_version + 1 WHERE deadline_id = %(did)s",
                     {**fields, "did": deadline_id})
        emit(conn, "calendar.deadline", "deadline", deadline_id, actor=member_id, matter_id=row["matter_id"], payload={"updated": sorted(fields)})
        conn.commit()
        audit.record("deadline.update", member_id=member_id, object_type="deadline", object_id=deadline_id, matter_id=row["matter_id"],
                     detail={k: str(v) for k, v in fields.items()})
    return _deadline_item(conn, _deadline_row(conn, deadline_id), member_id)


@guard
def confirm_deadline(conn, member_id: str | None, deadline_id: str) -> dict:
    """A second lawyer checks the court date against the order or rules and confirms it."""
    row = _deadline_row(conn, deadline_id)
    require_level(conn, member_id, row["matter_id"], "edit")
    if row["kind"] not in CONFIRM_KINDS:
        raise FirmError(422, "Only hearing, filing and limitation dates need confirming")
    if row["confirmed_at"] is not None:
        raise FirmError(409, "Already confirmed")
    if member_id is not None:
        if member_id in (row["created_by_member_id"], row["owner_member_id"]):
            raise FirmError(403, "A court date is confirmed by a second lawyer, not the one who entered or owns it")
        lawyer = one(conn, "SELECT is_lawyer FROM members WHERE member_id = %s", (member_id,))
        if not lawyer or not lawyer["is_lawyer"]:
            raise FirmError(403, "Court dates are confirmed by a lawyer")
    conn.execute("UPDATE court_deadlines SET confirmed_by_member_id = %s, confirmed_at = now(), row_version = row_version + 1 "
                 "WHERE deadline_id = %s", (member_id, deadline_id))
    emit(conn, "calendar.deadline", "deadline", deadline_id, actor=member_id, matter_id=row["matter_id"], payload={"confirmed": True})
    conn.commit()
    audit.record("deadline.confirm", member_id=member_id, object_type="deadline", object_id=deadline_id, matter_id=row["matter_id"],
                 detail={"due_date": row["due_date"].isoformat(), "kind": row["kind"]})
    return _deadline_item(conn, _deadline_row(conn, deadline_id), member_id)


# ── ICS subscriptions ────────────────────────────────────────────────────────

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@guard
def create_feed(conn, member_id: str | None, show_restricted: bool = False) -> dict:
    """A new private feed URL (replaces the old one). The token is shown once."""
    if member_id is None:
        raise FirmError(400, "Sign in to subscribe")
    token = secrets.token_urlsafe(32)
    conn.execute("""INSERT INTO calendar_feeds (member_id, token_hash, show_restricted) VALUES (%s, %s, %s)
                    ON CONFLICT (member_id) DO UPDATE SET token_hash = EXCLUDED.token_hash,
                        show_restricted = EXCLUDED.show_restricted, created_at = now(), last_used_at = NULL""",
                 (member_id, _hash(token), bool(show_restricted)))
    conn.commit()
    audit.record("calendar.feed.create", member_id=member_id, object_type="calendar_feed", object_id=member_id,
                 detail={"show_restricted": bool(show_restricted)})
    return {"token": token, "show_restricted": bool(show_restricted)}


@guard
def feed_status(conn, member_id: str | None) -> dict:
    row = one(conn, "SELECT created_at, last_used_at, show_restricted FROM calendar_feeds WHERE member_id = %s", (member_id,))
    return {"active": row is not None, **(row or {})}


@guard
def revoke_feed(conn, member_id: str | None) -> None:
    conn.execute("DELETE FROM calendar_feeds WHERE member_id = %s", (member_id,))
    conn.commit()
    audit.record("calendar.feed.revoke", member_id=member_id, object_type="calendar_feed", object_id=member_id or "")


def _ics_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545: lines of at most 75 octets, continued with a leading space."""
    raw = line.encode()
    if len(raw) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        b = ch.encode()
        if len(cur) + len(b) > (75 if not parts else 74):
            parts.append(cur.decode())
            cur = b""
        cur += b
    parts.append(cur.decode())
    return "\r\n ".join(parts)


def ics_for_token(conn, token: str) -> str | None:
    feed = one(conn, "SELECT member_id, show_restricted FROM calendar_feeds WHERE token_hash = %s", (_hash(token),))
    if feed is None:
        return None
    member_id = feed["member_id"]
    conn.execute("UPDATE calendar_feeds SET last_used_at = now() WHERE member_id = %s", (member_id,))
    conn.commit()
    today = date.today()
    items = list_items(conn, member_id, today - timedelta(days=31), today + timedelta(days=365), "mine")["items"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Precentis//Calendar//EN", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:Precentis — my calendar"]
    for it in items:
        hidden = it["restricted"] and not feed["show_restricted"]
        title = "Restricted matter" if hidden else it["title"]
        if not hidden and it.get("matter_code"):
            title = f"{title} ({it['matter_code']})"
        if it["source"] == "deadline" and it["confirmed"] is False:
            title = f"[UNCONFIRMED] {title}"
        lines += ["BEGIN:VEVENT", f"UID:{it['id']}@precentis", f"DTSTAMP:{stamp}", _fold(f"SUMMARY:{_ics_text(title)}")]
        if it["all_day"]:
            start = date.fromisoformat(it["start"][:10])
            end = date.fromisoformat(it["end"][:10]) + timedelta(days=1)
            lines += [f"DTSTART;VALUE=DATE:{start:%Y%m%d}", f"DTEND;VALUE=DATE:{end:%Y%m%d}"]
        else:
            s = datetime.fromisoformat(it["start"]).astimezone(timezone.utc)
            e = datetime.fromisoformat(it["end"]).astimezone(timezone.utc)
            lines += [f"DTSTART:{s:%Y%m%dT%H%M%SZ}", f"DTEND:{e:%Y%m%dT%H%M%SZ}"]
        if not hidden and it.get("location"):
            lines.append(_fold(f"LOCATION:{_ics_text(it['location'])}"))
        if not hidden and it.get("notes"):
            lines.append(_fold(f"DESCRIPTION:{_ics_text(it['notes'])}"))
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
