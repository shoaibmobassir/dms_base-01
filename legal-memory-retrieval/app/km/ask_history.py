"""Questions a member has asked Ask the Firm, newest first.

A personal list so the Ask page can offer "recent questions" across reloads.
Rows hold only the question and its scope label; the answer is recomputed on
open, so the matter ACL at read time still decides what the member sees.
"""
from __future__ import annotations

import uuid
from typing import Any

MAX_ROWS = 200  # per member; older rows are trimmed on write


def record(conn, member_id: str | None, query: str, scope: dict | None) -> None:
    """Add a question (or move an identical one to the top)."""
    q = (query or "").strip()
    if not member_id or not q:
        return
    scope_value = (scope or {}).get("value") or None
    scope_type = (scope or {}).get("type") if scope_value else None
    conn.execute(
        """
        INSERT INTO ask_history (id, member_id, query, scope, scope_type)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (member_id, query, coalesce(scope, ''), coalesce(scope_type, ''))
        DO UPDATE SET asked_at = now()
        """,
        (str(uuid.uuid4()), member_id, q[:2000], scope_value, scope_type),
    )
    conn.execute(
        """
        DELETE FROM ask_history WHERE member_id = %s AND id NOT IN (
            SELECT id FROM ask_history WHERE member_id = %s ORDER BY asked_at DESC LIMIT %s
        )
        """,
        (member_id, member_id, MAX_ROWS),
    )
    conn.commit()


def recent(conn, member_id: str | None, limit: int = 30) -> list[dict[str, Any]]:
    if not member_id:
        return []
    rows = conn.execute(
        """
        SELECT id, query, scope, scope_type, asked_at FROM ask_history
        WHERE member_id = %s ORDER BY asked_at DESC LIMIT %s
        """,
        (member_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def remove(conn, member_id: str | None, entry_id: str | None = None) -> int:
    """Delete one question, or all of the member's questions when ``entry_id`` is None."""
    if not member_id:
        return 0
    if entry_id:
        cur = conn.execute("DELETE FROM ask_history WHERE member_id = %s AND id = %s", (member_id, entry_id))
    else:
        cur = conn.execute("DELETE FROM ask_history WHERE member_id = %s", (member_id,))
    conn.commit()
    return cur.rowcount
