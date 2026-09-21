"""Postgres CRUD for source connections, sync state, and file inventory."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.db.connection import connect
from app.sources.models import (
    ConnectionRecord,
    FileMetadata,
    Permission,
    SyncStateRecord,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def create_connection(
    *,
    organization_id: str,
    provider: str,
    matter_id: str,
    created_by_member_id: str | None = None,
    provider_account_id: str | None = None,
    display_name: str | None = None,
    scopes: list[str] | None = None,
    encrypted_access_token: str | None = None,
    encrypted_refresh_token: str | None = None,
    extra_config: dict[str, Any] | None = None,
) -> ConnectionRecord:
    connection_id = _gen_id("SRC")
    config = {"matter_id": matter_id, **(extra_config or {})}
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO source_connections (
                    connection_id, organization_id, created_by_member_id,
                    provider, provider_account_id, display_name, scopes,
                    encrypted_access_token, encrypted_refresh_token,
                    status, config, created_at, updated_at
                ) VALUES (
                    %(cid)s, %(oid)s, %(mid)s,
                    %(prov)s, %(paid)s, %(dn)s, %(scopes)s,
                    %(at)s, %(rt)s,
                    'active', %(cfg)s, %(ts)s, %(ts)s
                )
                """,
                {
                    "cid": connection_id,
                    "oid": organization_id,
                    "mid": created_by_member_id,
                    "prov": provider,
                    "paid": provider_account_id,
                    "dn": display_name,
                    "scopes": scopes or [],
                    "at": encrypted_access_token,
                    "rt": encrypted_refresh_token,
                    "cfg": Json(config),
                    "ts": _now(),
                },
            )
            cur.execute(
                """
                INSERT INTO source_sync_state (connection_id, scope_key, sync_status)
                VALUES (%(cid)s, 'default', 'idle')
                ON CONFLICT DO NOTHING
                """,
                {"cid": connection_id},
            )
            conn.commit()
    return get_connection(connection_id)  # type: ignore[return-value]


def get_connection(connection_id: str) -> ConnectionRecord | None:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM source_connections WHERE connection_id = %(cid)s",
                {"cid": connection_id},
            )
            row = cur.fetchone()
    if not row:
        return None
    config = row["config"]
    if isinstance(config, str):
        config = json.loads(config)
    return ConnectionRecord(
        connection_id=row["connection_id"],
        organization_id=row["organization_id"],
        provider=row["provider"],
        provider_account_id=row["provider_account_id"],
        display_name=row["display_name"],
        status=row["status"],
        config=config or {},
        created_by_member_id=row.get("created_by_member_id"),
        encrypted_access_token=row.get("encrypted_access_token"),
        encrypted_refresh_token=row.get("encrypted_refresh_token"),
    )


def list_connections(organization_id: str | None = None) -> list[dict]:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if organization_id:
                cur.execute(
                    """
                    SELECT c.*, s.sync_status, s.last_sync_at, s.last_success_at,
                           s.cursor, s.error_message, s.consecutive_failures
                    FROM source_connections c
                    LEFT JOIN source_sync_state s
                      ON s.connection_id = c.connection_id AND s.scope_key = 'default'
                    WHERE c.organization_id = %(oid)s
                    ORDER BY c.created_at DESC
                    """,
                    {"oid": organization_id},
                )
            else:
                cur.execute(
                    """
                    SELECT c.*, s.sync_status, s.last_sync_at, s.last_success_at,
                           s.cursor, s.error_message, s.consecutive_failures
                    FROM source_connections c
                    LEFT JOIN source_sync_state s
                      ON s.connection_id = c.connection_id AND s.scope_key = 'default'
                    ORDER BY c.created_at DESC
                    """
                )
            return list(cur.fetchall())


