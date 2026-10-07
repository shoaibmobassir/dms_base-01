"""Workspaces (plan 22, W0): projects, what a workspace shows, links, filing, copies, folders, tags.

Mounted at /api/projects and /api/workspaces. Services live in ``app/workspaces``.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from app.auth.deps import resolve_member
from app.db.connection import connect
from app.firm import FirmError
from app.workspaces import documents as doc_svc, projects as project_svc, state as state_svc

projects_router = APIRouter(tags=["projects"])
workspaces_router = APIRouter(tags=["workspaces"])

Kind = Literal["matter", "project", "library", "firm"]


def _run(fn, *args, **kwargs):
    with connect() as conn:
        try:
            return jsonable_encoder(fn(conn, *args, **kwargs))
        except FirmError as exc:
            conn.rollback()
            raise HTTPException(status_code=exc.status, detail=jsonable_encoder({"message": exc.detail, **exc.extra})) from exc


def _container(kind: str, container_id: str, member_id: str | None) -> str:
    """``library/me`` names the caller's own library."""
    if kind == "library" and container_id == "me":
        if member_id is None:
            raise HTTPException(status_code=422, detail={"message": "Sign in to use your library"})
        return member_id
    return container_id


# ── projects ─────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    title: str = Field(max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    matter_id: str | None = None


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    matter_id: str | None = None
    row_version: int | None = None


class MemberSet(BaseModel):
    principal_type: Literal["member", "team"] = "member"
    principal_id: str
    role: Literal["owner", "editor", "viewer"] = "editor"


@projects_router.get("/health")
def projects_health() -> dict:
    return {"service": "projects", "status": "ok"}


