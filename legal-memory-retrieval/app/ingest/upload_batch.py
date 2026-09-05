"""Upload batch: folder-preserving ingest with object storage + per-file isolation.

FirmOS Immediate Next tasks 3–5:
  - deterministic storage keys
  - folder upload + manifest
  - async-style job with retries / one failure ≠ batch failure
"""
from __future__ import annotations

import json
import logging
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from psycopg.rows import dict_row

from app.config import settings
from app.db.connection import connect
from app.documents import create_version
from app.ingest.extractors.dispatch import extract_from_bytes
from app.ingest.jobs import complete_job, create_job, mark_item, register_items
from app.storage.object_store import (
    build_storage_key,
    content_sha256_bytes,
    get_object_store,
    guess_mime,
)

log = logging.getLogger(__name__)

TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".html", ".xml"}
PDF_EXTENSIONS = {".pdf"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_upload_batch(
    *,
    matter_id: str,
    files: list[tuple[str, bytes]],
    client_id: str | None = None,
    tenant_id: str | None = None,
    created_by: str | None = None,
) -> dict:
    """
    Persist raw files to object storage, create upload_batches + ingest_job.

    ``files``: list of (relative_path, content_bytes). Paths preserve folder hierarchy.
    """
    if not files:
        raise ValueError("No files provided")

    tenant = tenant_id or settings.tenant_id
    store = get_object_store()
    batch_id = f"BAT-{uuid.uuid4().hex[:10].upper()}"

    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT matter_id, client_id, title FROM matters WHERE matter_id = %(mid)s",
                {"mid": matter_id},
            )
            matter = cur.fetchone()
            if not matter:
                raise ValueError(f"Matter not found: {matter_id}")
            client = client_id or matter["client_id"] or "CLIENT-UNKNOWN"

            job_id = create_job(conn, f"upload://{batch_id}", len(files), workers=1)

            cur.execute(
                """
                INSERT INTO upload_batches (
                    batch_id, tenant_id, matter_id, client_id, status,
                    total_files, ingest_job_id, created_by, created_at, manifest
                ) VALUES (
                    %(bid)s, %(tid)s, %(mid)s, %(cid)s, 'pending',
                    %(n)s, %(jid)s, %(by)s, %(ts)s, %(manifest)s::jsonb
                )
                """,
                {
                    "bid": batch_id,
                    "tid": tenant,
                    "mid": matter_id,
                    "cid": client,
                    "n": len(files),
                    "jid": job_id,
                    "by": created_by,
                    "ts": _now(),
                    "manifest": "[]",
                },
            )

            manifest_entries: list[dict] = []
            source_uris: list[str] = []

            for rel_path, data in files:
                rel = rel_path.replace("\\", "/").lstrip("/")
                name = Path(rel).name
                sha = content_sha256_bytes(data)
                mime = guess_mime(name)
                # Provisional document id for key stability (final DOC id may differ)
                provisional_doc = f"DOC-{uuid.uuid4().hex[:10].upper()}"
                key = build_storage_key(
                    tenant_id=tenant,
                    client_id=client,
                    matter_id=matter_id,
                    document_id=provisional_doc,
                    version_number=1,
                    filename=name,
                )
                uri = store.put(key, data, content_type=mime)
                entry = {
                    "relative_path": rel,
                    "filename": name,
                    "storage_uri": uri,
                    "storage_key": key,
                    "content_sha256": sha,
                    "size_bytes": len(data),
                    "mime_type": mime,
                    "provisional_document_id": provisional_doc,
                    "status": "pending",
                }
                manifest_entries.append(entry)
                source_uris.append(uri)

                cur.execute(
                    """
                    INSERT INTO upload_batch_files (
                        batch_id, relative_path, storage_uri, content_sha256,
                        size_bytes, mime_type, status, provisional_document_id
                    ) VALUES (
                        %(bid)s, %(rel)s, %(uri)s, %(sha)s,
                        %(sz)s, %(mime)s, 'pending', %(pdid)s
                    )
                    """,
                    {
                        "bid": batch_id,
                        "rel": rel,
                        "uri": uri,
                        "sha": sha,
                        "sz": len(data),
                        "mime": mime,
                        "pdid": provisional_doc,
                    },
                )

            cur.execute(
                "UPDATE upload_batches SET manifest = %(m)s::jsonb WHERE batch_id = %(bid)s",
                {"m": json.dumps(manifest_entries), "bid": batch_id},
            )
            register_items(conn, job_id, source_uris)
            conn.commit()

    return {
        "batch_id": batch_id,
        "ingest_job_id": job_id,
        "matter_id": matter_id,
        "client_id": client,
        "tenant_id": tenant,
        "status": "pending",
        "total_files": len(files),
        "files": [
            {
                "relative_path": e["relative_path"],
                "storage_uri": e["storage_uri"],
                "content_sha256": e["content_sha256"],
                "size_bytes": e["size_bytes"],
                "mime_type": e["mime_type"],
            }
            for e in manifest_entries
        ],
    }


