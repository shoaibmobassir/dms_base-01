"""Workspaces (plan 22, W0): matters, projects and personal libraries over single-copy documents.

A document lives once and has one home (``documents.home_kind`` / ``home_id``, or ``matter_id`` for a matter);
other workspaces show it through ``document_links``. The home governs access (compiled in the database, see
migration ``20261007a_workspaces.sql``); a link never widens it.

Writes follow the firm write layer's rules (``app.firm``): access check, one transaction with a
``domain_events`` row, commit, audit.
"""
from __future__ import annotations

from typing import Any

from app import access
from app.firm import FirmError, one

KINDS = ("matter", "project", "library", "firm")


def rows(conn, sql: str, params: Any = ()) -> list[dict]:
    return list(conn.execute(sql, params).fetchall())


def clean_path(value: Any) -> str:
    """A folder path: segments joined by '/', no empty, '.' or '..' segments; '' is the workspace root."""
    if value is None:
        return ""
    parts = [p.strip() for p in str(value).replace("\\", "/").split("/")]
    parts = [p for p in parts if p]
    for p in parts:
        if p in (".", "..") or len(p) > 120:
            raise FirmError(422, f"Folder name '{p[:40]}' is not allowed")
    path = "/".join(parts)
    if len(path) > 500:
        raise FirmError(422, "Folder path is too long")
    return path


def check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise FirmError(422, f"Workspace kind must be one of {', '.join(KINDS)}")
    return kind


def require_container(conn, actor: str | None, kind: str, container_id: str, needed: str) -> str:
    """The actor's level on a workspace, at least ``needed``; unknown and invisible are both 404."""
    check_kind(kind)
    level = access.container_level(conn, actor, kind, container_id)
    if level == "none":
        raise FirmError(404, "Workspace not found or access denied")
    if access.LEVELS.index(level) < access.LEVELS.index(needed):
        raise FirmError(403, f"Requires {needed} access to this workspace")
    if kind == "project" and needed != "read":
        archived = one(conn, "SELECT archived_at FROM projects WHERE project_id = %s", (container_id,))
        if archived and archived["archived_at"] is not None:
            raise FirmError(409, "This project is archived; restore it first")
    return level


def require_document(conn, actor: str | None, document_id: str, needed: str, via: str) -> dict:
    try:
        return access.require_document_level(conn, actor, document_id.upper(), needed, via=via)
    except access.AccessError as exc:
        raise FirmError(exc.status, exc.detail) from exc


def container_label(conn, kind: str, container_id: str) -> str:
    if kind == "matter":
        row = one(conn, "SELECT matter_code, title FROM matters WHERE matter_id = %s", (container_id,))
        return f"{row['matter_code']} — {row['title']}" if row else container_id
    if kind == "project":
        row = one(conn, "SELECT title FROM projects WHERE project_id = %s", (container_id,))
        return row["title"] if row else container_id
    if kind == "firm":
        return "Firm templates"
    return "My library"


def home_of(doc: dict) -> tuple[str, str]:
    """(kind, id) of a document row's home."""
    if doc["home_kind"] == "matter":
        return "matter", doc["matter_id"]
    return doc["home_kind"], doc["home_id"]
