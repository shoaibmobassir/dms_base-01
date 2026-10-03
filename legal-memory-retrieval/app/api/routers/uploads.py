"""Upload batch API — folder-preserving multi-file ingest (FirmOS)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.api.acl import ACL_CLAUSE
from app.audit import events as audit
from app.auth.deps import resolve_member
from app.config import settings
from app.db.connection import connect
from app.ingest.upload_batch import create_upload_batch, get_upload_batch, process_upload_batch
from app.ingest.upload_policy import UploadRejected

router = APIRouter(tags=["uploads"])

SERVICE = "uploads"


def _require_matter_access(matter_id: str, member_id: str | None) -> None:
    with connect() as conn:
        row = conn.execute(
            f"""
            SELECT 1 FROM matters m LEFT JOIN permissions p ON p.matter_id = m.matter_id
            WHERE m.matter_id = %(matter_id)s AND {ACL_CLAUSE}
            """,
            {"matter_id": matter_id, "member_id": member_id},
        ).fetchone()
    if row is None:
        audit.record("matter.access", member_id=member_id, outcome="denied", object_type="matter", object_id=matter_id)
        raise HTTPException(status_code=404, detail="Matter not found or access denied")


def _owned_batch(batch_id: str, member_id: str | None) -> dict:
    """A batch is visible only to the member who created it (and who can still see the matter)."""
    batch = get_upload_batch(batch_id)
    if not batch or batch.get("created_by") != member_id:
        raise HTTPException(status_code=404, detail="Batch not found")
    _require_matter_access(batch["matter_id"], member_id)
    return batch


@router.get("/health")
def uploads_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


@router.post("/batches")
def create_batch(
    matter_id: str = Form(...),
    client_id: Optional[str] = Form(default=None),
    files: list[UploadFile] = File(...),
    relative_paths: Optional[list[str]] = Form(default=None),
    member_id: str | None = Depends(resolve_member),
) -> dict:
    """
    Upload one or more files preserving folder hierarchy.

    Pass ``relative_paths`` aligned with ``files`` (e.g. ``Agreements/SPA.pdf``).
    If omitted, uses each file's ``filename``. Files are streamed from the request's
    spooled temp files to object storage; the whole request is size-capped by
    ``UploadLimitMiddleware`` before parsing.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    _require_matter_access(matter_id, member_id)

    payloads = []
    for i, uf in enumerate(files):
        if relative_paths and i < len(relative_paths) and relative_paths[i]:
            rel = relative_paths[i]
        else:
            rel = uf.filename or f"file_{i}"
        payloads.append((rel, uf.file))

    try:
        result = create_upload_batch(
            matter_id=matter_id,
            files=payloads,
            client_id=client_id,
            created_by=member_id,
        )
    except UploadRejected as exc:
        audit.record("upload.create", member_id=member_id, outcome="denied", object_type="matter", object_id=matter_id,
                     matter_id=matter_id, detail={"reason": str(exc)})
        status = 413 if "limit" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit.record("upload.create", member_id=member_id, object_type="upload_batch", object_id=result["batch_id"],
                 matter_id=matter_id, detail={"files": [f["relative_path"] for f in result["files"]]})
    return {"service": SERVICE, **result}


@router.get("/batches")
def my_batches(limit: int = 15, member_id: str | None = Depends(resolve_member)) -> dict:
    """The caller's recent upload batches (newest first), with each file's outcome, for the Documents page."""
    limit = max(1, min(limit, 50))
    with connect() as conn:
        batches = conn.execute(
            f"""
            SELECT b.batch_id, b.matter_id, m.title AS matter_title, b.status, b.total_files, b.created_at
            FROM upload_batches b
            JOIN matters m ON m.matter_id = b.matter_id
            LEFT JOIN permissions p ON p.matter_id = m.matter_id
            WHERE b.created_by = %(member_id)s AND {ACL_CLAUSE}
            GROUP BY b.batch_id, m.title
            ORDER BY b.created_at DESC LIMIT %(limit)s
            """,
            {"member_id": member_id, "limit": limit},
        ).fetchall()
        out = []
        for b in batches:
            files = conn.execute(
                "SELECT relative_path, status, document_id, error FROM upload_batch_files WHERE batch_id = %s ORDER BY relative_path",
                (b["batch_id"],),
            ).fetchall()
            counts = {k: sum(1 for f in files if f["status"] == k) for k in ("indexed", "skipped", "failed", "quarantined")}
            out.append({**b, "created_at": b["created_at"].isoformat(), "files": files,
                        "indexed": counts["indexed"], "duplicates": counts["skipped"],
                        "failed": counts["failed"] + counts["quarantined"],
                        "retryable": counts["failed"] > 0})
    return {"service": SERVICE, "batches": out}


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return {"service": SERVICE, "batch": _owned_batch(batch_id, member_id)}


@router.post("/batches/{batch_id}/run")
def run_batch(batch_id: str, member_id: str | None = Depends(resolve_member)):
    """Process pending files with per-file failure isolation.

    INGEST_MODE=queue (production): mark the batch queued and return 202; the ingest
    worker processes it and the client polls GET /batches/{id}.
    """
    batch = _owned_batch(batch_id, member_id)
    if settings.ingest_mode == "queue":
        from app.workers.ingest import enqueue

        enqueue(batch_id)
        audit.record("upload.process", member_id=member_id, object_type="upload_batch", object_id=batch_id,
                     matter_id=batch["matter_id"], detail={"status": "queued"})
        return JSONResponse(status_code=202, content={"service": SERVICE, "batch_id": batch_id, "status": "queued"})
    try:
        result = process_upload_batch(batch_id, created_by=member_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    audit.record("upload.process", member_id=member_id, object_type="upload_batch", object_id=batch_id,
                 matter_id=batch["matter_id"], detail={k: result.get(k) for k in ("status", "indexed", "skipped", "failed")})
    return {"service": SERVICE, **result}
