"""Incremental sync engine — provider-agnostic change processing."""
from __future__ import annotations

import logging
import time
from typing import Any

from app.config import settings
from app.sources.factory import get_connector
from app.sources.models import ChangeType, Scope
from app.sources import store
from app.sources.queue import (
    QUEUE_DOWNLOAD,
    QUEUE_PERMISSIONS,
    SourceJob,
    backoff_seconds,
    drain_inline,
    enqueue,
)
from app.sources.process import process_download

log = logging.getLogger(__name__)


def _matter_id(connection) -> str | None:
    return (connection.config or {}).get("matter_id")


def _handle_change(
    connection_id: str,
    provider: str,
    matter_id: str,
    change,
    *,
    process_inline: bool,
) -> dict[str, Any]:
    pfid = change.provider_file_id

    if change.change_type == ChangeType.deleted:
        row = store.get_source_file_by_provider(connection_id, pfid)
        if row:
            if row.get("document_id"):
                store.soft_delete_indexed_document(row["document_id"])
            store.mark_source_file(
                row["source_file_id"], status="deleted", deleted=True
            )
        return {"action": "deleted", "provider_file_id": pfid}

    if change.metadata is None:
        return {"action": "skipped", "reason": "no_metadata", "provider_file_id": pfid}

    if change.metadata.is_folder:
        store.upsert_source_file(
            connection_id=connection_id,
            provider=provider,
            matter_id=matter_id,
            metadata=change.metadata,
            status="ignored",
        )
        return {"action": "ignored_folder", "provider_file_id": pfid}

    existing = store.get_source_file_by_provider(connection_id, pfid)
    sfid = store.upsert_source_file(
        connection_id=connection_id,
        provider=provider,
        matter_id=matter_id,
        metadata=change.metadata,
        status="discovered",
    )

    if change.change_type == ChangeType.permission_only:
        job = SourceJob(
            job_type=QUEUE_PERMISSIONS,
            connection_id=connection_id,
            payload={"provider_file_id": pfid, "source_file_id": sfid},
        )
        if process_inline:
            _refresh_permissions(job)
        else:
            enqueue(job)
        return {"action": "permissions", "provider_file_id": pfid}

    # Hash / etag no-op: already indexed with same content fingerprint
    if (
        existing
        and existing.get("status") == "indexed"
        and change.metadata.content_hash
        and existing.get("content_hash") == change.metadata.content_hash
    ):
        store.mark_source_file(
            sfid,
            status="skipped_unchanged",
            content_hash=change.metadata.content_hash,
            etag=change.metadata.etag,
            document_id=existing.get("document_id"),
        )
        return {
            "action": "skipped_unchanged",
            "provider_file_id": pfid,
            "source_file_id": sfid,
        }

    job = SourceJob(
        job_type=QUEUE_DOWNLOAD,
        connection_id=connection_id,
        payload={"provider_file_id": pfid},
    )
    if process_inline:
        return {
            "action": "downloaded",
            "provider_file_id": pfid,
            "result": process_download(connection_id, pfid),
        }
    enqueue(job)
    return {"action": "enqueued_download", "provider_file_id": pfid}


def _refresh_permissions(job: SourceJob) -> None:
    connection = store.get_connection(job.connection_id)
    if not connection:
        return
    pfid = job.payload["provider_file_id"]
    sfid = job.payload.get("source_file_id")
    connector = get_connector(connection)
    connector.authenticate()
    perms = connector.get_permissions(pfid)
    if sfid:
        store.replace_permissions(sfid, perms)


def _handle_download_job(job: SourceJob) -> None:
    pfid = job.payload["provider_file_id"]
    try:
        process_download(job.connection_id, pfid)
    except Exception as exc:
        log.exception("download job failed")
        max_retries = settings.sources_sync_max_retries
        if job.attempt + 1 < max_retries:
            time.sleep(backoff_seconds(job.attempt))
            enqueue(
                SourceJob(
                    job_type=QUEUE_DOWNLOAD,
                    connection_id=job.connection_id,
                    payload=job.payload,
                    attempt=job.attempt + 1,
                )
            )
        else:
            row = store.get_source_file_by_provider(job.connection_id, pfid)
            if row:
                store.mark_source_file(
                    row["source_file_id"], status="failed", error=str(exc)
                )


def run_sync(
    connection_id: str,
    *,
    scope_key: str = "default",
    process_inline: bool | None = None,
) -> dict[str, Any]:
    """Advance cursor and process changes for one connection.

    When ``process_inline`` is True (default from settings), downloads run
    immediately; otherwise jobs are enqueued for workers.
    """
    if not settings.sources_sync_enabled:
        return {"status": "disabled", "error": "SOURCES_SYNC_ENABLED=false"}

    inline = (
        settings.sources_queue_inline if process_inline is None else process_inline
    )
    connection = store.get_connection(connection_id)
    if not connection:
        return {"status": "failed", "error": "connection_not_found"}
    if connection.status != "active":
        return {"status": "failed", "error": "connection_not_active"}

    matter_id = _matter_id(connection)
    if not matter_id:
        return {"status": "failed", "error": "matter_id_missing"}

    state = store.get_sync_state(connection_id, scope_key)
    cursor = state.cursor if state else None

    store.update_sync_state(
        connection_id, scope_key=scope_key, sync_status="running"
    )

    actions: list[dict] = []
    try:
        connector = get_connector(connection)
        connector.authenticate()
        scope = Scope(key=scope_key)
        page = connector.get_changes(cursor, scope)

        while True:
            for change in page.items:
                actions.append(
                    _handle_change(
                        connection_id,
                        connection.provider,
                        matter_id,
                        change,
                        process_inline=inline,
                    )
                )
            store.update_sync_state(
                connection_id,
                scope_key=scope_key,
                cursor=page.next_cursor,
                cursor_kind=page.cursor_kind,
                sync_status="running",
            )
            if page.done:
                break
            page = connector.get_changes(page.next_cursor, scope)

        if not inline:
            drain_inline(
                {
                    QUEUE_DOWNLOAD: _handle_download_job,
                    QUEUE_PERMISSIONS: _refresh_permissions,
                }
            )

        store.update_sync_state(
            connection_id,
            scope_key=scope_key,
            sync_status="idle",
            mark_success=True,
        )
        return {
            "status": "ok",
            "connection_id": connection_id,
            "cursor": page.next_cursor,
            "actions": actions,
            "change_count": len(actions),
        }
    except Exception as exc:
        log.exception("sync failed for %s", connection_id)
        failures = (state.consecutive_failures if state else 0) + 1
        store.update_sync_state(
            connection_id,
            scope_key=scope_key,
            sync_status="error" if failures < settings.sources_sync_max_retries else "backoff",
            error_code="sync_error",
            error_message=str(exc),
            consecutive_failures=failures,
        )
        return {
            "status": "failed",
            "connection_id": connection_id,
            "error": str(exc),
            "consecutive_failures": failures,
            "backoff_seconds": backoff_seconds(failures),
            "actions": actions,
        }
