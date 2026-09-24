from fastapi import APIRouter, Depends, Query
from psycopg.rows import dict_row

from app.api.acl import ACL_CLAUSE
from app.auth.deps import resolve_member
from app.db.connection import connect

router = APIRouter(tags=["knowledge"])

SERVICE = "knowledge"


@router.get("/health")
def knowledge_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


@router.get("/arguments")
def knowledge_arguments(
    q: str | None = Query(default=None),
    limit: int = Query(default=30, le=100),
    offset: int = Query(default=0, ge=0),
    member_id: str | None = Depends(resolve_member),
) -> dict:
    params: dict = {"member_id": member_id, "limit": limit, "offset": offset}
    wheres = [ACL_CLAUSE]
    if q:
        params["like"] = f"%{q}%"
        wheres.append(
            "(a.issue ILIKE %(like)s OR a.argument ILIKE %(like)s"
            " OR a.position ILIKE %(like)s)"
        )
    where = " AND ".join(wheres)
    from_sql = f"""
        FROM arguments a
        JOIN matters m ON m.matter_id = a.matter_id
        LEFT JOIN permissions p ON p.matter_id = a.matter_id
        WHERE {where}
    """
    sql = f"""
        SELECT a.argument_id, a.matter_id, a.issue, a.position, a.argument,
               a.outcome, m.matter_code, m.practice_area, m.title AS matter_title
        {from_sql}
        ORDER BY a.issue, a.argument_id
        LIMIT %(limit)s OFFSET %(offset)s
    """
    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            items = list(cur.fetchall())
            cur.execute(f"SELECT COUNT(*) AS n {from_sql}", count_params)
            total = cur.fetchone()["n"]
    return {"service": SERVICE, "total": total, "items": items}