def get_sync_state(
    connection_id: str, scope_key: str = "default"
) -> SyncStateRecord | None:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM source_sync_state
                WHERE connection_id = %(cid)s AND scope_key = %(sk)s
                """,
                {"cid": connection_id, "sk": scope_key},
            )
            row = cur.fetchone()
    if not row:
        return None
    return SyncStateRecord(
        connection_id=row["connection_id"],
        scope_key=row["scope_key"],
        cursor=row["cursor"],
        cursor_kind=row["cursor_kind"],
        sync_status=row["sync_status"],
        consecutive_failures=row["consecutive_failures"] or 0,
        error_message=row.get("error_message"),
    )


def update_sync_state(
    connection_id: str,
    *,
    scope_key: str = "default",
    cursor: str | None = None,
    cursor_kind: str | None = None,
    sync_status: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    consecutive_failures: int | None = None,
    mark_success: bool = False,
) -> None:
    sets = ["last_sync_at = %(ts)s"]
    params: dict[str, Any] = {
        "cid": connection_id,
        "sk": scope_key,
        "ts": _now(),
    }
    if cursor is not None:
        sets.append("cursor = %(cursor)s")
        params["cursor"] = cursor
    if cursor_kind is not None:
        sets.append("cursor_kind = %(ck)s")
        params["ck"] = cursor_kind
    if sync_status is not None:
        sets.append("sync_status = %(ss)s")
        params["ss"] = sync_status
    if error_code is not None:
        sets.append("error_code = %(ec)s")
        params["ec"] = error_code
    if error_message is not None:
        sets.append("error_message = %(em)s")
        params["em"] = error_message
    if consecutive_failures is not None:
        sets.append("consecutive_failures = %(cf)s")
        params["cf"] = consecutive_failures
    if mark_success:
        sets.append("last_success_at = %(ts)s")
        sets.append("error_code = NULL")
        sets.append("error_message = NULL")
        sets.append("consecutive_failures = 0")

    sql = f"""
        INSERT INTO source_sync_state (connection_id, scope_key, sync_status)
        VALUES (%(cid)s, %(sk)s, 'idle')
        ON CONFLICT (connection_id, scope_key) DO UPDATE SET
            {', '.join(sets)}
    """
    # ON CONFLICT DO UPDATE needs the SET columns only — rewrite cleanly:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO source_sync_state (connection_id, scope_key, sync_status)
                VALUES (%(cid)s, %(sk)s, 'idle')
                ON CONFLICT (connection_id, scope_key) DO NOTHING
                """,
                {"cid": connection_id, "sk": scope_key},
            )
            cur.execute(
                f"""
                UPDATE source_sync_state
                SET {', '.join(sets)}
                WHERE connection_id = %(cid)s AND scope_key = %(sk)s
                """,
                params,
            )
            conn.commit()


def upsert_source_file(
    *,
    connection_id: str,
    provider: str,
    matter_id: str,
    metadata: FileMetadata,
    status: str = "discovered",
) -> str:
    """Insert or update inventory row; return source_file_id."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT source_file_id FROM source_files
                WHERE connection_id = %(cid)s AND provider_file_id = %(pfid)s
                """,
                {"cid": connection_id, "pfid": metadata.provider_file_id},
            )
            existing = cur.fetchone()
            if existing:
                sfid = existing["source_file_id"]
                cur.execute(
                    """
                    UPDATE source_files SET
                        name = %(name)s,
                        mime_type = %(mime)s,
                        size_bytes = %(sz)s,
                        parent_provider_file_id = %(parent)s,
                        path = %(path)s,
                        web_url = %(url)s,
                        created_at_remote = %(cat)s,
                        modified_at_remote = %(mat)s,
                        etag = %(etag)s,
                        content_hash = COALESCE(%(ch)s, content_hash),
                        is_folder = %(folder)s,
                        matter_id = %(mid)s,
                        status = %(status)s,
                        deleted_at = NULL,
                        error = NULL,
                        updated_at = %(ts)s
                    WHERE source_file_id = %(sfid)s
                    """,
                    {
                        "sfid": sfid,
                        "name": metadata.name,
                        "mime": metadata.mime_type,
                        "sz": metadata.size_bytes,
                        "parent": metadata.parent_provider_file_id,
                        "path": metadata.path,
                        "url": metadata.web_url,
                        "cat": metadata.created_at,
                        "mat": metadata.modified_at,
                        "etag": metadata.etag,
                        "ch": metadata.content_hash,
                        "folder": metadata.is_folder,
                        "mid": matter_id,
                        "status": status,
                        "ts": _now(),
                    },
                )
            else:
                sfid = _gen_id("SF")
                cur.execute(
                    """
                    INSERT INTO source_files (
                        source_file_id, connection_id, provider, provider_file_id,
                        name, mime_type, size_bytes, parent_provider_file_id,
                        path, web_url, created_at_remote, modified_at_remote,
                        etag, content_hash, is_folder, matter_id, status, updated_at
                    ) VALUES (
                        %(sfid)s, %(cid)s, %(prov)s, %(pfid)s,
                        %(name)s, %(mime)s, %(sz)s, %(parent)s,
                        %(path)s, %(url)s, %(cat)s, %(mat)s,
                        %(etag)s, %(ch)s, %(folder)s, %(mid)s, %(status)s, %(ts)s
                    )
                    """,
                    {
                        "sfid": sfid,
                        "cid": connection_id,
                        "prov": provider,
                        "pfid": metadata.provider_file_id,
                        "name": metadata.name,
                        "mime": metadata.mime_type,
                        "sz": metadata.size_bytes,
                        "parent": metadata.parent_provider_file_id,
                        "path": metadata.path,
                        "url": metadata.web_url,
                        "cat": metadata.created_at,
                        "mat": metadata.modified_at,
                        "etag": metadata.etag,
                        "ch": metadata.content_hash,
                        "folder": metadata.is_folder,
                        "mid": matter_id,
                        "status": status,
                        "ts": _now(),
                    },
                )
            conn.commit()
            return sfid


