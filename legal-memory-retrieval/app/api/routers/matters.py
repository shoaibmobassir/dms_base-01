from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row

from app.api.acl import ACL_CLAUSE, doc_acl
from app.api.sorting import order_by
from app.auth.deps import resolve_member
from app.db.connection import connect

router = APIRouter(tags=["matters"])

# What the matters list can be sorted by.
MATTER_SORT = {
    "opened": "m.opened_date",
    "title": "lower(m.title)",
    "client": "lower(m.client_name)",
    "deadline": "nd.due_date",
    "status": "lower(m.status)",
    "documents": "document_count",
}

SERVICE = "matters"


@router.get("/health")
def matters_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


@router.get("")
def matters_list(
    q: str | None = Query(default=None),
    practice: str | None = Query(default=None),
    status: str | None = Query(default=None),
    mine: bool = Query(default=False, description="Only matters the caller is staffed on"),
    sort: str | None = Query(default=None, description="opened, title, client, deadline, status or documents"),
    dir: str | None = Query(default=None, pattern="^(asc|desc)$"),
    member_id: str | None = Depends(resolve_member),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    params: dict = {"member_id": member_id, "limit": limit, "offset": offset}
    wheres = [ACL_CLAUSE]
    if mine:
        wheres.append(
            "EXISTS (SELECT 1 FROM matter_members mx WHERE mx.matter_id = m.matter_id AND mx.member_id = %(member_id)s)"
        )
    if q:
        wheres.append(
            "(m.title ILIKE %(q_like)s"
            " OR m.matter_code ILIKE %(q_like)s"
            " OR m.client_name ILIKE %(q_like)s)"
        )
        params["q_like"] = f"%{q}%"
    if practice:
        wheres.append("m.practice_area ILIKE %(practice_like)s")
        params["practice_like"] = f"%{practice}%"
    if status and status.lower() != "all":
        wheres.append("m.status ILIKE %(status_like)s")
        params["status_like"] = f"%{status}%"
    where = " AND ".join(wheres)
    sql = f"""
        SELECT m.matter_id, m.matter_code, m.title, m.client_id, m.client_name,
               m.practice_area, m.matter_type, m.status, m.jurisdiction,
               m.opened_date, m.closed_date, m.claim_amount, m.outcome,
               COALESCE(p.restricted, FALSE) AS restricted,
               lead.name AS lead_name, lead.member_id AS lead_member_id,
               nd.due_date AS next_deadline_date, nd.title AS next_deadline_title,
               (SELECT count(*) FROM documents d WHERE d.matter_id = m.matter_id
                  AND d.status IS DISTINCT FROM 'Deleted' AND {doc_acl('d')}) AS document_count
        FROM matters m
        LEFT JOIN permissions p ON p.matter_id = m.matter_id
        LEFT JOIN LATERAL (
            SELECT mb.member_id, mb.name FROM matter_members mm JOIN members mb USING (member_id)
            WHERE mm.matter_id = m.matter_id AND lower(coalesce(mm.role_on_matter, '')) = 'lead'
            ORDER BY mb.member_id LIMIT 1
        ) lead ON TRUE
        LEFT JOIN LATERAL (
            SELECT cd.due_date, cd.title FROM court_deadlines cd
            WHERE cd.matter_id = m.matter_id AND cd.status = 'open'
            ORDER BY cd.due_date LIMIT 1
        ) nd ON TRUE
        WHERE {where}
        {order_by(sort, dir, MATTER_SORT, 'opened', 'm.matter_id')}
        LIMIT %(limit)s OFFSET %(offset)s
    """
    count_sql = f"""
        SELECT COUNT(*) AS n FROM matters m
        LEFT JOIN permissions p ON p.matter_id = m.matter_id
        WHERE {where}
    """
    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            items = list(cur.fetchall())
            cur.execute(count_sql, count_params)
            total = cur.fetchone()["n"]
    return {"service": SERVICE, "total": total, "items": items}


def _require_member(member_id: str | None) -> str:
    if member_id is None:
        raise HTTPException(status_code=401, detail="Pins need a member identity")
    return member_id


def _can_access(cur, matter_id: str, member_id: str | None) -> bool:
    cur.execute(
        f"""
        SELECT 1 FROM matters m LEFT JOIN permissions p ON p.matter_id = m.matter_id
        WHERE m.matter_id = %(matter_id)s AND {ACL_CLAUSE}
        """,
        {"matter_id": matter_id, "member_id": member_id},
    )
    return cur.fetchone() is not None


@router.get("/pinned")
def pinned_matters(member_id: str | None = Depends(resolve_member)) -> dict:
    """The caller's pinned matters, newest pin first. Pins on matters the caller can no
    longer access are omitted (a pin never grants access)."""
    me = _require_member(member_id)
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT m.matter_id, m.matter_code, m.title, m.client_name, m.status,
                       COALESCE(p.restricted, FALSE) AS restricted, mp.pinned_at
                FROM member_pins mp
                JOIN matters m ON m.matter_id = mp.matter_id
                LEFT JOIN permissions p ON p.matter_id = m.matter_id
                WHERE mp.member_id = %(member_id)s AND {ACL_CLAUSE}
                ORDER BY mp.pinned_at DESC
                """,
                {"member_id": me},
            )
            return {"service": SERVICE, "items": list(cur.fetchall())}


@router.put("/{matter_id}/pin", status_code=204)
def pin_matter(matter_id: str, member_id: str | None = Depends(resolve_member)) -> None:
    me = _require_member(member_id)
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if not _can_access(cur, matter_id, me):
                raise HTTPException(status_code=404, detail="Matter not found or access denied")
            cur.execute(
                "INSERT INTO member_pins (member_id, matter_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (me, matter_id),
            )
        conn.commit()


@router.delete("/{matter_id}/pin", status_code=204)
def unpin_matter(matter_id: str, member_id: str | None = Depends(resolve_member)) -> None:
    me = _require_member(member_id)
    with connect() as conn:
        conn.execute("DELETE FROM member_pins WHERE member_id = %s AND matter_id = %s", (me, matter_id))
        conn.commit()


@router.get("/{matter_id}")
def matter_detail(
    matter_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    params = {"matter_id": matter_id, "member_id": member_id}
    sql = f"""
        SELECT m.*, COALESCE(p.restricted, FALSE) AS restricted,
               p.classification, p.allowed_members AS acl_members
        FROM matters m
        LEFT JOIN permissions p ON p.matter_id = m.matter_id
        WHERE m.matter_id = %(matter_id)s AND {ACL_CLAUSE}
    """
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            matter = cur.fetchone()
            if not matter:
                raise HTTPException(status_code=404, detail="Matter not found or access denied")
            cur.execute(
                """
                SELECT mm.member_id, mm.role_on_matter, mem.name, mem.role, mem.office,
                       mm.started_at, mm.ended_at, (mm.ended_at IS NULL OR mm.ended_at >= current_date) AS active
                FROM matter_members mm
                JOIN members mem ON mem.member_id = mm.member_id
                WHERE mm.matter_id = %(matter_id)s
                ORDER BY (lower(mm.role_on_matter) = 'lead') DESC, active DESC, mm.role_on_matter
                """,
                {"matter_id": matter_id},
            )
            team = list(cur.fetchall())
            cur.execute(
                f"""
                SELECT d.document_id, d.title, d.document_type, d.author_name,
                       d.doc_date, d.status, d.version, da.visibility AS privacy
                FROM documents d LEFT JOIN document_access da USING (document_id)
                WHERE d.matter_id = %(matter_id)s AND {doc_acl('d')}
                ORDER BY d.doc_date DESC NULLS LAST
                LIMIT 20
                """,
                {"matter_id": matter_id, "member_id": member_id},
            )
            docs = list(cur.fetchall())
            from app import access

            # What the viewer may do here (the page shows edit controls accordingly).
            my_level = access.matter_level(conn, member_id, matter_id)
    return {"service": SERVICE, "matter": matter, "team": team, "documents": docs, "my_level": my_level}


@router.get("/{matter_id}/arguments")
def matter_arguments(
    matter_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    params = {"matter_id": matter_id, "member_id": member_id}
    access_sql = f"""
        SELECT 1 FROM matters m
        LEFT JOIN permissions p ON p.matter_id = m.matter_id
        WHERE m.matter_id = %(matter_id)s AND {ACL_CLAUSE}
    """
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(access_sql, params)
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Matter not found or access denied")
            cur.execute(
                """
                SELECT argument_id, issue, position, argument, outcome,
                       supporting_documents
                FROM arguments WHERE matter_id = %(matter_id)s
                ORDER BY issue
                """,
                {"matter_id": matter_id},
            )
            return {"service": SERVICE, "matter_id": matter_id, "arguments": list(cur.fetchall())}


@router.get("/{matter_id}/related")
def matter_related(
    matter_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    params = {"matter_id": matter_id, "member_id": member_id}
    access_sql = f"""
        SELECT 1 FROM matters m
        LEFT JOIN permissions p ON p.matter_id = m.matter_id
        WHERE m.matter_id = %(matter_id)s AND {ACL_CLAUSE}
    """
    # Links people made (matter_links) come first, then generated relationships.
    sql = f"""
        SELECT DISTINCT ON (m.matter_id) m.matter_id, m.matter_code, m.title, m.client_name,
               m.practice_area, m.status, m.outcome,
               COALESCE(p2.restricted, FALSE) AS restricted, x.relation, x.note, x.manual
        FROM (
            SELECT CASE WHEN l.matter_id = %(matter_id)s THEN l.related_matter_id ELSE l.matter_id END AS other,
                   l.relation, l.note, TRUE AS manual
            FROM matter_links l WHERE l.matter_id = %(matter_id)s OR l.related_matter_id = %(matter_id)s
            UNION ALL
            SELECT CASE WHEN r.source_id = %(matter_id)s THEN r.target_id ELSE r.source_id END,
                   r.rel_type, '', FALSE
            FROM relationships r WHERE r.source_id = %(matter_id)s OR r.target_id = %(matter_id)s
        ) x
        JOIN matters m ON m.matter_id = x.other
        LEFT JOIN permissions p2 ON p2.matter_id = m.matter_id
        WHERE m.matter_id != %(matter_id)s
          AND {ACL_CLAUSE.replace('p.', 'p2.')}
        ORDER BY m.matter_id, x.manual DESC
    """
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # The relationship graph of a restricted matter is itself restricted.
            cur.execute(access_sql, params)
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Matter not found or access denied")
            cur.execute(sql, params)
            related = sorted(cur.fetchall(), key=lambda r: (not r["manual"], r["title"] or ""))[:20]
            return {"service": SERVICE, "matter_id": matter_id, "related": related}


# What people did on this matter (UI roadmap Q2). Only actions worth showing a
# colleague; reads/views are in the audit export, not the activity feed.
ACTIVITY_ACTIONS = ("upload.create", "upload.process", "chat.prompt", "document.download", "export.bundle", "document.version",
                    "document.edit", "matter.create", "matter.update", "matter.team.set", "matter.team.remove",
                    "matter.event.add", "matter.event.update", "matter.event.delete", "matter.argument.add",
                    "matter.argument.update", "matter.argument.delete", "matter.link", "matter.unlink")


@router.get("/{matter_id}/activity")
def matter_activity(
    matter_id: str,
    limit: int = Query(default=30, le=100),
    member_id: str | None = Depends(resolve_member),
) -> dict:
    params = {"matter_id": matter_id, "member_id": member_id, "limit": limit, "actions": list(ACTIVITY_ACTIONS)}
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if not _can_access(cur, matter_id, member_id):
                raise HTTPException(status_code=404, detail="Matter not found or access denied")
            cur.execute(
                """
                SELECT a.seq, a.occurred_at, a.action, a.object_type, a.object_id,
                       a.member_id, m.name AS member_name
                FROM audit_events a LEFT JOIN members m ON m.member_id = a.member_id
                WHERE a.matter_id = %(matter_id)s AND a.outcome = 'success' AND a.action = ANY(%(actions)s)
                ORDER BY a.seq DESC
                LIMIT %(limit)s
                """,
                params,
            )
            items = list(cur.fetchall())
    return {"service": SERVICE, "matter_id": matter_id, "items": items}


@router.get("/{matter_id}/timeline")
def matter_timeline(
    matter_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    params = {"matter_id": matter_id, "member_id": member_id}
    access_sql = f"""
        SELECT 1 FROM matters m
        LEFT JOIN permissions p ON p.matter_id = m.matter_id
        WHERE m.matter_id = %(matter_id)s AND {ACL_CLAUSE}
    """
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(access_sql, params)
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Matter not found or access denied")
            cur.execute(
                f"""
                SELECT d.document_id, d.title, d.document_type, d.author_name, d.doc_date
                FROM documents d
                WHERE d.matter_id = %(mid)s AND {doc_acl('d')}
                ORDER BY d.doc_date ASC NULLS LAST
                """,
                {"mid": matter_id, "member_id": member_id},
            )
            docs = cur.fetchall()
            cur.execute(
                """
                SELECT e.event_id, e.occurred_on, e.title, e.detail, e.kind, e.source_document_id,
                       e.row_version, mb.name AS author
                FROM matter_events e LEFT JOIN members mb ON mb.member_id = e.created_by
                WHERE e.matter_id = %(mid)s
                """,
                {"mid": matter_id},
            )
            entries = cur.fetchall()

    # Document dates, plus the events people entered (hearings, orders, correspondence...).
    timeline = [
        {
            "date": str(d.get("doc_date") or ""),
            "author": d.get("author_name"),
            "event": d.get("title", "Matter milestone"),
            "doc_id": d["document_id"],
            "doc_type": d.get("document_type", "Document"),
            "source": "document",
        }
        for d in docs
    ] + [
        {
            "date": str(e["occurred_on"]),
            "author": e["author"],
            "event": e["title"],
            "detail": e["detail"],
            "doc_id": e["source_document_id"],
            "doc_type": e["kind"].capitalize(),
            "source": "entry",
            "event_id": e["event_id"],
            "row_version": e["row_version"],
        }
        for e in entries
    ]
    timeline.sort(key=lambda t: (t["date"] or "9999", t["event"] or ""))
    return {"service": SERVICE, "matter_id": matter_id, "timeline": timeline}


@router.get("/{matter_id}/graph")
def matter_graph(
    matter_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    params = {"matter_id": matter_id, "member_id": member_id}
    access_sql = f"""
        SELECT m.matter_id, m.matter_code, m.title, m.client_name
        FROM matters m
        LEFT JOIN permissions p ON p.matter_id = m.matter_id
        WHERE m.matter_id = %(matter_id)s AND {ACL_CLAUSE}
    """
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(access_sql, params)
            m = cur.fetchone()
            if not m:
                raise HTTPException(status_code=404, detail="Matter not found or access denied")

            cur.execute(
                f"SELECT d.document_id, d.title FROM documents d WHERE d.matter_id = %(mid)s AND {doc_acl('d')} LIMIT 5",
                {"mid": matter_id, "member_id": member_id},
            )
            docs = cur.fetchall()

            cur.execute(
                """
                SELECT mem.member_id, mem.name, mm.role_on_matter
                FROM matter_members mm
                JOIN members mem ON mem.member_id = mm.member_id
                WHERE mm.matter_id = %(mid)s
                LIMIT 4
                """,
                {"mid": matter_id},
            )
            team = cur.fetchall()

    nodes = [{"id": m["matter_id"], "label": m["matter_code"], "type": "matter", "title": m["title"]}]
    nodes.append({"id": f"cli-{m['matter_id']}", "label": m["client_name"], "type": "client"})
    edges = [{"source": m["matter_id"], "target": f"cli-{m['matter_id']}"}]

    for d in docs:
        nodes.append({"id": d["document_id"], "label": d["title"][:24], "type": "doc"})
        edges.append({"source": m["matter_id"], "target": d["document_id"]})

    for t in team:
        nodes.append({"id": t["member_id"], "label": t["name"], "type": "person"})
        edges.append({"source": m["matter_id"], "target": t["member_id"]})

    return {"service": SERVICE, "nodes": nodes, "edges": edges}
