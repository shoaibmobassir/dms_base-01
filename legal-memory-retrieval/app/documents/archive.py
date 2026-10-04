"""Archive a document: a soft delete. Nothing is erased; the document, its versions and history stay.

Archiving compiles an empty visibility list (migration 20261003d), so the document disappears from
lists, search and retrieval for everyone. People with manage access to the document archive it;
only a firm administrator (``users.manage``) sees the archive and restores from it.
"""
from __future__ import annotations

from typing import Any

from app import access
from app.audit import events as audit
from app.documents.editing import record_event


class ArchiveError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def _doc(conn, document_id: str) -> dict:
    row = conn.execute("SELECT document_id, matter_id, title, current_version_id, archived_at FROM documents WHERE document_id = %s",
                       (document_id,)).fetchone()
    if row is None:
        raise ArchiveError(404, "Document not found or access denied")
    return row


def archive_document(conn, member_id: str | None, document_id: str, reason: str) -> dict[str, Any]:
    reason = (reason or "").strip()
    if len(reason) < 3 or len(reason) > 500:
        raise ArchiveError(422, "Say why in a few words (at most 500 characters)")
    doc = _doc(conn, document_id)
    try:
        access.require_document_level(conn, member_id, document_id, "manage", via="archive")
    except access.AccessError as exc:
        raise ArchiveError(exc.status, "Document not found or access denied" if exc.status == 404
                           else "Only someone who manages this document can archive it") from exc
    if doc["archived_at"] is not None:
        raise ArchiveError(409, "Already archived")
    conn.execute("UPDATE documents SET archived_at = now(), archived_by = %s, archive_reason = %s WHERE document_id = %s",
                 (member_id, reason, document_id))
    record_event(conn, document_id, member_id, "archive", doc["current_version_id"], {"reason": reason})
    conn.commit()
    audit.record("document.archive", member_id=member_id, object_type="document", object_id=document_id,
                 matter_id=doc["matter_id"], detail={"reason": reason})
    return {"document_id": document_id, "archived": True}


def _require_admin(conn, member_id: str | None) -> None:
    try:
        access.require_permission(conn, member_id, "users.manage")
    except access.AccessError as exc:
        raise ArchiveError(exc.status, exc.detail) from exc


def restore_document(conn, member_id: str | None, document_id: str) -> dict[str, Any]:
    _require_admin(conn, member_id)
    doc = _doc(conn, document_id)
    if doc["archived_at"] is None:
        raise ArchiveError(409, "This document is not archived")
    conn.execute("UPDATE documents SET archived_at = NULL, archived_by = NULL, archive_reason = NULL WHERE document_id = %s", (document_id,))
    record_event(conn, document_id, member_id, "restore", doc["current_version_id"], {})
    conn.commit()
    audit.record("document.restore", member_id=member_id, object_type="document", object_id=document_id, matter_id=doc["matter_id"])
    return {"document_id": document_id, "archived": False}


def list_archived(conn, member_id: str | None) -> list[dict[str, Any]]:
    _require_admin(conn, member_id)
    return conn.execute(
        """SELECT d.document_id, d.title, d.matter_id, m.title AS matter_title, d.archived_at, d.archive_reason,
                  mem.name AS archived_by_name
           FROM documents d LEFT JOIN matters m ON m.matter_id = d.matter_id LEFT JOIN members mem ON mem.member_id = d.archived_by
           WHERE d.archived_at IS NOT NULL ORDER BY d.archived_at DESC LIMIT 200""").fetchall()
