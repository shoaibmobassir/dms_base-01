from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row

from app.api.acl import ACL_CLAUSE
from app.auth.deps import resolve_member
from app.db.connection import connect

router = APIRouter(tags=["clients"])

SERVICE = "clients"


@router.get("/health")
def clients_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


@router.get("")
def clients_list(
    q: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if q:
                like = f"%{q}%"
                cur.execute(
                    "SELECT client_id, name, industry, size, headquarters"
                    " FROM clients WHERE name ILIKE %(like)s OR industry ILIKE %(like)s"
                    " ORDER BY name, client_id LIMIT %(limit)s OFFSET %(offset)s",
                    {"like": like, "limit": limit, "offset": offset},
                )
                items = list(cur.fetchall())
                cur.execute(
                    "SELECT COUNT(*) AS n FROM clients"
                    " WHERE name ILIKE %(like)s OR industry ILIKE %(like)s",
                    {"like": like},
                )
            else:
                cur.execute(
                    "SELECT client_id, name, industry, size, headquarters"
                    " FROM clients ORDER BY name, client_id"
                    " LIMIT %(limit)s OFFSET %(offset)s",
                    {"limit": limit, "offset": offset},
                )
                items = list(cur.fetchall())
                cur.execute("SELECT COUNT(*) AS n FROM clients")
            total = cur.fetchone()["n"]
            return {"service": SERVICE, "total": total, "items": items}


@router.get("/{client_id}/matters")
def client_matters(
    client_id: str,
    member_id: str | None = Depends(resolve_member),
    limit: int = Query(default=20, le=100),
) -> dict:
    params = {"client_id": client_id, "member_id": member_id, "limit": limit}
    sql = f"""
        SELECT m.matter_id, m.matter_code, m.title, m.client_name, m.practice_area,
               m.status, m.opened_date, m.claim_amount,
               COALESCE(p.restricted, FALSE) AS restricted
        FROM matters m
        LEFT JOIN permissions p ON p.matter_id = m.matter_id
        WHERE m.client_id = %(client_id)s AND {ACL_CLAUSE}
        ORDER BY m.opened_date DESC NULLS LAST
        LIMIT %(limit)s
    """
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            items = list(cur.fetchall())
    return {"service": SERVICE, "client_id": client_id, "items": items}


@router.get("/{client_id}")
def client_detail(client_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM clients WHERE client_id = %(cid)s", {"cid": client_id})
            client = cur.fetchone()
            if not client:
                raise HTTPException(status_code=404, detail="Client not found")

            params = {"cid": client_id, "member_id": member_id}
            cur.execute(
                f"""
                SELECT m.matter_id, m.matter_code, m.title, m.practice_area, m.status, m.opened_date
                FROM matters m
                LEFT JOIN permissions p ON p.matter_id = m.matter_id
                WHERE m.client_id = %(cid)s AND {ACL_CLAUSE}
                ORDER BY m.opened_date DESC NULLS LAST
                LIMIT 10
                """,
                params,
            )
            matters = list(cur.fetchall())

            # Notes sourced from a restricted matter are hidden like the matter itself.
            cur.execute(
                f"""
                SELECT n.note_id, n.kind, n.text, n.source_matter_id,
                       sm.matter_code AS source_matter_code, n.author_member_id,
                       mb.name AS author_name, n.created_at
                FROM client_notes n
                LEFT JOIN matters sm ON sm.matter_id = n.source_matter_id
                LEFT JOIN permissions p ON p.matter_id = n.source_matter_id
                LEFT JOIN members mb ON mb.member_id = n.author_member_id
                WHERE n.client_id = %(cid)s
                  AND (n.source_matter_id IS NULL OR {ACL_CLAUSE})
                ORDER BY n.kind, n.created_at DESC
                """,
                params,
            )
            notes = list(cur.fetchall())

    client["matters"] = matters
    client["notes"] = notes
    client["service"] = SERVICE
    return client
