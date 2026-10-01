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


# The argument bank mixes three kinds of record: arguments run in disputes and
# petitions, PCIJ docket entries and Security Council resolution summaries.
_KIND_SQL = """CASE m.matter_type
    WHEN 'Permanent Court of International Justice' THEN 'pcij'
    WHEN 'Security Council Resolution' THEN 'unsc'
    ELSE 'disputes' END"""
ARGUMENT_KINDS = ("disputes", "pcij", "unsc")


@router.get("/arguments")
def knowledge_arguments(
    q: str | None = Query(default=None),
    kind: str | None = Query(default=None, description="disputes | pcij | unsc"),
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
            " OR a.position ILIKE %(like)s OR m.court ILIKE %(like)s)"
        )
    base_where = " AND ".join(wheres)
    if kind in ARGUMENT_KINDS:
        wheres.append(f"({_KIND_SQL}) = %(kind)s")
        params["kind"] = kind
    where = " AND ".join(wheres)
    from_sql = """
        FROM arguments a
        JOIN matters m ON m.matter_id = a.matter_id
        LEFT JOIN permissions p ON p.matter_id = a.matter_id
    """
    sql = f"""
        SELECT a.argument_id, a.matter_id, a.issue, a.position, a.argument,
               a.outcome, m.matter_code, m.practice_area, m.title AS matter_title,
               m.court, m.matter_type, m.opened_date, m.status AS matter_status,
               ({_KIND_SQL}) AS kind,
               lead.name AS lead_name, lead.member_id AS lead_member_id,
               COALESCE((
                   SELECT json_agg(json_build_object('document_id', d.document_id, 'title', d.title,
                                                     'document_type', d.document_type) ORDER BY d.doc_date NULLS LAST)
                   FROM documents d WHERE d.document_id = ANY(a.supporting_documents)
               ), '[]'::json) AS supporting_documents
        {from_sql}
        LEFT JOIN LATERAL (
            SELECT mb.member_id, mb.name FROM matter_members mm JOIN members mb USING (member_id)
            WHERE mm.matter_id = m.matter_id AND lower(coalesce(mm.role_on_matter, '')) = 'lead'
            ORDER BY mb.member_id LIMIT 1
        ) lead ON TRUE
        WHERE {where}
        ORDER BY array_position(ARRAY['disputes','pcij','unsc'], {_KIND_SQL}),
                 m.opened_date DESC NULLS LAST, a.argument_id
        LIMIT %(limit)s OFFSET %(offset)s
    """
    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            items = list(cur.fetchall())
            cur.execute(f"SELECT COUNT(*) AS n {from_sql} WHERE {where}", count_params)
            total = cur.fetchone()["n"]
            cur.execute(
                f"SELECT ({_KIND_SQL}) AS kind, COUNT(*) AS n {from_sql} WHERE {base_where} GROUP BY 1",
                {k: v for k, v in count_params.items() if k != "kind"},
            )
            kinds = {r["kind"]: r["n"] for r in cur.fetchall()}
    return {"service": SERVICE, "total": total, "items": items, "kinds": kinds}