@projects_router.get("")
def list_projects(q: str | None = None, archived: bool = False, limit: int = Query(default=100, ge=1, le=200),
                  offset: int = Query(default=0, ge=0), member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(project_svc.list_projects, member_id, q=q, archived=archived, limit=limit, offset=offset)


@projects_router.post("", status_code=201)
def create_project(body: ProjectCreate, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(project_svc.create_project, member_id, body.model_dump())


@projects_router.get("/{project_id}")
def get_project(project_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(project_svc.get_project, member_id, project_id)


@projects_router.patch("/{project_id}")
def update_project(project_id: str, body: ProjectUpdate, member_id: str | None = Depends(resolve_member)) -> dict:
    changes = body.model_dump(exclude_unset=True)
    version = changes.pop("row_version", None)
    return _run(project_svc.update_project, member_id, project_id, changes, version)


@projects_router.post("/{project_id}/archive")
def archive_project(project_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(project_svc.set_archived, member_id, project_id, True)


@projects_router.post("/{project_id}/restore")
def restore_project(project_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(project_svc.set_archived, member_id, project_id, False)


@projects_router.put("/{project_id}/members")
def set_member(project_id: str, body: MemberSet, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(project_svc.set_member, member_id, project_id, body.principal_type, body.principal_id, body.role)


@projects_router.delete("/{project_id}/members/{principal_type}/{principal_id}")
def remove_member(project_id: str, principal_type: Literal["member", "team"], principal_id: str,
                  member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(project_svc.remove_member, member_id, project_id, principal_type, principal_id)


# ── workspaces: listing and folders ──────────────────────────────────────────

class FolderCreate(BaseModel):
    path: str = Field(max_length=500)


class FolderRename(BaseModel):
    path: str = Field(max_length=500)
    new_path: str = Field(max_length=500)


class Target(BaseModel):
    kind: Kind
    id: str
    folder: str = Field(default="", max_length=500)


class CopyBody(Target):
    title: str | None = Field(default=None, max_length=300)


class TagBody(BaseModel):
    tag: str = Field(max_length=80)


class DuplicateCheck(BaseModel):
    kind: Kind
    id: str
    hashes: list[str] = Field(max_length=500)


@workspaces_router.get("/health")
def workspaces_health() -> dict:
    return {"service": "workspaces", "status": "ok"}


@workspaces_router.get("/{kind}/{container_id}/items")
def list_items(kind: Kind, container_id: str, folder: str = "", recursive: bool = False, q: str | None = None,
               tag: str | None = None, limit: int = Query(default=200, ge=1, le=1000),
               offset: int = Query(default=0, ge=0), member_id: str | None = Depends(resolve_member)) -> dict:
    cid = _container(kind, container_id, member_id)
    return _run(doc_svc.list_items, member_id, kind, cid, folder=folder, recursive=recursive, q=q, tag=tag,
                limit=limit, offset=offset)


@workspaces_router.get("/{kind}/{container_id}/search")
def search_workspace(kind: Kind, container_id: str, q: str = "", limit: int = Query(default=30, ge=1, le=100),
                     member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(doc_svc.search_workspace, member_id, kind, _container(kind, container_id, member_id), q, limit)


@workspaces_router.get("/{kind}/{container_id}/state")
def get_state(kind: Kind, container_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(state_svc.get_state, member_id, kind, _container(kind, container_id, member_id))


class StateBody(BaseModel):
    state: dict


@workspaces_router.put("/{kind}/{container_id}/state")
def put_state(kind: Kind, container_id: str, body: StateBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(state_svc.put_state, member_id, kind, _container(kind, container_id, member_id), body.state)


@workspaces_router.post("/{kind}/{container_id}/folders", status_code=201)
def create_folder(kind: Kind, container_id: str, body: FolderCreate,
                  member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(doc_svc.create_folder, member_id, kind, _container(kind, container_id, member_id), body.path)


@workspaces_router.patch("/{kind}/{container_id}/folders")
def rename_folder(kind: Kind, container_id: str, body: FolderRename,
                  member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(doc_svc.rename_folder, member_id, kind, _container(kind, container_id, member_id),
                body.path, body.new_path)


@workspaces_router.delete("/{kind}/{container_id}/folders")
def delete_folder(kind: Kind, container_id: str, path: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(doc_svc.delete_folder, member_id, kind, _container(kind, container_id, member_id), path)


@workspaces_router.post("/duplicates")
def check_duplicates(body: DuplicateCheck, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(doc_svc.check_duplicates, member_id, body.hashes, body.kind, _container(body.kind, body.id, member_id))


@workspaces_router.get("/tags")
def tag_suggestions(prefix: str = "", limit: int = Query(default=20, ge=1, le=100),
                    member_id: str | None = Depends(resolve_member)) -> dict:
    return {"tags": _run(doc_svc.tag_suggestions, member_id, prefix, limit)}


# ── a document across workspaces ─────────────────────────────────────────────

@workspaces_router.get("/documents/{document_id}")
def document_places(document_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(doc_svc.document_places, member_id, document_id)


@workspaces_router.post("/documents/{document_id}/links", status_code=201)
def link_document(document_id: str, body: Target, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(doc_svc.link_document, member_id, document_id, body.kind, _container(body.kind, body.id, member_id),
                body.folder)


@workspaces_router.delete("/documents/{document_id}/links/{kind}/{container_id}")
def unlink_document(document_id: str, kind: Kind, container_id: str,
                    member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(doc_svc.unlink_document, member_id, document_id, kind, _container(kind, container_id, member_id))


@workspaces_router.post("/documents/{document_id}/move-home")
def move_home(document_id: str, body: Target, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(doc_svc.move_home, member_id, document_id, body.kind, _container(body.kind, body.id, member_id),
                body.folder)


@workspaces_router.post("/documents/{document_id}/copy", status_code=201)
def copy_document(document_id: str, body: CopyBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(doc_svc.copy_document, member_id, document_id, body.kind, _container(body.kind, body.id, member_id),
                body.folder, body.title)


@workspaces_router.patch("/documents/{document_id}/folder")
def place_in_folder(document_id: str, body: Target, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(doc_svc.place_in_folder, member_id, document_id, body.kind,
                _container(body.kind, body.id, member_id), body.folder)


@workspaces_router.post("/documents/{document_id}/tags")
def add_tag(document_id: str, body: TagBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(doc_svc.add_tag, member_id, document_id, body.tag)


@workspaces_router.delete("/documents/{document_id}/tags/{tag}")
def remove_tag(document_id: str, tag: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(doc_svc.remove_tag, member_id, document_id, tag)
