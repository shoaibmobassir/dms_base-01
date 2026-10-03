"""Saved Ask the Firm answers: full grounded payload per member + question + scope.

The Ask page reloads these instead of re-running the model. Every read re-checks
that the member can still see every matter cited in the panel / sources.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.km.scope import ACL_SQL, _fetch

logger = logging.getLogger(__name__)

# Keys written into the row and restored into the Ask response.
_RESULT_KEYS = (
    "answer", "key_finding", "status", "provider", "model", "abstained", "reason",
    "citations", "span_citations", "panel", "matter_cards", "sources", "people",
    "resolved_scope", "grounding", "structured_citations", "matchedMatters", "tags",
    "docket", "docket_copies", "latency_ms", "service",
)


def _scope_parts(scope: dict | None) -> tuple[str | None, str | None]:
    scope_value = (scope or {}).get("value") or None
    scope_type = (scope or {}).get("type") if scope_value else None
    return scope_value, scope_type


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def cited_matter_ids(payload: dict[str, Any]) -> set[str]:
    """Matter ids the saved answer depends on (panel + cards + sources)."""
    ids: set[str] = set()
    for m in (payload.get("panel") or {}).get("matters") or []:
        mid = m.get("matter_id")
        if mid:
            ids.add(str(mid))
    for c in payload.get("matter_cards") or []:
        mid = c.get("matter_id")
        if mid:
            ids.add(str(mid))
    for s in payload.get("sources") or []:
        mid = s.get("matter_id")
        if mid:
            ids.add(str(mid))
    for mid in (payload.get("resolved_scope") or {}).get("matter_ids") or []:
        ids.add(str(mid))
    return ids


def member_can_see(conn, member_id: str | None, matter_ids: set[str]) -> bool:
    """True when every matter is still visible under the ethical-wall ACL."""
    if not matter_ids:
        return True
    if not member_id:
        return False
    rows = _fetch(
        conn,
        f"""
        SELECT m.matter_id FROM matters m
        JOIN permissions p ON p.matter_id = m.matter_id
        WHERE m.matter_id = ANY(%(ids)s) AND {ACL_SQL}
        """,
        {"member_id": member_id, "ids": list(matter_ids)},
    )
    return {r["matter_id"] for r in rows} >= matter_ids


def save(conn, member_id: str | None, query: str, scope: dict | None, result: dict[str, Any]) -> str | None:
    """Upsert the grounded answer for this member/question/scope. Returns the row id."""
    q = (query or "").strip()
    if not member_id or not q:
        return None
    scope_value, scope_type = _scope_parts(scope)
    payload = {k: result.get(k) for k in _RESULT_KEYS if k in result}
    row_id = str(uuid.uuid4())
    row = conn.execute(
        """
        INSERT INTO ask_answers (
            id, member_id, query, scope, scope_type, asked_at, answered_at,
            answer, key_finding, status, provider, model, abstained, reason,
            citations, span_citations, panel, matter_cards, sources, people,
            resolved_scope, grounding, payload
        ) VALUES (
            %s, %s, %s, %s, %s, now(), now(),
            %s, %s, %s, %s, %s, %s, %s,
            %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
            %s::jsonb, %s::jsonb, %s::jsonb
        )
        ON CONFLICT (member_id, query, coalesce(scope, ''), coalesce(scope_type, ''))
        DO UPDATE SET
            answered_at = now(),
            asked_at = now(),
            answer = EXCLUDED.answer,
            key_finding = EXCLUDED.key_finding,
            status = EXCLUDED.status,
            provider = EXCLUDED.provider,
            model = EXCLUDED.model,
            abstained = EXCLUDED.abstained,
            reason = EXCLUDED.reason,
            citations = EXCLUDED.citations,
            span_citations = EXCLUDED.span_citations,
            panel = EXCLUDED.panel,
            matter_cards = EXCLUDED.matter_cards,
            sources = EXCLUDED.sources,
            people = EXCLUDED.people,
            resolved_scope = EXCLUDED.resolved_scope,
            grounding = EXCLUDED.grounding,
            payload = EXCLUDED.payload
        RETURNING id
        """,
        (
            row_id, member_id, q[:2000], scope_value, scope_type,
            result.get("answer") or "", result.get("key_finding") or "",
            result.get("status"), result.get("provider"), result.get("model"),
            bool(result.get("abstained")), result.get("reason"),
            _json(result.get("citations") or []),
            _json(result.get("span_citations") or []),
            _json(result.get("panel")),
            _json(result.get("matter_cards") or []),
            _json(result.get("sources") or []),
            _json(result.get("people") or []),
            _json(result.get("resolved_scope")),
            _json(result.get("grounding")),
            _json(payload),
        ),
    ).fetchone()
    conn.commit()
    return str(row["id"]) if row else row_id


def _row_to_payload(conn, member_id: str | None, row: dict) -> dict[str, Any] | None:
    payload = dict(row["payload"] or {})
    for key in (
        "answer", "key_finding", "status", "provider", "model", "abstained", "reason",
        "citations", "span_citations", "panel", "matter_cards", "sources", "people",
        "resolved_scope", "grounding",
    ):
        if key not in payload or payload.get(key) is None:
            payload[key] = row[key]
    matters = cited_matter_ids(payload)
    if not member_can_see(conn, member_id, matters):
        conn.execute("DELETE FROM ask_answers WHERE id = %s", (row["id"],))
        conn.commit()
        return None
    payload["query"] = row.get("query") or payload.get("query")
    payload["scope"] = row.get("scope")
    payload["scope_type"] = row.get("scope_type")
    payload["saved"] = True
    payload["saved_id"] = row["id"]
    payload["answered_at"] = row["answered_at"].isoformat() if row.get("answered_at") else None
    payload["service"] = payload.get("service") or "answers"
    payload["hits"] = payload.get("hits") or []
    return payload


_SELECT = """
    SELECT id, query, scope, scope_type, payload, panel, matter_cards, sources, resolved_scope,
           answer, key_finding, status, provider, model, abstained, reason,
           citations, span_citations, people, grounding, answered_at
    FROM ask_answers
