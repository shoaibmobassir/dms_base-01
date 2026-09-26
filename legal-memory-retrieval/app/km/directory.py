"""Structured firm records: matter cards, matter teams, people, parties.

These are the KM facts a retrieval-only pipeline cannot see in chunk text:
who is staffed on a matter, who the lead is, what a person specialises in,
which matters a client or counterparty appears on. All reads honour the
ethical-wall ACL (a restricted matter is invisible, including its team).
"""
from __future__ import annotations

import re
from typing import Any

from app.km.scope import ACL_SQL, _fetch

_STOP = frozenset(
    """a an and are as at be by did do does for from had has have in is it its of on or our
    the their them they this that to was we were what when where which who whom whose why
    with work worked working works firm firms team teams expert experts expertise specialist
    specialise specialised specialises specialize specialized specializes specialist
    handle handled handles lead leads led leading person people lawyer lawyers member members
    anyone someone somebody office offices sits sit based any all us me tell know about""".split()
)
_ROLE_WORDS = {
    "partner": "Partner",
    "partners": "Partner",
    "counsel": "Counsel",
    "senior associate": "Senior Associate",
    "associate": "Associate",
    "associates": "Associate",
    "junior": "Junior",
    "juniors": "Junior",
    "paralegal": "Paralegal",
    "paralegals": "Paralegal",
    "knowledge manager": "Knowledge Manager",
}


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) >= 3 and t not in _STOP]


def _stem(tok: str) -> str:
    return tok[:6] if len(tok) > 6 else tok


def matter_cards(conn, matter_ids: list[str], member_id: str | None, *, max_docs: int = 25) -> list[dict]:
    """Full matter records (facts, issues, team, documents, open deadlines)."""
    if not matter_ids:
        return []
    params = {"member_id": member_id, "ids": list(matter_ids)}
    matters = _fetch(
        conn,
        f"""
        SELECT m.matter_id, m.matter_code, m.title, cl.name AS client_name, m.opposing_party,
               m.practice_area, m.matter_type, m.jurisdiction, m.court, m.status, m.office,
               m.opened_date, m.closed_date, m.claim_amount, m.outcome, m.facts, m.legal_issues
        FROM matters m
        JOIN clients cl ON cl.client_id = m.client_id
        JOIN permissions p ON p.matter_id = m.matter_id
        WHERE {ACL_SQL} AND m.matter_id = ANY(%(ids)s)
        """,
        params,
    )
    if not matters:
        return []
    allowed = [m["matter_id"] for m in matters]
    params = {"ids": allowed, "max_docs": max_docs}
    team = _fetch(
        conn,
        """
        SELECT mm.matter_id, mb.member_id, mb.name, mb.role, mb.office, mm.role_on_matter
        FROM matter_members mm JOIN members mb USING (member_id)
        WHERE mm.matter_id = ANY(%(ids)s)
        ORDER BY mm.matter_id,
                 CASE lower(coalesce(mm.role_on_matter, '')) WHEN 'lead' THEN 0 ELSE 1 END,
                 mb.member_id
        """,
        params,
    )
    docs = _fetch(
        conn,
        """
        SELECT matter_id, document_id, title, document_type, doc_date, author_name, status
        FROM (
          SELECT d.*, row_number() OVER (PARTITION BY d.matter_id ORDER BY d.doc_date NULLS LAST, d.document_id) rn
          FROM documents d WHERE d.matter_id = ANY(%(ids)s)
        ) x WHERE rn <= %(max_docs)s
        ORDER BY matter_id, rn
        """,
        params,
    )
    counts = {
        r["matter_id"]: int(r["n"])
        for r in _fetch(conn, "SELECT matter_id, count(*) n FROM documents WHERE matter_id = ANY(%(ids)s) GROUP BY 1", params)
    }
    deadlines = _fetch(
        conn,
        """
        SELECT matter_id, title, kind, due_date, court, status FROM court_deadlines
        WHERE matter_id = ANY(%(ids)s) AND status = 'open' ORDER BY due_date
        """,
        params,
    )
    by_id = {m["matter_id"]: {**m, "team": [], "documents": [], "document_count": counts.get(m["matter_id"], 0), "deadlines": []} for m in matters}
    for t in team:
        by_id[t["matter_id"]]["team"].append({k: t[k] for k in ("member_id", "name", "role", "office", "role_on_matter")})
    for d in docs:
        by_id[d["matter_id"]]["documents"].append({k: d[k] for k in ("document_id", "title", "document_type", "doc_date", "author_name", "status")})
    for dl in deadlines:
        by_id[dl["matter_id"]]["deadlines"].append({k: dl[k] for k in ("title", "kind", "due_date", "court", "status")})
    return [by_id[mid] for mid in matter_ids if mid in by_id]


