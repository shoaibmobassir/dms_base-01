"""
Chat store: PostgreSQL-backed CRUD for chat sessions and messages.
Clean-room independent implementation for FirmOS legal assistant chatbot.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.chat.models import (
    ChatMessage,
    ChatSession,
    ChatSessionCreate,
    ChatSessionPatch,
    FileAttachment,
    MessageRole,
    SessionStatus,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _gen_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

def create_session(conn, req: ChatSessionCreate) -> ChatSession:
    """Create a new chat session."""
    session_id = _gen_id()
    now = _now_utc()
    conn.execute(
        """
        INSERT INTO chat_sessions (id, title, matter_id, model, member_id, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (session_id, req.title, req.matter_id, req.model, req.member_id, "active", now, now),
    )
    conn.commit()
    return ChatSession(
        id=session_id,
        title=req.title,
        matter_id=req.matter_id,
        model=req.model,
        member_id=req.member_id,
        status=SessionStatus.active,
        created_at=now,
        updated_at=now,
    )


def get_session(conn, session_id: str) -> ChatSession | None:
    """Fetch a single chat session by ID."""
    row = conn.execute(
        "SELECT * FROM chat_sessions WHERE id = %s", (session_id,)
    ).fetchone()
    if not row:
        return None
    return _row_to_session(row)


def list_sessions(
    conn,
    member_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ChatSession]:
    """List chat sessions, optionally filtered by member_id, newest first."""
    if member_id:
        rows = conn.execute(
            """
            SELECT * FROM chat_sessions
            WHERE member_id = %s AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT %s OFFSET %s
            """,
            (member_id, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM chat_sessions
            WHERE status = 'active'
            ORDER BY updated_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        ).fetchall()
    return [_row_to_session(r) for r in rows]


def patch_session(conn, session_id: str, patch: ChatSessionPatch) -> ChatSession | None:
    """Update mutable fields on a chat session."""
    existing = get_session(conn, session_id)
    if not existing:
        return None
    updates: dict[str, Any] = {}
    if patch.title is not None:
        updates["title"] = patch.title
    if patch.model is not None:
        updates["model"] = patch.model
    if patch.status is not None:
        updates["status"] = patch.status.value
    if not updates:
        return existing
    updates["updated_at"] = _now_utc()
    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [session_id]
    conn.execute(
        f"UPDATE chat_sessions SET {set_clause} WHERE id = %s",  # noqa: S608
        values,
    )
    conn.commit()
    return get_session(conn, session_id)


def delete_session(conn, session_id: str) -> bool:
    """Soft-delete a session by setting status to 'archived'."""
    result = conn.execute(
        "UPDATE chat_sessions SET status = 'archived', updated_at = %s WHERE id = %s",
        (_now_utc(), session_id),
    )
    conn.commit()
    return result.rowcount > 0


# ---------------------------------------------------------------------------
# Message CRUD
# ---------------------------------------------------------------------------

def append_message(
    conn,
    session_id: str,
    role: MessageRole,
    content: str,
    *,
    files: list[FileAttachment] | None = None,
    events: list[dict[str, Any]] | None = None,
    citations: list[dict[str, Any]] | None = None,
    model: str | None = None,
) -> ChatMessage:
    """Append a new message to a chat session."""
    msg_id = _gen_id()
    now = _now_utc()
    files_json = json.dumps([f.model_dump() for f in files]) if files else None
    events_json = json.dumps(events) if events else None
    citations_json = json.dumps(citations) if citations else None
    conn.execute(
        """
        INSERT INTO chat_messages (id, session_id, role, content, files, events, citations, model, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (msg_id, session_id, role.value, content, files_json, events_json, citations_json, model, now),
    )
    # Touch session updated_at
    conn.execute(
        "UPDATE chat_sessions SET updated_at = %s WHERE id = %s",
        (now, session_id),
    )
    conn.commit()
    return ChatMessage(
        id=msg_id,
        session_id=session_id,
        role=role,
        content=content,
        files=files,
        events=events,
        citations=citations,
        model=model,
        created_at=now,
    )


def update_assistant_message(
    conn,
    message_id: str,
    content: str,
    *,
    events: list[dict[str, Any]] | None = None,
    citations: list[dict[str, Any]] | None = None,
) -> None:
    """Update a reserved assistant message with final content."""
    events_json = json.dumps(events) if events else None
    citations_json = json.dumps(citations) if citations else None
    conn.execute(
        """
        UPDATE chat_messages SET content = %s, events = %s, citations = %s
        WHERE id = %s
        """,
        (content, events_json, citations_json, message_id),
    )
    conn.commit()


def get_message(conn, session_id: str, message_id: str) -> ChatMessage | None:
    """One message of a session, or None."""
    row = conn.execute(
        "SELECT * FROM chat_messages WHERE id = %s AND session_id = %s",
        (message_id, session_id),
    ).fetchone()
    return _row_to_message(row) if row else None


def set_message_events(conn, message_id: str, events: list[dict[str, Any]]) -> None:
    """Replace a message's stored events (used when the lawyer accepts or rejects an edit)."""
    conn.execute(
        "UPDATE chat_messages SET events = %s WHERE id = %s",
        (json.dumps(events) if events else None, message_id),
    )
    conn.commit()


def get_messages(conn, session_id: str) -> list[ChatMessage]:
    """Fetch all messages for a session, in chronological order."""
    rows = conn.execute(
        """
        SELECT * FROM chat_messages
        WHERE session_id = %s
        ORDER BY created_at ASC
        """,
        (session_id,),
    ).fetchall()
    return [_row_to_message(r) for r in rows]


# ---------------------------------------------------------------------------
# Row mappers
# ---------------------------------------------------------------------------

def _row_to_session(row: dict) -> ChatSession:
    return ChatSession(
        id=row["id"],
        title=row.get("title"),
        matter_id=row.get("matter_id"),
        model=row.get("model"),
        member_id=row.get("member_id"),
        status=SessionStatus(row.get("status", "active")),
        created_at=row.get("created_at", _now_utc()),
        updated_at=row.get("updated_at", _now_utc()),
    )


def _row_to_message(row: dict) -> ChatMessage:
    files_raw = row.get("files")
    files = None
    if files_raw:
        parsed = json.loads(files_raw) if isinstance(files_raw, str) else files_raw
        files = [FileAttachment(**f) for f in parsed]
    events_raw = row.get("events")
    events = None
    if events_raw:
        events = json.loads(events_raw) if isinstance(events_raw, str) else events_raw
    citations_raw = row.get("citations")
    citations = None
    if citations_raw:
        citations = json.loads(citations_raw) if isinstance(citations_raw, str) else citations_raw
    return ChatMessage(
        id=row["id"],
        session_id=row["session_id"],
        role=MessageRole(row["role"]),
        content=row.get("content", ""),
        files=files,
        events=events,
        citations=citations,
        model=row.get("model"),
        created_at=row.get("created_at", _now_utc()),
    )
