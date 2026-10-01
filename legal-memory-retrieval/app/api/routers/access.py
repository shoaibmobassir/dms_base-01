"""Matter access management and access requests (plan §5).

Mounted at /api/access. Managers of a matter (lead, manage grant) and
risk & compliance (walls.manage) change who can see it; screens are
risk & compliance only. Every change is audited and recompiles the ACL.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import access
from app.auth.deps import resolve_member
from app.db.connection import connect

router = APIRouter(tags=["access"])


def _run(fn, *args, **kwargs):
    with connect() as conn:
        try:
            return fn(conn, *args, **kwargs)
        except access.AccessError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.detail) from exc


class ModeUpdate(BaseModel):
    mode: Literal["open", "team", "restricted"]
    hide_existence: bool | None = None
    row_version: int | None = None


class GrantCreate(BaseModel):
    principal_type: Literal["member", "team"]
    principal_id: str = Field(min_length=1, max_length=64)
    level: Literal["read", "edit", "manage"] = "read"
    reason: str = Field(default="", max_length=500)
    expires_at: str | None = None


class ScreenCreate(BaseModel):
    member_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=3, max_length=500)


class RequestCreate(BaseModel):
    level: Literal["read", "edit"] = "read"
    reason: str = Field(min_length=3, max_length=1000)


class Decision(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=1000)


@router.get("/health")
def access_health() -> dict:
    return {"service": "access", "status": "ok"}


@router.get("/me")
def my_access(member_id: str | None = Depends(resolve_member)) -> dict:
    """The caller's firm roles and permission keys (drives which admin screens show)."""
    with connect() as conn:
        perms = access.member_permissions(conn, member_id)
        roles = access.member_roles(conn, member_id) if member_id else []
    return {"member_id": member_id, "roles": roles, "permissions": sorted(perms)}


@router.get("/matters/{matter_id}")
def get_matter_access(matter_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(access.matter_access_summary, member_id, matter_id)


@router.get("/matters/{matter_id}/status")
def matter_status(matter_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    """What the caller may do with this matter; 404 when it is hidden from them."""
    return _run(access.access_status, member_id, matter_id)


@router.put("/matters/{matter_id}")
def put_matter_mode(matter_id: str, body: ModeUpdate, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(access.set_matter_mode, member_id, matter_id, body.mode, body.hide_existence, body.row_version)


@router.post("/matters/{matter_id}/grants", status_code=201)
def post_grant(matter_id: str, body: GrantCreate, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(access.add_grant, member_id, matter_id, body.principal_type, body.principal_id,
                body.level, body.reason, body.expires_at)


@router.delete("/matters/{matter_id}/grants/{grant_id}", status_code=204)
def delete_grant(matter_id: str, grant_id: str, member_id: str | None = Depends(resolve_member)) -> None:
    _run(access.remove_grant, member_id, matter_id, grant_id)


@router.post("/matters/{matter_id}/screens", status_code=201)
def post_screen(matter_id: str, body: ScreenCreate, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(access.add_screen, member_id, matter_id, body.member_id, body.reason)


@router.delete("/matters/{matter_id}/screens/{screened_id}", status_code=204)
def delete_screen(matter_id: str, screened_id: str, member_id: str | None = Depends(resolve_member)) -> None:
    _run(access.remove_screen, member_id, matter_id, screened_id)


@router.post("/matters/{matter_id}/requests", status_code=201)
def post_request(matter_id: str, body: RequestCreate, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(access.request_access, member_id, matter_id, body.level, body.reason)


@router.get("/requests")
def get_requests(
    scope: Literal["mine", "to_decide"] = Query(default="to_decide"),
    member_id: str | None = Depends(resolve_member),
) -> dict:
    return {"items": _run(access.list_requests, member_id, scope)}


@router.post("/requests/{request_id}/decision")
def post_decision(request_id: str, body: Decision, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(access.decide_request, member_id, request_id, body.approve, body.note)
