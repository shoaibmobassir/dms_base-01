"""Append-only audit stream: who did what, to which record, when, with what outcome.

Rows go to ``audit_events`` (hash-chained, UPDATE/DELETE rejected by triggers — see
migration 20260924f). Prompts are recorded because a firm must be able to answer
"who asked what about this matter"; answers are recorded as metadata (cited
documents, abstention), not text.

Recording never raises into the caller: a failed audit write is logged at ERROR
with the request id so operations can alert on it.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from psycopg.rows import dict_row

from app.db.connection import connect
from app.observability.request_id import current_client_ip, current_request_id

log = logging.getLogger(__name__)

MAX_TEXT = 4000  # cap free text (prompts) stored per event


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_TEXT:
        return value[:MAX_TEXT] + "…"
    return value


def record(
    action: str,
    *,
    member_id: str | None,
    outcome: str = "success",
    object_type: str | None = None,
    object_id: str | None = None,
    matter_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    payload = {k: _clip(v) for k, v in (detail or {}).items()}
    try:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events
                    (member_id, action, outcome, object_type, object_id, matter_id, request_id, ip, detail)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    member_id, action, outcome, object_type, object_id, matter_id,
                    current_request_id() or None, current_client_ip() or None,
                    json.dumps(payload, default=str),
                ),
            )
            conn.commit()
    except Exception:  # noqa: BLE001 — never break the request; alert on this log line
        log.error("AUDIT WRITE FAILED action=%s member=%s request_id=%s", action, member_id, current_request_id(), exc_info=True)


def matter_of_document(document_id: str) -> str | None:
    try:
        with connect() as conn:
            row = conn.execute("SELECT matter_id FROM documents WHERE document_id = %s", (document_id,)).fetchone()
        return row["matter_id"] if row else None
    except Exception:  # noqa: BLE001
        return None


def is_admin(member_id: str | None) -> bool:
    if not member_id:
        return False
    with connect() as conn:
        row = conn.execute("SELECT is_admin FROM members WHERE member_id = %s", (member_id,)).fetchone()
    return bool(row and row["is_admin"])


def verify_chain(conn=None) -> dict[str, Any]:
    """Recompute every hash in SQL (same expression as the insert trigger) and report the
    first row whose hash, link to its predecessor, or sequence number is wrong."""
    sql = """
        WITH c AS (
            SELECT seq, hash, prev_hash,
                   lag(hash) OVER (ORDER BY seq) AS expected_prev,
                   row_number() OVER (ORDER BY seq) AS rn,
                   encode(sha256(convert_to(
                       COALESCE(lag(hash) OVER (ORDER BY seq), '') || '|' || seq || '|' ||
                       to_char(occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US') || '|' ||
                       COALESCE(member_id, '') || '|' || action || '|' || outcome || '|' ||
                       COALESCE(object_type, '') || '|' || COALESCE(object_id, '') || '|' ||
                       COALESCE(matter_id, '') || '|' || detail::text, 'UTF8')), 'hex') AS expected_hash
            FROM audit_events
        )
        SELECT
            (SELECT count(*) FROM c) AS events,
            (SELECT min(seq) FROM c
              WHERE hash <> expected_hash
                 OR prev_hash IS DISTINCT FROM expected_prev
                 OR seq <> rn) AS first_broken_seq
    """
    if conn is None:
        with connect() as own:
            return verify_chain(own)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql)
        row = cur.fetchone()
    return {"events": row["events"], "intact": row["first_broken_seq"] is None, "first_broken_seq": row["first_broken_seq"]}
