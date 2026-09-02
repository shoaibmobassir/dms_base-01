from fastapi import APIRouter
from psycopg.rows import dict_row

from app.db.connection import connect

router = APIRouter(tags=["teams"])

SERVICE = "teams"


@router.get("/health")
def teams_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


@router.get("")
def teams_list() -> dict:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT unnest(practice_areas) AS practice, COUNT(*) AS lawyers
                FROM members WHERE is_lawyer = TRUE
                GROUP BY practice ORDER BY lawyers DESC
                """
            )
            by_practice = list(cur.fetchall())
            cur.execute(
                """
                SELECT practice_area, COUNT(*) AS matters
                FROM matters GROUP BY practice_area ORDER BY matters DESC
                """
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
