from fastapi import APIRouter
from psycopg.rows import dict_row

from app.db.connection import connect

router = APIRouter(tags=["home"])

SERVICE = "home"


@router.get("/health")
def home_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


@router.get("/stats")
def home_stats() -> dict:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            counts = {}
            for table in ("members", "clients", "matters", "documents", "arguments", "projects"):
                cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
                counts[table] = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM permissions WHERE restricted = TRUE")
            counts["restricted_matters"] = cur.fetchone()["n"]
    return {"service": SERVICE, "firm": "Apex Chambers", "counts": counts}
