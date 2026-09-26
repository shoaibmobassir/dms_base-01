from fastapi import APIRouter, Depends
from psycopg.rows import dict_row

from app.api.acl import ACL_CLAUSE
from app.api.firm import firm_profile
from app.auth.deps import resolve_member
from app.db.connection import connect

router = APIRouter(tags=["home"])

SERVICE = "home"


@router.get("/health")
def home_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


@router.get("/stats")
def home_stats(member_id: str | None = Depends(resolve_member)) -> dict:
    """Counts within the caller's access scope (matter-derived counts are ACL-filtered)."""
    params = {"member_id": member_id}
    in_scope = f"""
        SELECT m.matter_id FROM matters m
        LEFT JOIN permissions p ON p.matter_id = m.matter_id
        WHERE {ACL_CLAUSE}
    """
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                WITH scope AS ({in_scope})
                SELECT
                  (SELECT COUNT(*) FROM scope) AS matters,
                  (SELECT COUNT(*) FROM documents d JOIN scope s USING (matter_id)) AS documents,
                  (SELECT COUNT(*) FROM arguments a JOIN scope s USING (matter_id)) AS arguments,
                  (SELECT COUNT(DISTINCT m.client_id) FROM matters m JOIN scope s USING (matter_id)) AS clients,
                  (SELECT COUNT(*) FROM court_deadlines c JOIN scope s USING (matter_id)
                     WHERE c.status = 'open') AS open_deadlines,
                  (SELECT COUNT(*) FROM members) AS members
                """,
                params,
            )
            counts = dict(cur.fetchone())
        firm = firm_profile(conn)
    counts["people"] = counts["members"]
    return {"service": SERVICE, "firm": firm["name"], "counts": counts}
