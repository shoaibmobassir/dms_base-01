"""What each person had open in a workspace (plan 22, W1.6): tabs, split and panel sizes.

Only ids are stored. On load, tabs whose document the member can no longer read are dropped, so a saved
layout never reveals a title it should not.
"""
from __future__ import annotations

import json
from typing import Any

from app.api.acl import doc_read
from app.firm import FirmError, guard, one
from app.workspaces import require_container, rows

MAX_TABS = 40


@guard
def get_state(conn, actor: str | None, kind: str, cid: str) -> dict:
    require_container(conn, actor, kind, cid, "read")
    if actor is None:
        return {"state": {}}
    row = one(conn, "SELECT state, updated_at FROM workbench_state WHERE member_id = %s AND scope_key = %s",
              (actor, f"{kind}:{cid}"))
    state: dict[str, Any] = dict(row["state"]) if row else {}
    doc_ids = sorted({t.get("documentId") for g in state.get("groups", []) for t in g.get("tabs", [])
                      if isinstance(t, dict) and t.get("documentId")})
    if doc_ids:
        readable = {r["document_id"] for r in rows(conn, f"""
            SELECT d.document_id FROM documents d LEFT JOIN permissions p ON p.matter_id = d.matter_id
            WHERE d.document_id = ANY(%(ids)s) AND d.archived_at IS NULL AND {doc_read('d')}""",
            {"ids": doc_ids, "member_id": actor})}
        for g in state.get("groups", []):
            g["tabs"] = [t for t in g.get("tabs", []) if not t.get("documentId") or t["documentId"] in readable]
    return {"state": state, "updated_at": row["updated_at"] if row else None}


@guard
def put_state(conn, actor: str | None, kind: str, cid: str, state: dict) -> dict:
    require_container(conn, actor, kind, cid, "read")
    if actor is None:
        return {"saved": False}
    groups = state.get("groups", [])
    if not isinstance(groups, list) or len(groups) > 2 or sum(len(g.get("tabs", [])) for g in groups) > MAX_TABS:
        raise FirmError(422, f"At most 2 editor groups and {MAX_TABS} tabs")
    body = json.dumps(state)
    if len(body) > 60000:
        raise FirmError(422, "Layout is too large")
    conn.execute(
        """INSERT INTO workbench_state (member_id, scope_key, state, updated_at) VALUES (%s, %s, %s::jsonb, now())
           ON CONFLICT (member_id, scope_key) DO UPDATE SET state = EXCLUDED.state, updated_at = now()""",
        (actor, f"{kind}:{cid}", body))
    conn.commit()
    return {"saved": True}
