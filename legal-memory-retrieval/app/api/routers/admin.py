"""Firm administration (plan §5): users and roles, teams, walls overview.

Mounted at /api/admin. Each endpoint checks a permission key; admin roles do
not grant access to matter content.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import access
from app.auth.deps import resolve_member
from app.db.connection import connect

router = APIRouter(tags=["admin"])


def _run(fn, *args, **kwargs):
    with connect() as conn:
        try:
            return fn(conn, *args, **kwargs)
        except access.AccessError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.detail) from exc


class RolesUpdate(BaseModel):
    roles: list[str]


class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    kind: Literal["practice", "office", "matter", "custom"] = "custom"
    description: str = Field(default="", max_length=500)
    external_group_id: str | None = None


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class TeamMemberUpdate(BaseModel):
    team_role: Literal["member", "lead"] = "member"


@router.get("/health")
def admin_health() -> dict:
    return {"service": "admin", "status": "ok"}


@router.get("/roles")
def roles(member_id: str | None = Depends(resolve_member)) -> dict:
    with connect() as conn:
        rows = access._rows(
            conn,
            """
            SELECT r.role_key, r.name, r.description,
                   coalesce(array_agg(p.permission ORDER BY p.permission) FILTER (WHERE p.permission IS NOT NULL), '{}') AS permissions,
                   (SELECT count(*) FROM member_roles mr WHERE mr.role_key = r.role_key) AS member_count
            FROM firm_roles r LEFT JOIN role_permissions p USING (role_key)
            GROUP BY r.role_key ORDER BY r.role_key
            """,
        )
    return {"items": rows}


@router.get("/users")
def users(member_id: str | None = Depends(resolve_member)) -> dict:
    return {"items": _run(access.list_users, member_id)}


@router.put("/users/{target}/roles")
def put_user_roles(target: str, body: RolesUpdate, member_id: str | None = Depends(resolve_member)) -> dict:
    return {"member_id": target, "roles": _run(access.set_member_roles, member_id, target, body.roles)}


@router.get("/teams")
def teams(member_id: str | None = Depends(resolve_member)) -> dict:
    with connect() as conn:
        return {"items": access.list_teams(conn)}


@router.post("/teams", status_code=201)
def post_team(body: TeamCreate, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(access.create_team, member_id, access.TeamInput(**body.model_dump()))


@router.patch("/teams/{team_id}")
def patch_team(team_id: str, body: TeamUpdate, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(access.update_team, member_id, team_id, body.name, body.description)


@router.delete("/teams/{team_id}", status_code=204)
def delete_team(team_id: str, member_id: str | None = Depends(resolve_member)) -> None:
    _run(access.delete_team, member_id, team_id)


@router.put("/teams/{team_id}/members/{target}", status_code=204)
def put_team_member(team_id: str, target: str, body: TeamMemberUpdate | None = None,
                    member_id: str | None = Depends(resolve_member)) -> None:
    _run(access.set_team_member, member_id, team_id, target, True, (body or TeamMemberUpdate()).team_role)


@router.delete("/teams/{team_id}/members/{target}", status_code=204)
def delete_team_member(team_id: str, target: str, member_id: str | None = Depends(resolve_member)) -> None:
    _run(access.set_team_member, member_id, team_id, target, False)


@router.get("/walls")
def walls(member_id: str | None = Depends(resolve_member)) -> dict:
    return {"items": _run(access.walls_overview, member_id)}
