"""Job tracking for the ingest pipeline — create, update, resume jobs."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import psycopg


def create_job(conn: psycopg.Connection, source_root: str, total: int, workers: int = 1) -> str:
    """Create a new ingest job. Returns job_id."""
    job_id = f"JOB-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO ingest_jobs (job_id, source_root, status, total_items, workers, started_at)
        VALUES (%s, %s, 'running', %s, %s, %s)
        """,
        (job_id, source_root, total, workers, datetime.now(timezone.utc)),
    )
    conn.commit()
    return job_id


def register_items(conn: psycopg.Connection, job_id: str, source_uris: list[str]) -> None:
    """Register items for a job (idempotent via ON CONFLICT)."""
    with conn.pipeline():
        for uri in source_uris:
            conn.execute(
                """
                INSERT INTO ingest_items (job_id, source_uri, status)
                VALUES (%s, %s, 'pending')
                ON CONFLICT (job_id, source_uri) DO NOTHING
                """,
                (job_id, uri),
            )
    conn.commit()


def mark_item(conn: psycopg.Connection, job_id: str, source_uri: str,
              status: str, document_id: str | None = None,
              sha: str | None = None, error: str | None = None) -> None:
    """Update item status: indexed, failed, or skipped."""
    conn.execute(
        """
        UPDATE ingest_items
        SET status = %s, document_id = %s, content_sha256 = %s,
            error = %s, processed_at = %s
        WHERE job_id = %s AND source_uri = %s
        """,
        (status, document_id, sha, error, datetime.now(timezone.utc), job_id, source_uri),
    )
    # Update job counters
    field_map = {"indexed": "indexed_items", "failed": "failed_items", "skipped": "skipped_items"}
    col = field_map.get(status)
    if col:
        conn.execute(
            f"UPDATE ingest_jobs SET {col} = {col} + 1 WHERE job_id = %s",
            (job_id,),
        )
    conn.commit()


def complete_job(conn: psycopg.Connection, job_id: str, error: str | None = None) -> None:
    """Mark job as completed or failed."""
    status = "failed" if error else "completed"
    conn.execute(
        """
        UPDATE ingest_jobs
        SET status = %s, finished_at = %s, error_summary = %s
        WHERE job_id = %s
        """,
        (status, datetime.now(timezone.utc), error, job_id),
    )
    conn.commit()


def get_pending_items(conn: psycopg.Connection, job_id: str) -> list[str]:
    """Get source_uris of pending or failed items (for resume)."""
    rows = conn.execute(
        "SELECT source_uri FROM ingest_items WHERE job_id = %s AND status IN ('pending', 'failed')",
        (job_id,),
    ).fetchall()
    return [r["source_uri"] for r in rows]


def job_status(conn: psycopg.Connection, job_id: str) -> dict | None:
    """Get full job status."""
    row = conn.execute(
        "SELECT * FROM ingest_jobs WHERE job_id = %s",
        (job_id,),
    ).fetchone()
    return dict(row) if row else None
