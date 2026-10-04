"""Bring clients, people and matters in from a spreadsheet (CSV).

Two steps, always: ``preview`` checks every row and saves nothing; ``apply`` creates the rows that pass.
Each row goes through the same rules as creating it by hand (permissions, conflict checks for clients,
duplicates, known roles and clients), so an import can never do what the interface would refuse.
Clients with possible conflicts are not created: they are left for the conflict queue.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any

from app import access
from app.audit import events as audit
from app.firm import FirmError, clients as client_svc, guard, matters as matter_svc, one, people as people_svc

MAX_ROWS = 500
MAX_BYTES = 1_000_000

TEMPLATES: dict[str, dict[str, Any]] = {
    "clients": {
        "columns": ["name", "industry", "headquarters", "aliases"],
        "required": ["name"],
        "example": ["Northbridge Growth Fund III", "Private equity", "Mumbai", "Northbridge III; NGF III"],
        "permission": "clients.create",
    },
    "people": {
        "columns": ["name", "title", "office", "email", "practice_areas", "roles"],
        "required": ["name"],
        "example": ["Asha Menon", "Associate", "Delhi", "asha.menon@example.com", "Energy; Arbitration", "fee_earner"],
        "permission": "users.manage",
    },
    "matters": {
        "columns": ["title", "client", "practice_area", "office", "opposing_party", "court", "opened_date", "lead_email"],
        "required": ["title", "client", "practice_area"],
        "example": ["Tariff petition 12 of 2026", "Northbridge Growth Fund III", "Regulatory", "Delhi", "State Discom", "CERC", "2026-10-01", "asha.menon@example.com"],
        "permission": "matters.create",
    },
}


def template_csv(entity: str) -> str:
    t = _template(entity)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(t["columns"])
    w.writerow(t["example"])
    return out.getvalue()


def _template(entity: str) -> dict[str, Any]:
    if entity not in TEMPLATES:
        raise FirmError(404, f"Cannot import {entity}: choose clients, people or matters")
    return TEMPLATES[entity]


def _parts(value: str) -> list[str]:
    return [p.strip() for p in re.split(r"[;|]", value or "") if p.strip()]


def parse(entity: str, raw: bytes) -> list[dict[str, str]]:
    t = _template(entity)
    if len(raw) > MAX_BYTES:
        raise FirmError(413, "The file is larger than 1 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FirmError(422, "Save the file as CSV in UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise FirmError(422, "The file is empty")
    header = [h.strip().lower() for h in reader.fieldnames]
    missing = [c for c in t["required"] if c not in header]
    if missing:
        raise FirmError(422, f"The file needs the column(s): {', '.join(missing)}. Download the template.")
    rows = []
    for rec in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in rec.items()}
        if any(row.values()):
            rows.append(row)
        if len(rows) > MAX_ROWS:
            raise FirmError(422, f"At most {MAX_ROWS} rows at a time")
    if not rows:
        raise FirmError(422, "There are no rows below the header")
    return rows


# ── row checks (nothing is written) ──────────────────────────────────────────

def _check_clients(conn, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for i, r in enumerate(rows, start=2):
        name = r.get("name", "")
        key = re.sub(r"\W+", " ", name.lower()).strip()
        res: dict[str, Any] = {"row": i, "label": name or "(no name)", "status": "ok", "message": ""}
        if not name or len(name) > 300:
            res.update(status="error", message="The name is required (at most 300 characters)")
        elif key in seen:
            res.update(status="error", message="The same name appears earlier in the file")
        elif one(conn, "SELECT 1 AS ok FROM clients WHERE lower(name) = lower(%s)", (name,)):
            res.update(status="error", message="Already a client")
        else:
            hits = client_svc._search(conn, name)
            if hits:
                res.update(status="review", message=f"{len(hits)} possible conflict(s): left for the conflict queue, not imported")
        seen.add(key)
        out.append(res)
    return out


def _check_people(conn, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    known = {r["role_key"] for r in conn.execute("SELECT role_key FROM firm_roles")}
    seen_email: set[str] = set()
    out = []
    for i, r in enumerate(rows, start=2):
        name, email = r.get("name", ""), r.get("email", "").lower()
        res: dict[str, Any] = {"row": i, "label": name or "(no name)", "status": "ok", "message": ""}
        roles = _parts(r.get("roles", "")) or ["fee_earner"]
        if not name:
            res.update(status="error", message="The name is required")
        elif email and ("@" not in email or len(email) > 200):
            res.update(status="error", message="The email is not valid")
        elif email and (email in seen_email or one(conn, "SELECT 1 AS ok FROM members WHERE lower(email) = %s", (email,))):
            res.update(status="error", message="Someone already has this email")
        elif set(roles) - known:
            res.update(status="error", message=f"Unknown role(s): {', '.join(sorted(set(roles) - known))}")
        if email:
            seen_email.add(email)
        out.append(res)
    return out


def _check_matters(conn, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out = []
    for i, r in enumerate(rows, start=2):
        title, cname = r.get("title", ""), r.get("client", "")
        res: dict[str, Any] = {"row": i, "label": title or "(no title)", "status": "ok", "message": ""}
        client = one(conn, "SELECT client_id, name, status FROM clients WHERE lower(name) = lower(%s)", (cname,)) if cname else None
        opened = r.get("opened_date", "")
        if not title or not r.get("practice_area"):
            res.update(status="error", message="The title and practice area are required")
        elif client is None:
            res.update(status="error", message=f"No client named “{cname}”. Add the client first")
        elif client["status"] != "active":
            res.update(status="error", message=f"{client['name']} is {client['status']}: matters cannot be opened yet")
        elif opened and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", opened):
            res.update(status="error", message="opened_date must look like 2026-10-01")
        elif r.get("lead_email") and not one(conn, "SELECT 1 AS ok FROM members WHERE lower(email) = %s AND active", (r["lead_email"].lower(),)):
            res.update(status="error", message=f"No active person has the email {r['lead_email']}")
        elif (client["client_id"], title.lower()) in seen:
            res.update(status="error", message="The same matter appears earlier in the file")
        if client:
            seen.add((client["client_id"], title.lower()))
        out.append(res)
    return out


CHECKS = {"clients": _check_clients, "people": _check_people, "matters": _check_matters}


def _report(entity: str, results: list[dict[str, Any]], created: int = 0) -> dict[str, Any]:
    return {
        "entity": entity, "total": len(results), "ok": sum(1 for r in results if r["status"] in ("ok", "created")),
        "review": sum(1 for r in results if r["status"] == "review"), "errors": sum(1 for r in results if r["status"] == "error"),
        "created": created, "rows": results,
    }


@guard
def preview(conn, actor: str | None, entity: str, raw: bytes) -> dict[str, Any]:
    t = _template(entity)
    access.require_permission(conn, actor, t["permission"])
    return _report(entity, CHECKS[entity](conn, parse(entity, raw)))


@guard
def apply(conn, actor: str | None, entity: str, raw: bytes) -> dict[str, Any]:
    t = _template(entity)
    access.require_permission(conn, actor, t["permission"])
    rows = parse(entity, raw)
    results = CHECKS[entity](conn, rows)
    created = 0
    for res, row in zip(results, rows):
        if res["status"] != "ok":
            continue
        try:
            _create(conn, actor, entity, row)
            res["status"], res["message"] = "created", "Created"
            created += 1
        except FirmError as exc:
            conn.rollback()
            res["status"], res["message"] = "error", exc.detail
    audit.record("import.apply", member_id=actor, object_type=entity, object_id="csv",
                 detail={"rows": len(rows), "created": created, "errors": sum(1 for r in results if r["status"] == "error")})
    return _report(entity, results, created)


def _create(conn, actor: str | None, entity: str, row: dict[str, str]) -> None:
    if entity == "clients":
        check = client_svc.run_check(conn, actor, [row["name"]], "Spreadsheet import")
        if check.get("decision") not in ("clear", "waived") and check.get("status") != "clear":
            raise FirmError(409, "A conflict check found matches: decide it in the conflict queue")
        client_svc.create_client(conn, actor, {
            "name": row["name"], "check_id": check["check_id"], "industry": row.get("industry") or None,
            "headquarters": row.get("headquarters") or None, "aliases": _parts(row.get("aliases", "")),
        })
    elif entity == "people":
        people_svc.create_person(conn, actor, {
            "name": row["name"], "role": row.get("title") or "Associate", "office": row.get("office") or None,
            "email": row.get("email") or None, "practice_areas": _parts(row.get("practice_areas", "")),
            "roles": _parts(row.get("roles", "")) or ["fee_earner"],
        })
    else:
        client = one(conn, "SELECT client_id FROM clients WHERE lower(name) = lower(%s)", (row["client"],))
        lead = one(conn, "SELECT member_id FROM members WHERE lower(email) = %s AND active", (row["lead_email"].lower(),)) if row.get("lead_email") else None
        matter_svc.create_matter(conn, actor, {
            "title": row["title"], "client_id": client["client_id"], "practice_area": row["practice_area"],
            "office": row.get("office") or None, "opposing_party": row.get("opposing_party") or None,
            "court": row.get("court") or None, "opened_date": row.get("opened_date") or None,
            "lead_member_id": lead["member_id"] if lead else None,
        })
