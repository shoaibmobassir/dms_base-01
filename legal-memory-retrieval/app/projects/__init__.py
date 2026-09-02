"""Project activity recording helper.

Records audit events for all project mutations.
"""
from __future__ import annotations

import json
from psycopg.rows import dict_row

from app.db.connection import connect


def record_activity(
    project_id: str,
    action: str,
    *,
    actor_id: str | None = None,
    target_id: str | None = None,
    target_title: str | None = None,
    metadata: dict | None = None,
    conn=None,
    cur=None,
) -> None:
    """Insert an activity row. Accepts an optional existing connection/cursor."""
    sql = """
        INSERT INTO project_activity (
            project_id, action, actor_id, target_id, target_title, metadata
        ) VALUES (
            %(project_id)s, %(action)s, %(actor_id)s,
            %(target_id)s, %(target_title)s, %(metadata)s::jsonb
        )
    """
    params = {
        "project_id": project_id,
        "action": action,
        "actor_id": actor_id,
        "target_id": target_id,
        "target_title": target_title,
        "metadata": json.dumps(metadata or {}),
    }
    if cur:
        cur.execute(sql, params)
    elif conn:
        with conn.cursor() as c:
            c.execute(sql, params)
    else:
        with connect() as conn2:
            with conn2.cursor() as c:
                c.execute(sql, params)
            conn2.commit()