def get_source_file_by_provider(
    connection_id: str, provider_file_id: str
) -> dict | None:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM source_files
                WHERE connection_id = %(cid)s AND provider_file_id = %(pfid)s
                """,
                {"cid": connection_id, "pfid": provider_file_id},
            )
            return cur.fetchone()


def mark_source_file(
    source_file_id: str,
    *,
    status: str,
    document_id: str | None = None,
    content_hash: str | None = None,
    etag: str | None = None,
    error: str | None = None,
    deleted: bool = False,
) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE source_files SET
                    status = %(status)s,
                    document_id = COALESCE(%(did)s, document_id),
                    content_hash = COALESCE(%(ch)s, content_hash),
                    etag = COALESCE(%(etag)s, etag),
                    error = %(err)s,
                    deleted_at = CASE WHEN %(del)s THEN %(ts)s ELSE deleted_at END,
                    updated_at = %(ts)s
                WHERE source_file_id = %(sfid)s
                """,
                {
                    "sfid": source_file_id,
                    "status": status,
                    "did": document_id,
                    "ch": content_hash,
                    "etag": etag,
                    "err": error,
                    "del": deleted,
                    "ts": _now(),
                },
            )
            conn.commit()


def replace_permissions(source_file_id: str, permissions: list[Permission]) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM source_file_permissions WHERE source_file_id = %(sfid)s",
                {"sfid": source_file_id},
            )
            for p in permissions:
                cur.execute(
                    """
                    INSERT INTO source_file_permissions (
                        source_file_id, principal_type, principal_id, permission
                    ) VALUES (%(sfid)s, %(pt)s, %(pid)s, %(perm)s)
                    ON CONFLICT DO NOTHING
                    """,
                    {
                        "sfid": source_file_id,
                        "pt": p.principal_type,
                        "pid": p.principal_id,
                        "perm": p.permission,
                    },
                )
            conn.commit()


def soft_delete_indexed_document(document_id: str) -> None:
    """Remove searchable chunks and clear body pointer for a tombstoned source file."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM chunks WHERE document_id = %(did)s",
                {"did": document_id},
            )
            cur.execute(
                """
                UPDATE documents
                SET status = 'Deleted', body = '', updated_at = %(ts)s
                WHERE document_id = %(did)s
                """,
                {"did": document_id, "ts": _now()},
            )
            conn.commit()


def list_source_files(connection_id: str, limit: int = 100) -> list[dict]:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT source_file_id, provider_file_id, name, mime_type, path,
                       status, document_id, content_hash, etag, deleted_at, error
                FROM source_files
                WHERE connection_id = %(cid)s
                ORDER BY path NULLS LAST, name
                LIMIT %(lim)s
                """,
                {"cid": connection_id, "lim": limit},
            )
            return list(cur.fetchall())


def disconnect_connection(connection_id: str) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE source_connections
                SET status = 'disconnected',
                    encrypted_access_token = NULL,
                    encrypted_refresh_token = NULL,
                    updated_at = %(ts)s
                WHERE connection_id = %(cid)s
                """,
                {"cid": connection_id, "ts": _now()},
            )
            conn.commit()
