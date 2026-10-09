"""Playbooks (plan 22, W5): mounted at /api/playbooks. Services live in ``app/playbooks``."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from app import playbooks as svc
from app.auth.deps import resolve_member
from app.db.connection import connect
from app.firm import FirmError

router = APIRouter(tags=["playbooks"])


def _run(fn, *args, **kwargs):
    with connect() as conn:
        try:
            return jsonable_encoder(fn(conn, *args, **kwargs))
        except FirmError as exc:
            conn.rollback()
            raise HTTPException(status_code=exc.status, detail=jsonable_encoder({"message": exc.detail, **exc.extra})) from exc


class Column(BaseModel):
    label: str = Field(max_length=120)
    question: str = Field(max_length=2000)
    answer_format: Literal["text", "date", "yes_no", "number", "money", "list", "choice"] = "text"
    choices: list[str] = Field(default_factory=list, max_length=20)


class PlaybookIn(BaseModel):
    kind: Literal["instructions", "columns"]
    title: str = Field(max_length=200)
    summary: str | None = Field(default=None, max_length=500)
    practice_area: str | None = Field(default=None, max_length=100)
    jurisdiction: str | None = Field(default=None, max_length=100)
    language: str | None = Field(default=None, max_length=50)
    body_md: str = Field(default="", max_length=60000)
    columns: list[Column] = Field(default_factory=list, max_length=30)
    document_ids: list[str] = Field(default_factory=list, max_length=20)


class PlaybookPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=500)
    practice_area: str | None = Field(default=None, max_length=100)
    jurisdiction: str | None = Field(default=None, max_length=100)
    language: str | None = Field(default=None, max_length=50)
    body_md: str | None = Field(default=None, max_length=60000)
    columns: list[Column] | None = Field(default=None, max_length=30)
    document_ids: list[str] | None = Field(default=None, max_length=20)
    row_version: int | None = None


class ShareIn(BaseModel):
    principal_type: Literal["member", "team"] = "member"
    principal_id: str
    level: Literal["view", "edit"] | None = "view"


@router.get("/health")
def health() -> dict:
    return {"service": "playbooks", "status": "ok"}


@router.get("")
def list_playbooks(kind: Literal["instructions", "columns"] | None = None, q: str | None = None,
                   source: Literal["shipped", "firm", "personal"] | None = None,
                   member_id: str | None = Depends(resolve_member)) -> dict:
    return {"items": _run(svc.list_playbooks, member_id, kind=kind, q=q, source=source)}


@router.post("", status_code=201)
def create_playbook(body: PlaybookIn, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(svc.create_playbook, member_id, body.model_dump())


@router.get("/{playbook_id}")
def get_playbook(playbook_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(svc.get_playbook, member_id, playbook_id)


@router.patch("/{playbook_id}")
def update_playbook(playbook_id: str, body: PlaybookPatch, member_id: str | None = Depends(resolve_member)) -> dict:
    changes = body.model_dump(exclude_unset=True)
    version = changes.pop("row_version", None)
    return _run(svc.update_playbook, member_id, playbook_id, changes, version)


@router.post("/{playbook_id}/duplicate", status_code=201)
def duplicate_playbook(playbook_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(svc.duplicate_playbook, member_id, playbook_id)


@router.post("/{playbook_id}/publish")
def publish_playbook(playbook_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(svc.publish_playbook, member_id, playbook_id)


@router.put("/{playbook_id}/shares")
def share_playbook(playbook_id: str, body: ShareIn, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(svc.share_playbook, member_id, playbook_id, body.principal_type, body.principal_id, body.level)


@router.delete("/{playbook_id}")
def archive_playbook(playbook_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(svc.archive_playbook, member_id, playbook_id)