def get_upload_batch(batch_id: str) -> dict | None:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM upload_batches WHERE batch_id = %(bid)s", {"bid": batch_id})
            batch = cur.fetchone()
            if not batch:
                return None
            cur.execute(
                """
                SELECT relative_path, storage_uri, content_sha256, size_bytes,
                       mime_type, status, document_id, version_id, error, processed_at
                FROM upload_batch_files
                WHERE batch_id = %(bid)s
                ORDER BY relative_path
                """,
                {"bid": batch_id},
            )
            files = list(cur.fetchall())
            out = dict(batch)
            out["files"] = files
            return out


def _extract_document(filename: str, data: bytes):
    """Return page-aware ExtractedDocument (PDF/DOCX/text)."""
    return extract_from_bytes(filename, data)


def _ensure_folders(
    cur,
    project_id: str | None,
    folder_path: str,
    created_by: str | None,
) -> str | None:
    """Create nested project_folders for path segments; return leaf folder_id."""
    parts = [p for p in folder_path.split("/") if p]
    if not parts or not project_id:
        return None
    parent_id: str | None = None
    built = ""
    for part in parts:
        built = f"{built}/{part}" if built else part
        cur.execute(
            """
            SELECT folder_id FROM project_folders
            WHERE project_id = %(pid)s AND name = %(name)s
              AND COALESCE(parent_folder_id, '') = COALESCE(%(parent)s, '')
            """,
            {"pid": project_id, "name": part, "parent": parent_id},
        )
        row = cur.fetchone()
        if row:
            parent_id = row["folder_id"]
            continue
        fid = f"FLD-{uuid.uuid4().hex[:8].upper()}"
        cur.execute(
            """
            INSERT INTO project_folders (folder_id, project_id, name, parent_folder_id, created_by)
            VALUES (%(fid)s, %(pid)s, %(name)s, %(parent)s, %(by)s)
            """,
            {
                "fid": fid,
                "pid": project_id,
                "name": part,
                "parent": parent_id,
                "by": created_by,
            },
        )
        parent_id = fid
    return parent_id


