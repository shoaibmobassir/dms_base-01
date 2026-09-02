from fastapi import APIRouter, Depends, Query
from psycopg.rows import dict_row

from app.api.acl import ACL_CLAUSE
from app.auth.deps import resolve_member
from app.db.connection import connect

router = APIRouter(tags=["search"])

SERVICE = "search"


@router.get("/health")
def search_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


@router.get("")
def search(
    q: str,
    kind: str = Query(default="all", description="all|matter|document|client|member"),
    member_id: str | None = Depends(resolve_member),
    limit: int = Query(default=20, le=50),
) -> dict:
    like = f"%{q}%"
    results: list[dict] = []
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if kind in ("all", "matter"):
                cur.execute(
                    f"""
                    SELECT 'matter' AS kind, m.matter_id AS id,
                           m.matter_code AS code, m.title,
                           m.client_name AS subtitle, m.practice_area AS meta,
                           m.status
                    FROM matters m
                    LEFT JOIN permissions p ON p.matter_id = m.matter_id
                    WHERE (m.title ILIKE %(like)s OR m.matter_code ILIKE %(like)s
                           OR m.client_name ILIKE %(like)s)
                      AND {ACL_CLAUSE}
                    ORDER BY m.opened_date DESC NULLS LAST
                    LIMIT %(limit)s
                    """,
                    {"like": like, "member_id": member_id, "limit": limit},
                )
                results.extend(cur.fetchall())
            if kind in ("all", "document"):
                cur.execute(
                    f"""
                    SELECT 'document' AS kind, d.document_id AS id,
                           d.document_id AS code, d.title,
                           d.document_type AS subtitle, d.matter_code AS meta,
                           d.status
                    FROM documents d
                    LEFT JOIN permissions p ON p.matter_id = d.matter_id
                    WHERE (d.title ILIKE %(like)s OR d.document_type ILIKE %(like)s)
                      AND {ACL_CLAUSE}
                    ORDER BY d.doc_date DESC NULLS LAST
                    LIMIT %(limit)s
                    """,
                    {"like": like, "member_id": member_id, "limit": limit},
                )
                results.extend(cur.fetchall())
            if kind in ("all", "client"):
                cur.execute(
                    "SELECT 'client' AS kind, client_id AS id, client_id AS code,"
                    " name AS title, industry AS subtitle, headquarters AS meta,"
                    " NULL AS status"
                    " FROM clients WHERE name ILIKE %(like)s OR industry ILIKE %(like)s"
                    " LIMIT %(limit)s",
                    {"like": like, "limit": limit},
                )
                results.extend(cur.fetchall())
            if kind in ("all", "member"):
                cur.execute(
                    "SELECT 'member' AS kind, member_id AS id, member_id AS code,"
                    " name AS title, role AS subtitle, office AS meta, NULL AS status"
                    " FROM members WHERE name ILIKE %(like)s OR role ILIKE %(like)s"
                    " LIMIT %(limit)s",
                    {"like": like, "limit": limit},
                )
                results.extend(cur.fetchall())
    return {"service": SERVICE, "query": q, "results": results[:limit]}
