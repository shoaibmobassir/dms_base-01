from fastapi import APIRouter
from psycopg.rows import dict_row

from app.db.connection import connect

router = APIRouter(tags=["people"])

SERVICE = "people"


@router.get("/health")
def people_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


@router.get("")
def people_list() -> dict:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT member_id, name, role, practice_areas, specializations,
                       office, joined_year, is_lawyer
                FROM members
                ORDER BY is_lawyer DESC, role, name
                """
            )
            return {"service": SERVICE, "items": list(cur.fetchall())}


@router.get("/{member_id}")
def person_detail(member_id: str) -> dict:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT member_id, name, role, practice_areas, specializations,
                       office, joined_year, is_lawyer
                FROM members WHERE member_id = %(mid)s
                """,
                {"mid": member_id},
            )
            person = cur.fetchone()
            if not person:
                return {"service": SERVICE, "member_id": member_id, "found": False}
            cur.execute(
                """
                SELECT m.matter_id, m.matter_code, m.title, mm.role_on_matter
                FROM matter_members mm
                JOIN matters m ON m.matter_id = mm.matter_id
                WHERE mm.member_id = %(mid)s
                ORDER BY m.opened_date DESC NULLS LAST
                LIMIT 10
                """,
                {"mid": member_id},
            )
            matters = list(cur.fetchall())
    return {"service": SERVICE, "person": person, "matters": matters}
