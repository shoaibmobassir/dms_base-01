from fastapi import APIRouter, Depends
from psycopg.rows import dict_row

from app.api.acl import ACL_CLAUSE
from app.auth.deps import resolve_member
from app.db.connection import connect

router = APIRouter(tags=["teams"])

SERVICE = "teams"


@router.get("/health")
def teams_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


@router.get("")
def teams_list(member_id: str | None = Depends(resolve_member)) -> dict:
    """Practice teams: lawyers per practice area, with open matters in the caller's scope."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT unnest(practice_areas) AS practice, COUNT(*) AS lawyers
                FROM members WHERE is_lawyer = TRUE
                GROUP BY practice ORDER BY lawyers DESC, practice
                """
            )
            by_practice = list(cur.fetchall())
            cur.execute(
                f"""
                SELECT m.practice_area, COUNT(*) AS matters
                FROM matters m
                LEFT JOIN permissions p ON p.matter_id = m.matter_id
                WHERE m.status = 'Open' AND {ACL_CLAUSE}
                GROUP BY m.practice_area
                """,
                {"member_id": member_id},
            )
            matter_counts = {r["practice_area"]: r["matters"] for r in cur.fetchall()}
    items = [
        {
            "name": r["practice"],
            "lawyers": r["lawyers"],
            "active_matters": matter_counts.get(r["practice"], 0),
        }
        for r in by_practice
    ]
    return {"service": SERVICE, "items": items}
