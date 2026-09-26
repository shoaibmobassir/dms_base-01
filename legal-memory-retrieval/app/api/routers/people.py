from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row

from app.api.acl import ACL_CLAUSE
from app.auth.deps import resolve_member
from app.db.connection import connect

router = APIRouter(tags=["people"])

SERVICE = "people"


@router.get("/health")
def people_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


@router.get("")
def people_list(_caller: str | None = Depends(resolve_member)) -> dict:
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


@router.get("/me")
def whoami(caller_id: str | None = Depends(resolve_member)) -> dict:
    """The authenticated member (or the dev-mode X-Member-Id persona)."""
    if caller_id is None:
        raise HTTPException(status_code=401, detail="No member identity on this request")
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT member_id, name, role, practice_areas, specializations,
                       office, joined_year, is_lawyer
                FROM members WHERE member_id = %(mid)s
                """,
                {"mid": caller_id},
            )
            person = cur.fetchone()
    if not person:
        raise HTTPException(status_code=401, detail="Unknown member")
    return {"service": SERVICE, "person": person}


@router.get("/{member_id}")
def person_detail(
    member_id: str,
    caller_id: str | None = Depends(resolve_member),
) -> dict:
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
                raise HTTPException(status_code=404, detail="Person not found")
            # Only matters the caller may see — a colleague's restricted work stays hidden.
            cur.execute(
                f"""
                SELECT m.matter_id, m.matter_code, m.title, m.status, m.practice_area,
                       mm.role_on_matter
                FROM matter_members mm
                JOIN matters m ON m.matter_id = mm.matter_id
                LEFT JOIN permissions p ON p.matter_id = m.matter_id
                WHERE mm.member_id = %(mid)s AND {ACL_CLAUSE}
                ORDER BY m.opened_date DESC NULLS LAST
                LIMIT 25
                """,
                {"mid": member_id, "member_id": caller_id},
            )
            matters = list(cur.fetchall())
    return {"service": SERVICE, "person": person, "matters": matters}