"""


def load(conn, member_id: str | None, query: str, scope: dict | None) -> dict[str, Any] | None:
    """Return the stored Ask payload, or None if missing / no longer ACL-visible."""
    q = (query or "").strip()
    if not member_id or not q:
        return None
    scope_value, scope_type = _scope_parts(scope)
    row = conn.execute(
        _SELECT + """
        WHERE member_id = %s AND query = %s
          AND coalesce(scope, '') = coalesce(%s, '')
          AND coalesce(scope_type, '') = coalesce(%s, '')
        """,
        (member_id, q, scope_value, scope_type),
    ).fetchone()
    if not row:
        return None
    return _row_to_payload(conn, member_id, dict(row))


def load_by_id(conn, member_id: str | None, answer_id: str) -> dict[str, Any] | None:
    """Load one saved answer by id (Assistant-style reopen). Owner + ACL checked."""
    if not member_id or not answer_id:
        return None
    row = conn.execute(
        _SELECT + " WHERE id = %s AND member_id = %s",
        (answer_id, member_id),
    ).fetchone()
    if not row:
        return None
    return _row_to_payload(conn, member_id, dict(row))


def recent(conn, member_id: str | None, limit: int = 30) -> list[dict[str, Any]]:
    """Recent saved answers for the sidebar — id is the reopen key, like a chat session."""
    if not member_id:
        return []
    rows = conn.execute(
        """
        SELECT id, query, scope, scope_type, answered_at AS asked_at
        FROM ask_answers
        WHERE member_id = %s
        ORDER BY answered_at DESC
        LIMIT %s
        """,
        (member_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def drop(conn, member_id: str | None, query: str, scope: dict | None) -> int:
    """Delete one saved answer (used before a forced refresh)."""
    q = (query or "").strip()
    if not member_id or not q:
        return 0
    scope_value, scope_type = _scope_parts(scope)
    cur = conn.execute(
        """
        DELETE FROM ask_answers
        WHERE member_id = %s AND query = %s
          AND coalesce(scope, '') = coalesce(%s, '')
          AND coalesce(scope_type, '') = coalesce(%s, '')
        """,
        (member_id, q, scope_value, scope_type),
    )
    conn.commit()
    return cur.rowcount


def drop_by_id(conn, member_id: str | None, answer_id: str) -> int:
    if not member_id or not answer_id:
        return 0
    cur = conn.execute(
        "DELETE FROM ask_answers WHERE member_id = %s AND id = %s",
        (member_id, answer_id),
    )
    conn.commit()
    return cur.rowcount