def process_upload_batch(batch_id: str, *, created_by: str | None = None) -> dict:
    """Process each file independently: extract → document → version → blocks."""
    batch = get_upload_batch(batch_id)
    if not batch:
        raise ValueError(f"Batch not found: {batch_id}")

    store = get_object_store()
    matter_id = batch["matter_id"]
    client_id = batch["client_id"]
    job_id = batch["ingest_job_id"]
    indexed = 0
    failed = 0
    skipped = 0
    errors: list[dict] = []

    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "UPDATE upload_batches SET status = 'running', updated_at = %(ts)s WHERE batch_id = %(bid)s",
                {"ts": _now(), "bid": batch_id},
            )
            cur.execute(
                "SELECT project_id FROM projects WHERE matter_id = %(mid)s LIMIT 1",
                {"mid": matter_id},
            )
            proj = cur.fetchone()
            project_id = proj["project_id"] if proj else None
            conn.commit()

    for f in batch["files"]:
        rel = f["relative_path"]
        uri = f["storage_uri"]
        if f["status"] in ("indexed", "skipped"):
            skipped += 1
            continue
        try:
            data = store.get(uri)
            extracted = _extract_document(f.get("filename") or Path(rel).name, data)
            text, page_count = extracted.text, extracted.page_count
            folder_path = str(Path(rel).parent).replace("\\", "/")
            if folder_path in (".", ""):
                folder_path = ""

            with connect() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    # Duplicate detection by content hash within matter
                    cur.execute(
                        """
                        SELECT document_id FROM documents
                        WHERE matter_id = %(mid)s AND content_sha256 = %(sha)s
                        LIMIT 1
                        """,
                        {"mid": matter_id, "sha": f["content_sha256"]},
                    )
                    existing = cur.fetchone()
                    if existing:
                        cur.execute(
                            """
                            UPDATE upload_batch_files
                            SET status = 'skipped', document_id = %(did)s,
                                error = 'duplicate content_sha256', processed_at = %(ts)s
                            WHERE batch_id = %(bid)s AND relative_path = %(rel)s
                            """,
                            {
                                "did": existing["document_id"],
                                "ts": _now(),
                                "bid": batch_id,
                                "rel": rel,
                            },
                        )
                        conn.commit()
                        mark_item(conn, job_id, uri, "skipped", document_id=existing["document_id"], sha=f["content_sha256"])
                        skipped += 1
                        continue

                    folder_id = _ensure_folders(cur, project_id, folder_path, created_by)
                    doc_id = f.get("provisional_document_id") or f"DOC-{uuid.uuid4().hex[:10].upper()}"
                    # upload_batch_files may not have provisional in SELECT — use from earlier
                    cur.execute(
                        "SELECT provisional_document_id FROM upload_batch_files WHERE batch_id=%(b)s AND relative_path=%(r)s",
                        {"b": batch_id, "r": rel},
                    )
                    prow = cur.fetchone()
                    if prow and prow.get("provisional_document_id"):
                        doc_id = prow["provisional_document_id"]

                    title = Path(rel).name
                    cur.execute(
                        """
                        INSERT INTO documents (
                            document_id, matter_id, title, document_type, body,
                            status, version, content_sha256, mime_type, folder_id,
                            folder_path, ingest_job_id, ingested_at, source_uri
                        ) VALUES (
                            %(did)s, %(mid)s, %(title)s, %(dtype)s, %(body)s,
                            'Draft', 'v1.0', %(sha)s, %(mime)s, %(fid)s,
                            %(fpath)s, %(jid)s, %(ts)s, %(uri)s
                        )
                        """,
                        {
                            "did": doc_id,
                            "mid": matter_id,
                            "title": title,
                            "dtype": "Uploaded",
                            "body": text[:500000],
                            "sha": f["content_sha256"],
                            "mime": extracted.mime_type or f["mime_type"],
                            "fid": folder_id,
                            "fpath": folder_path,
                            "jid": job_id,
                            "ts": _now(),
                            "uri": uri,
                        },
                    )
                    conn.commit()

            version = create_version(
                document_id=doc_id,
                body=text[:500000],
                title=title,
                author_name=created_by or "upload",
                source="upload",
                version_status="draft",
                change_summary=f"Uploaded from {rel}",
                storage_uri=uri,
                page_spans=extracted.pages,
                folder_path=folder_path,
            )

            with connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE document_versions
                        SET page_count = %(pc)s,
                            file_size_bytes = %(sz)s,
                            mime_type = %(mime)s
                        WHERE version_id = %(vid)s
                        """,
                        {
                            "pc": page_count,
                            "mime": f["mime_type"],
                            "sz": f["size_bytes"],
                            "vid": version["version_id"],
                        },
                    )
                    cur.execute(
                        """
                        UPDATE upload_batch_files
                        SET status = 'indexed', document_id = %(did)s,
                            version_id = %(vid)s, processed_at = %(ts)s, error = NULL
                        WHERE batch_id = %(bid)s AND relative_path = %(rel)s
                        """,
                        {
                            "did": doc_id,
                            "vid": version["version_id"],
                            "ts": _now(),
                            "bid": batch_id,
                            "rel": rel,
                        },
                    )
                    conn.commit()
                mark_item(
                    conn,
                    job_id,
                    uri,
                    "indexed",
                    document_id=doc_id,
                    sha=f["content_sha256"],
                )
            indexed += 1
        except Exception as exc:  # noqa: BLE001 — isolate per file
            log.exception("upload batch file failed: %s", rel)
            failed += 1
            err = str(exc)[:500]
            errors.append({"relative_path": rel, "error": err})
            with connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE upload_batch_files
                        SET status = 'failed', error = %(err)s, processed_at = %(ts)s
                        WHERE batch_id = %(bid)s AND relative_path = %(rel)s
                        """,
                        {"err": err, "ts": _now(), "bid": batch_id, "rel": rel},
                    )
                    conn.commit()
                mark_item(conn, job_id, uri, "failed", error=err)

    status = "completed" if failed == 0 else ("completed_with_errors" if indexed else "failed")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE upload_batches
                SET status = %(st)s, processed_files = %(ok)s, failed_files = %(fail)s,
                    updated_at = %(ts)s, error_summary = %(err)s
                WHERE batch_id = %(bid)s
                """,
                {
                    "st": status,
                    "ok": indexed,
                    "fail": failed,
                    "ts": _now(),
                    "err": None if not errors else json.dumps(errors[:20]),
                    "bid": batch_id,
                },
            )
            conn.commit()
        complete_job(conn, job_id, json.dumps(errors[:10]) if errors else None)

    return {
        "batch_id": batch_id,
        "status": status,
        "indexed": indexed,
        "skipped": skipped,
        "failed": failed,
        "errors": errors[:20],
        "batch": get_upload_batch(batch_id),
    }
