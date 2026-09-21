"""Download → object store → extract → document index for a source file."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from psycopg.rows import dict_row

from app.config import settings
from app.db.connection import connect
from app.documents import create_version
from app.ingest.extractors.dispatch import extract_from_bytes
from app.sources.factory import get_connector
from app.sources import store
from app.storage.object_store import (
    build_storage_key,
    content_sha256_bytes,
    get_object_store,
    guess_mime,
)

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def process_download(
    connection_id: str,
    provider_file_id: str,
    *,
    force: bool = False,
) -> dict:
    """Fetch bytes for one remote file and index into the bound matter.

    Idempotent: if stored content_hash matches remote hash and not force, skip.
    """
    connection = store.get_connection(connection_id)
    if not connection:
        return {"status": "failed", "error": "connection_not_found"}
    if connection.status != "active":
        return {"status": "failed", "error": "connection_not_active"}

    matter_id = (connection.config or {}).get("matter_id")
    if not matter_id:
        return {"status": "failed", "error": "matter_id_missing"}

    row = store.get_source_file_by_provider(connection_id, provider_file_id)
    if not row:
        return {"status": "failed", "error": "source_file_not_found"}
    if row.get("is_folder"):
        store.mark_source_file(row["source_file_id"], status="ignored")
        return {"status": "ignored", "reason": "folder"}

    connector = get_connector(connection)
    connector.authenticate()
    meta = connector.get_file(provider_file_id)

    if (
        not force
        and row.get("content_hash")
        and meta.content_hash
        and row["content_hash"] == meta.content_hash
        and row.get("status") == "indexed"
        and row.get("document_id")
    ):
        store.mark_source_file(
            row["source_file_id"],
            status="skipped_unchanged",
            content_hash=meta.content_hash,
            etag=meta.etag,
        )
        return {
            "status": "skipped_unchanged",
            "source_file_id": row["source_file_id"],
            "document_id": row["document_id"],
        }

    store.mark_source_file(row["source_file_id"], status="downloading")

    chunks = list(connector.download_file(provider_file_id))
    data = b"".join(chunks)
    sha = content_sha256_bytes(data)
    remote_hash = meta.content_hash or sha

    if (
        not force
        and row.get("content_hash") == remote_hash
        and row.get("status") == "indexed"
        and row.get("document_id")
    ):
        store.mark_source_file(
            row["source_file_id"],
            status="skipped_unchanged",
            content_hash=remote_hash,
            etag=meta.etag,
        )
        return {
            "status": "skipped_unchanged",
            "source_file_id": row["source_file_id"],
            "document_id": row["document_id"],
        }

    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT client_id FROM matters WHERE matter_id = %(mid)s",
                {"mid": matter_id},
            )
            matter = cur.fetchone()
    if not matter:
        store.mark_source_file(
            row["source_file_id"], status="failed", error="matter_not_found"
        )
        return {"status": "failed", "error": "matter_not_found"}

    client_id = matter["client_id"] or "CLIENT-UNKNOWN"
    doc_id = row.get("document_id") or f"DOC-{uuid.uuid4().hex[:10].upper()}"
    filename = meta.name or Path(meta.path or "file.bin").name
    mime = meta.mime_type or guess_mime(filename)

    key = build_storage_key(
        tenant_id=settings.tenant_id,
        client_id=client_id,
        matter_id=matter_id,
        document_id=doc_id,
        version_number=1 if not row.get("document_id") else 2,
        filename=filename,
    )
    store_obj = get_object_store()
    storage_uri = store_obj.put(key, data, content_type=mime)

    try:
        extracted = extract_from_bytes(filename, data)
        text = (extracted.text or "")[:500000]
    except Exception as exc:
        log.exception("extract failed for %s", provider_file_id)
        store.mark_source_file(
            row["source_file_id"], status="failed", error=f"extract:{exc}"
        )
        return {"status": "failed", "error": str(exc)}

    folder_path = str(Path(meta.path or filename).parent).replace("\\", "/")
    if folder_path in (".", ""):
        folder_path = ""

    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if row.get("document_id"):
                cur.execute(
                    """
                    UPDATE documents SET
                        title = %(title)s,
                        body = %(body)s,
                        content_sha256 = %(sha)s,
                        mime_type = %(mime)s,
                        folder_path = %(fpath)s,
                        source_uri = %(uri)s,
                        source_connection_id = %(scid)s,
                        source_file_id = %(sfid)s,
                        provider = %(prov)s,
                        provider_file_id = %(pfid)s,
                        status = 'Active',
                        updated_at = %(ts)s
                    WHERE document_id = %(did)s
                    """,
                    {
                        "did": doc_id,
                        "title": filename,
                        "body": text,
                        "sha": sha,
                        "mime": mime,
                        "fpath": folder_path,
                        "uri": storage_uri,
                        "scid": connection_id,
                        "sfid": row["source_file_id"],
                        "prov": connection.provider,
                        "pfid": provider_file_id,
                        "ts": _now(),
                    },
                )
            else:
                # Dedup by content hash within matter
                cur.execute(
                    """
                    SELECT document_id FROM documents
                    WHERE matter_id = %(mid)s AND content_sha256 = %(sha)s
                    LIMIT 1
                    """,
                    {"mid": matter_id, "sha": sha},
                )
                dup = cur.fetchone()
                if dup:
                    doc_id = dup["document_id"]
                    cur.execute(
                        """
                        UPDATE documents SET
                            source_connection_id = %(scid)s,
                            source_file_id = %(sfid)s,
                            provider = %(prov)s,
                            provider_file_id = %(pfid)s,
                            source_uri = %(uri)s,
                            updated_at = %(ts)s
                        WHERE document_id = %(did)s
                        """,
                        {
                            "did": doc_id,
                            "scid": connection_id,
                            "sfid": row["source_file_id"],
                            "prov": connection.provider,
                            "pfid": provider_file_id,
                            "uri": storage_uri,
                            "ts": _now(),
                        },
                    )
                    conn.commit()
                    store.mark_source_file(
                        row["source_file_id"],
                        status="indexed",
                        document_id=doc_id,
                        content_hash=remote_hash,
                        etag=meta.etag,
                    )
                    return {
                        "status": "indexed",
                        "document_id": doc_id,
                        "deduped": True,
                    }

                cur.execute(
                    """
                    INSERT INTO documents (
                        document_id, matter_id, title, document_type, body,
                        status, version, content_sha256, mime_type, folder_path,
                        ingested_at, source_uri,
                        source_connection_id, source_file_id, provider, provider_file_id
                    ) VALUES (
                        %(did)s, %(mid)s, %(title)s, 'Synced', %(body)s,
                        'Active', 'v1.0', %(sha)s, %(mime)s, %(fpath)s,
                        %(ts)s, %(uri)s,
                        %(scid)s, %(sfid)s, %(prov)s, %(pfid)s
                    )
                    """,
                    {
                        "did": doc_id,
                        "mid": matter_id,
                        "title": filename,
                        "body": text,
                        "sha": sha,
                        "mime": mime,
                        "fpath": folder_path,
                        "ts": _now(),
                        "uri": storage_uri,
                        "scid": connection_id,
                        "sfid": row["source_file_id"],
                        "prov": connection.provider,
                        "pfid": provider_file_id,
                    },
                )
            conn.commit()

    create_version(
        document_id=doc_id,
        body=text,
        title=filename,
        author_name="source-sync",
        source="import",
        version_status="final",
        change_summary=f"Synced from {connection.provider}:{provider_file_id}",
        storage_uri=storage_uri,
        page_spans=getattr(extracted, "pages", None),
        folder_path=folder_path,
    )

    try:
        perms = connector.get_permissions(provider_file_id)
        store.replace_permissions(row["source_file_id"], perms)
    except Exception as exc:
        log.warning("permission fetch failed for %s: %s", provider_file_id, exc)

    store.mark_source_file(
        row["source_file_id"],
        status="indexed",
        document_id=doc_id,
        content_hash=remote_hash,
        etag=meta.etag,
    )
    return {
        "status": "indexed",
        "document_id": doc_id,
        "source_file_id": row["source_file_id"],
        "storage_uri": storage_uri,
        "content_hash": remote_hash,
    }
