"""Live updates (the domain-event outbox, filtered per member) and Home "my work"."""
from __future__ import annotations

from typing import Any

from app import access
from app.api.acl import ACL_CLAUSE, doc_acl, doc_read
from app.firm import one


def latest_seq(conn) -> int:
    return int(one(conn, "SELECT coalesce(max(seq), 0) AS n FROM domain_events")["n"])


def _visible_matters(conn, member_id: str | None) -> set[str] | None:
    if member_id is None:
        return None
    return {r["matter_id"] for r in conn.execute(
        f"SELECT p.matter_id FROM permissions p WHERE {ACL_CLAUSE}", {"member_id": member_id})}


def events_since(conn, member_id: str | None, since: int, limit: int = 200) -> list[dict]:
    """New events the member may know about (a restricted matter's events never reach outsiders)."""
    rows = conn.execute(
        "SELECT seq, topic, entity_type, entity_id, matter_id, document_id, actor, payload, occurred_at "
        "FROM domain_events WHERE seq > %s ORDER BY seq LIMIT %s", (since, limit)).fetchall()
    if not rows or member_id is None:
        return rows
    matters = _visible_matters(conn, member_id)
    docs = [r["document_id"] for r in rows if r["document_id"]]
    readable_docs = {r["document_id"] for r in conn.execute(
        f"""SELECT d.document_id FROM documents d LEFT JOIN permissions p ON p.matter_id = d.matter_id
            WHERE d.document_id = ANY(%(ids)s) AND {doc_read('d')}""",
        {"ids": docs, "member_id": member_id})} if docs else set()
    risk = access.has_permission(conn, member_id, "conflicts.decide")
    projects: set[str] = set()
    if any(r["entity_type"] == "project" for r in rows):
        from app.workspaces.projects import visible_project_ids

        projects = visible_project_ids(conn, member_id) or set()
    out = []
    for r in rows:
        if r["matter_id"] and r["matter_id"] not in matters:
            continue
        if r["document_id"] and r["document_id"] not in readable_docs:
            continue
        if r["entity_type"] == "project" and r["entity_id"] not in projects:
            continue
        if r["entity_type"] == "conflict_check" and not risk and r["actor"] != member_id:
            continue
        out.append(r)
    return out


def my_work(conn, member_id: str | None) -> dict[str, Any]:
    """What needs me: my matters, what is due, what I am editing, comments for me, decisions waiting."""
    if member_id is None:
        return {"matters": [], "due": [], "editing": [], "comments": [], "decisions": {"access_requests": [], "conflict_checks": []}}
    params = {"me": member_id, "member_id": member_id}
    matters = conn.execute(
        f"""SELECT m.matter_id, m.matter_code, m.title, m.client_name, m.status, mm.role_on_matter,
                   (SELECT min(cd.due_date) FROM court_deadlines cd WHERE cd.matter_id = m.matter_id AND cd.status = 'open'
                      AND cd.due_date >= current_date) AS next_due
            FROM matter_members mm JOIN matters m USING (matter_id)
            LEFT JOIN permissions p ON p.matter_id = m.matter_id
            WHERE mm.member_id = %(me)s AND (mm.ended_at IS NULL OR mm.ended_at >= current_date)
              AND m.status IS DISTINCT FROM 'Closed' AND {ACL_CLAUSE}
            ORDER BY next_due NULLS LAST, m.title LIMIT 50""", params).fetchall()
    mine = [m["matter_id"] for m in matters]
    due = conn.execute(
        f"""SELECT cd.deadline_id, cd.matter_id, m.matter_code, cd.title, cd.kind, cd.due_date, cd.owner_member_id,
                   cd.due_date < current_date AS overdue
            FROM court_deadlines cd JOIN matters m USING (matter_id) LEFT JOIN permissions p ON p.matter_id = m.matter_id
            WHERE cd.status = 'open' AND cd.due_date <= current_date + 14
              AND (cd.owner_member_id = %(me)s OR cd.matter_id = ANY(%(mine)s)) AND {ACL_CLAUSE}
            ORDER BY cd.due_date LIMIT 50""", {**params, "mine": mine}).fetchall()
    editing = conn.execute(
        f"""SELECT d.document_id, d.title, 'editing' AS state, l.expires_at AS at
            FROM document_locks l JOIN documents d USING (document_id)
            WHERE l.member_id = %(me)s AND l.expires_at > now()
            UNION ALL
            SELECT d.document_id, d.title, 'draft' AS state, dr.updated_at AS at
            FROM document_drafts dr JOIN documents d USING (document_id)
            LEFT JOIN permissions p ON p.matter_id = d.matter_id
            WHERE dr.member_id = %(me)s AND jsonb_array_length(dr.ops) > 0 AND {ACL_CLAUSE} AND {doc_acl('d')}
            ORDER BY at DESC LIMIT 20""", params).fetchall()
    comments = conn.execute(
        f"""SELECT a.annotation_id AS comment_id, a.document_id, d.title, a.content AS body, a.author_name,
                   a.created_at, CASE WHEN root.author_id = %(me)s THEN 'reply' ELSE 'on_your_document' END AS why
            FROM annotations a
            JOIN annotations root ON root.annotation_id = coalesce(a.parent_id, a.annotation_id)
            JOIN documents d ON d.document_id = a.document_id
            LEFT JOIN permissions p ON p.matter_id = d.matter_id
            WHERE a.annotation_type = 'comment' AND root.status = 'active'
              AND a.author_id IS DISTINCT FROM %(me)s AND a.created_at > now() - interval '30 days'
              AND (root.author_id = %(me)s OR d.author_id = %(me)s)
              AND {ACL_CLAUSE} AND {doc_acl('d')}
            ORDER BY a.created_at DESC LIMIT 20""", params).fetchall()
    decisions = {
        "access_requests": access.list_requests(conn, member_id, "to_decide"),
        "conflict_checks": conn.execute(
            "SELECT check_id, names, requested_by, requested_at FROM conflict_checks WHERE decision IS NULL "
            "ORDER BY requested_at").fetchall() if access.has_permission(conn, member_id, "conflicts.decide") else [],
    }
    return {"matters": matters, "due": due, "editing": editing, "comments": comments, "decisions": decisions}
