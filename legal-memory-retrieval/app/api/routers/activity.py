from fastapi import APIRouter, Depends, Query
from psycopg.rows import dict_row

from app.api.acl import ACL_CLAUSE
from app.auth.deps import resolve_member
from app.db.connection import connect

router = APIRouter(tags=["activity"])

SERVICE = "activity"


@router.get("/health")
def activity_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


@router.get("")
def activity_feed(
    member_id: str | None = Depends(resolve_member),
    limit: int = Query(default=25, le=50),
) -> dict:
    params = {"member_id": member_id, "limit": limit}
    sql = f"""
        SELECT d.document_id, d.title, d.document_type, d.author_name,
               d.doc_date, d.matter_code, d.matter_id, m.client_name
        FROM documents d
        JOIN permissions p ON p.matter_id = d.matter_id
        JOIN matters m ON m.matter_id = d.matter_id
        WHERE {ACL_CLAUSE}
        ORDER BY d.doc_date DESC NULLS LAST, d.document_id DESC
        LIMIT %(limit)s
    """
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            docs = list(cur.fetchall())
    items = [
        {
            "kind": "document",
            "title": d["title"],
            "subtitle": f"{d['document_type']} · {d['matter_code']}",
            "actor": d.get("author_name") or "Unknown",
            "date": str(d["doc_date"]) if d.get("doc_date") else None,
            "matter_id": d["matter_id"],
            "document_id": d["document_id"],
        }
        for d in docs
    ]
    return {"service": SERVICE, "items": items}
