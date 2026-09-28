"""Client intake with conflict checks.

1. Someone who may take on clients runs a conflict check on the names involved (the
   prospective client, its group companies, the other side).
2. The check searches every client (name, aliases, subsidiaries) and every matter's
   opposing party — across the whole firm, walls included, because a conflict hidden
   behind a wall is still a conflict. The requester sees hits on matters they can see;
   hits on matters they cannot see say only that one exists and to ask Risk. Risk sees all.
3. A check with no hits is clear. A check with hits waits for Risk (conflicts.decide):
   clear, conflict or waived.
4. The client is created against the check: active once it is clear/waived, prospective
   while it waits, declined on a conflict.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app import access
from app.audit import events as audit
from app.firm import FirmError, emit, guard, new_id, one

SIMILARITY = 0.45
DECISIONS = ("clear", "conflict", "waived")
MAX_NAMES = 12


def _norm(name: str) -> str:
    """Company names compared without legal-form noise."""
    text = re.sub(r"[^\w\s&]", " ", name.lower())
    text = re.sub(r"\b(private|pvt|limited|ltd|llp|llc|inc|plc|corporation|corp|company|co|gmbh|sa|ag|bv|the)\b", " ", text)
    return " ".join(text.split())


def _search(conn, name: str) -> list[dict]:
    q, nq = name.lower().strip(), _norm(name)
    if len(nq) < 2:
        return []
    hits: list[dict] = []
    for r in conn.execute(
        """SELECT client_id, name, status,
                  greatest(similarity(lower(name), %(q)s), similarity(lower(name), %(nq)s),
                           coalesce((SELECT max(greatest(similarity(lower(a), %(q)s), similarity(lower(a), %(nq)s)))
                                     FROM unnest(aliases || subsidiaries) a), 0)) AS score
           FROM clients
           WHERE lower(name) %% %(nq)s OR lower(name) LIKE '%%' || %(nq)s || '%%'
              OR EXISTS (SELECT 1 FROM unnest(aliases || subsidiaries) a
                         WHERE lower(a) %% %(nq)s OR lower(a) LIKE '%%' || %(nq)s || '%%')
           ORDER BY score DESC LIMIT 10""", {"q": q, "nq": nq}):
        if r["score"] >= SIMILARITY or nq in _norm(r["name"]):
            hits.append({"kind": "existing_client", "query": name, "client_id": r["client_id"], "name": r["name"],
                         "status": r["status"], "score": round(float(r["score"]), 2)})
    for r in conn.execute(
        """SELECT m.matter_id, m.matter_code, m.title, m.opposing_party, m.client_name, m.status,
                  similarity(lower(m.opposing_party), %(nq)s) AS score
           FROM matters m
           WHERE m.opposing_party IS NOT NULL
             AND (lower(m.opposing_party) %% %(nq)s OR lower(m.opposing_party) LIKE '%%' || %(nq)s || '%%')
           ORDER BY score DESC LIMIT 20""", {"nq": nq}):
        if r["score"] >= SIMILARITY or nq in _norm(r["opposing_party"]):
            hits.append({"kind": "adverse_party", "query": name, "matter_id": r["matter_id"], "matter_code": r["matter_code"],
                         "title": r["title"], "opposing_party": r["opposing_party"], "client_name": r["client_name"],
                         "status": r["status"], "score": round(float(r["score"]), 2)})
    return hits


def _view(conn, member_id: str | None, check: dict) -> dict:
    """The check as this member may see it: hits on matters they cannot see are redacted."""
    full = member_id is None or access.has_permission(conn, member_id, "conflicts.decide")
    results = []
    for h in check["results"] or []:
        if h["kind"] == "adverse_party" and not full and not access.can_see_matter(conn, member_id, h["matter_id"]):
            results.append({"kind": "adverse_party", "query": h["query"], "redacted": True,
                            "note": "A matter you cannot see involves this name as the other side — ask Risk."})
        else:
            results.append(h)
    out = {k: check[k] for k in ("check_id", "names", "purpose", "requested_by", "requested_at", "decision",
                                 "decided_by", "decided_at", "notes")}
    out["results"] = results
    out["status"] = check["decision"] or "awaiting_risk"
    return out


def _may_request(conn, member_id: str | None) -> None:
    if member_id is None:
        return
    if not (access.has_permission(conn, member_id, "clients.create") or access.has_permission(conn, member_id, "conflicts.decide")):
        raise FirmError(403, "Only people who take on clients (or Risk) can run conflict checks")


@guard
def run_check(conn, actor: str | None, names: list[str], purpose: str = "") -> dict:
    _may_request(conn, actor)
    clean = [n.strip() for n in names if isinstance(n, str) and n.strip()]
    if not clean or len(clean) > MAX_NAMES:
        raise FirmError(422, f"Give between 1 and {MAX_NAMES} names")
    results = [h for n in clean for h in _search(conn, n)]
    check_id = new_id("CHK")
    decision = None if results else "clear"
    conn.execute(
        """INSERT INTO conflict_checks (check_id, names, purpose, requested_by, results, decision, decided_at, notes)
           VALUES (%s, %s, %s, %s, %s::jsonb, %s, CASE WHEN %s::text IS NULL THEN NULL ELSE now() END, %s)""",
        (check_id, clean, (purpose or "")[:500], actor, json.dumps(results, default=str), decision, decision,
         "No matches in clients or opposing parties" if decision else ""),
    )
    emit(conn, "conflict.checked", "conflict_check", check_id, actor=actor, payload={"hits": len(results), "decision": decision})
    conn.commit()
    audit.record("conflict.check", member_id=actor, object_type="conflict_check", object_id=check_id,
                 detail={"names": clean, "hits": len(results), "decision": decision})
    return _view(conn, actor, one(conn, "SELECT * FROM conflict_checks WHERE check_id = %s", (check_id,)))


@guard
def get_check(conn, actor: str | None, check_id: str) -> dict:
    row = one(conn, "SELECT * FROM conflict_checks WHERE check_id = %s", (check_id,))
    if row is None or (actor is not None and row["requested_by"] != actor
                       and not access.has_permission(conn, actor, "conflicts.decide")):
        raise FirmError(404, "Conflict check not found")
    return _view(conn, actor, row)


@guard
def list_checks(conn, actor: str | None, scope: str = "mine") -> list[dict]:
    if scope == "to_decide":
        access.require_permission(conn, actor, "conflicts.decide")
        rows = conn.execute("SELECT * FROM conflict_checks WHERE decision IS NULL ORDER BY requested_at").fetchall()
    else:
        rows = conn.execute("SELECT * FROM conflict_checks WHERE requested_by IS NOT DISTINCT FROM %s "
                            "ORDER BY requested_at DESC LIMIT 50", (actor,)).fetchall()
    return [_view(conn, actor, r) for r in rows]


@guard
def decide(conn, actor: str | None, check_id: str, decision: str, notes: str = "") -> dict:
    access.require_permission(conn, actor, "conflicts.decide")
    if decision not in DECISIONS:
        raise FirmError(422, f"decision must be one of {', '.join(DECISIONS)}")
    if decision in ("conflict", "waived") and not (notes or "").strip():
        raise FirmError(422, "Record why (notes) when declaring or waiving a conflict")
    row = one(conn, "SELECT * FROM conflict_checks WHERE check_id = %s FOR UPDATE", (check_id,))
    if row is None:
        raise FirmError(404, "Conflict check not found")
    conn.execute("UPDATE conflict_checks SET decision = %s, decided_by = %s, decided_at = now(), notes = %s WHERE check_id = %s",
                 (decision, actor, (notes or "")[:2000], check_id))
    status = "declined" if decision == "conflict" else "active"
    for c in conn.execute("UPDATE clients SET status = %s WHERE intake_check_id = %s RETURNING client_id", (status, check_id)).fetchall():
        emit(conn, "client.updated", "client", c["client_id"], actor=actor, payload={"status": status})
    emit(conn, "conflict.decided", "conflict_check", check_id, actor=actor, payload={"decision": decision})
    conn.commit()
    audit.record("conflict.decide", member_id=actor, object_type="conflict_check", object_id=check_id,
                 detail={"decision": decision, "from": row["decision"], "notes": notes})
    return _view(conn, actor, one(conn, "SELECT * FROM conflict_checks WHERE check_id = %s", (check_id,)))


@guard
def create_client(conn, actor: str | None, data: dict) -> dict:
    """A new client, opened against a conflict check that covered its name."""
    access.require_permission(conn, actor, "clients.create")
    name = (data.get("name") or "").strip()
    if not name or len(name) > 300:
        raise FirmError(422, "name is required (at most 300 characters)")
    check = one(conn, "SELECT * FROM conflict_checks WHERE check_id = %s", (data.get("check_id"),))
    if check is None:
        raise FirmError(422, "Run a conflict check on the client's name first")
    if _norm(name) not in {_norm(n) for n in check["names"]}:
        raise FirmError(422, "The conflict check does not cover this name; run a check that includes it")
    if check["decision"] == "conflict":
        raise FirmError(409, "The conflict check found a conflict; the client cannot be taken on")
    if one(conn, "SELECT 1 AS ok FROM clients WHERE lower(name) = lower(%s)", (name,)):
        raise FirmError(409, f"{name} is already a client")
    n = one(conn, "SELECT count(*) AS n FROM clients")["n"]
    client_id = f"CLI-{n + 20001:05d}"
    while one(conn, "SELECT 1 AS ok FROM clients WHERE client_id = %s", (client_id,)):
        n += 1
        client_id = f"CLI-{n + 20001:05d}"
    status = "active" if check["decision"] in ("clear", "waived") else "prospective"

    def lst(key: str) -> list[str]:
        return [str(x).strip() for x in (data.get(key) or []) if str(x).strip()][:30]

    conn.execute(
        """INSERT INTO clients (client_id, name, industry, size, headquarters, locations, subsidiaries, preferred_lawyer_ids,
                                aliases, status, intake_check_id, created_by_member_id, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, '{}', %s, %s, %s, %s, now())""",
        (client_id, name, (data.get("industry") or "")[:100] or None, (data.get("size") or "")[:50] or None,
         (data.get("headquarters") or "")[:100] or None, lst("locations"), lst("subsidiaries"), lst("aliases"),
         status, check["check_id"], actor),
    )
    emit(conn, "client.created", "client", client_id, actor=actor, payload={"name": name, "status": status})
    conn.commit()
    audit.record("client.create", member_id=actor, object_type="client", object_id=client_id,
                 detail={"name": name, "status": status, "check_id": check["check_id"]})
    return one(conn, "SELECT client_id, name, industry, headquarters, status, intake_check_id FROM clients WHERE client_id = %s",
               (client_id,))
