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
    limit: int = Query(default=30, le=100),
) -> dict:
    params = {"member_id": member_id, "limit": limit}
    sql = f"""
        SELECT pr.project_id, pr.title, pr.deadline, pr.status, pr.progress,
               m.matter_code, m.client_name, m.court
        FROM projects pr
        JOIN matters m ON m.matter_id = pr.matter_id
        LEFT JOIN permissions p2 ON p2.matter_id = pr.matter_id
        WHERE pr.status != 'Completed' AND pr.deadline IS NOT NULL
          AND {ACL_CLAUSE.replace('p.', 'p2.')}
        ORDER BY pr.deadline ASC
        LIMIT %(limit)s
    """
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = list(cur.fetchall())
    items = [
        {
            "id": r["project_id"],
            "title": r["title"],
            "due": str(r["deadline"]),
            "matter_code": r.get("matter_code"),
            "client_name": r.get("client_name"),
            "court": r.get("court"),
            "status": r.get("status"),
            "progress": r.get("progress"),
        }
        for r in rows
    ]
    return {"service": SERVICE, "items": items}