def _member_rows(conn, member_id: str | None) -> tuple[list[dict], dict[str, list[dict]]]:
    members = _fetch(
        conn,
        """
        SELECT member_id, name, role, office, practice_areas, specializations, joined_year, is_lawyer
        FROM members ORDER BY member_id
        """,
        {},
    )
    history = _fetch(
        conn,
        f"""
        SELECT mm.member_id, mm.role_on_matter, m.matter_id, m.matter_code, m.title,
               m.practice_area, m.legal_issues, cl.name AS client_name, m.status
        FROM matter_members mm
        JOIN matters m ON m.matter_id = mm.matter_id
        JOIN clients cl ON cl.client_id = m.client_id
        JOIN permissions p ON p.matter_id = m.matter_id
        WHERE {ACL_SQL}
        ORDER BY m.opened_date DESC NULLS LAST, m.matter_id
        """,
        {"member_id": member_id},
    )
    by_member: dict[str, list[dict]] = {}
    for h in history:
        by_member.setdefault(h["member_id"], []).append(h)
    return members, by_member


def people_search(conn, question: str, member_id: str | None, *, limit: int = 6) -> list[dict]:
    """Rank firm members for an expertise / role / office question.

    Signals: stated specialisations (strongest), practice areas, and the
    member's own staffing history on matters the asker may see. Role and
    office words in the question act as filters.
    """
    q = (question or "").lower()
    members, history = _member_rows(conn, member_id)
    offices = {str(m["office"]).lower(): m["office"] for m in members if m.get("office")}
    office_filter = {v for k, v in offices.items() if re.search(rf"\b{re.escape(k)}\b", q)}
    role_filter = set()
    for word, role in sorted(_ROLE_WORDS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(word)}\b", q):
            role_filter.add(role)
            if word in {"senior associate", "knowledge manager"}:
                break
    topic = [t for t in _tokens(q) if t not in {w for k in offices for w in k.split()} and t not in _ROLE_WORDS]
    stems = {_stem(t) for t in topic}

    def hits(text: str) -> int:
        toks = {_stem(t) for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) >= 3}
        return len(stems & toks)

    scored = []
    for m in members:
        if office_filter and m.get("office") not in office_filter:
            continue
        if role_filter and m.get("role") not in role_filter:
            continue
        score = 0.0
        spec_hits = hits(" ".join(m.get("specializations") or []))
        prac_hits = hits(" ".join(m.get("practice_areas") or []))
        mine = history.get(m["member_id"], [])
        matter_hits = [
            h for h in mine
            if stems and hits(" ".join([h["title"] or "", h["practice_area"] or "", " ".join(h["legal_issues"] or [])])) >= max(1, (len(stems) + 1) // 2)
        ]
        if stems:
            score += 4.0 * spec_hits / len(stems) + 1.0 * min(1, prac_hits) + min(2.0, 0.5 * len(matter_hits))
            if score <= 0:
                continue
        else:
            score = 1.0  # pure role/office filter
        if role_filter or office_filter:
            score += 0.5
        scored.append((score, m, matter_hits or mine))
    scored.sort(key=lambda x: (-x[0], x[1]["member_id"]))
    out = []
    for score, m, relevant in scored[:limit]:
        out.append({
            "member_id": m["member_id"],
            "name": m["name"],
            "role": m["role"],
            "office": m.get("office"),
            "practice_areas": list(m.get("practice_areas") or []),
            "specializations": list(m.get("specializations") or []),
            "score": round(score, 3),
            "matters": [
                {k: h[k] for k in ("matter_id", "matter_code", "title", "role_on_matter")}
                for h in relevant[:5]
            ],
            "matter_count": len(history.get(m["member_id"], [])),
        })
    return out


def matters_for_party(conn, text: str, member_id: str | None, *, limit: int = 20) -> list[dict[str, Any]]:
    """Accessible matters where ``text`` is the client, counterparty, or in the facts."""
    needle = (text or "").strip()
    if len(needle) < 3:
        return []
    return _fetch(
        conn,
        f"""
        SELECT m.matter_id, m.matter_code, m.title, cl.name AS client_name, m.opposing_party,
               m.practice_area, m.status,
               GREATEST(similarity(lower(cl.name), lower(%(n)s)),
                        similarity(lower(coalesce(m.opposing_party, '')), lower(%(n)s)),
                        CASE WHEN cl.name ILIKE '%%' || %(n)s || '%%'
                               OR coalesce(m.opposing_party, '') ILIKE '%%' || %(n)s || '%%' THEN 0.9
                             WHEN array_to_string(m.facts, ' ') ILIKE '%%' || %(n)s || '%%' THEN 0.7
                             ELSE 0 END) AS score
        FROM matters m
        JOIN clients cl ON cl.client_id = m.client_id
        JOIN permissions p ON p.matter_id = m.matter_id
        WHERE {ACL_SQL}
          AND (cl.name ILIKE '%%' || %(n)s || '%%'
               OR coalesce(m.opposing_party, '') ILIKE '%%' || %(n)s || '%%'
               OR array_to_string(m.facts, ' ') ILIKE '%%' || %(n)s || '%%'
               OR lower(%(n)s) = ANY(SELECT lower(a) FROM unnest(cl.aliases) a)
               OR similarity(lower(cl.name), lower(%(n)s)) >= 0.5)
        ORDER BY score DESC, m.matter_id
        LIMIT %(limit)s
        """,
        {"member_id": member_id, "n": needle, "limit": limit},
    )
