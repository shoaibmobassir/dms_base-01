from fastapi import APIRouter, Depends, Query
from psycopg.rows import dict_row

from app.api.acl import ACL_CLAUSE
from app.auth.deps import resolve_member
from app.db.connection import connect

router = APIRouter(tags=["tasks"])

SERVICE = "tasks"


@router.get("/health")
def tasks_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


@router.get("")
def tasks_list(
    member_id: str | None = Depends(resolve_member),
    status: str = Query(default="open", pattern="^(open|done|all)$"),
    matter_id: str | None = Query(default=None),
    limit: int = Query(default=30, le=100),
) -> dict:
    """Court deadlines on matters the caller may see, soonest first."""
    params: dict = {"member_id": member_id, "limit": limit}
    wheres = [ACL_CLAUSE]
    if status != "all":
        wheres.append("c.status = %(status)s")
        params["status"] = status
    if matter_id:
        wheres.append("c.matter_id = %(matter_id)s")
        params["matter_id"] = matter_id
    sql = f"""
        SELECT c.deadline_id, c.title, c.kind, c.due_date, c.status, c.notes,
               COALESCE(c.court, m.court) AS court,
               m.matter_id, m.matter_code, m.title AS matter_title, m.client_name,
               c.owner_member_id, mb.name AS owner_name
        FROM court_deadlines c
        JOIN matters m ON m.matter_id = c.matter_id
        LEFT JOIN permissions p ON p.matter_id = c.matter_id
        LEFT JOIN members mb ON mb.member_id = c.owner_member_id
        WHERE {' AND '.join(wheres)}
        ORDER BY c.due_date ASC, c.deadline_id
        LIMIT %(limit)s
    """
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = list(cur.fetchall())
    items = [
        {
            "id": r["deadline_id"],
            "title": r["title"],
            "kind": r["kind"],
            "due": r["due_date"].isoformat(),
            "status": r["status"],
            "notes": r["notes"],
            "court": r["court"],
            "matter_id": r["matter_id"],
            "matter_code": r["matter_code"],
            "matter_title": r["matter_title"],
            "client_name": r["client_name"],
            "owner_member_id": r["owner_member_id"],
            "owner_name": r["owner_name"],
        }
        for r in rows
    ]
    return {"service": SERVICE, "items": items}
