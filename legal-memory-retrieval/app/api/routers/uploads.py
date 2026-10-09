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


def _require_workspace(kind: str, container_id: str, member_id: str | None) -> None:
    """Uploading into a workspace: a matter the member can see (as before), a project where they are an
    editor or owner, or their own library."""
    if kind == "matter":
        _require_matter_access(container_id, member_id)
        return
    from app import access

    with connect() as conn:
        level = access.container_level(conn, member_id, kind, container_id)
        archived = (conn.execute("SELECT archived_at FROM projects WHERE project_id = %s", (container_id,)).fetchone()
                    if kind == "project" else None)
    if level == "none":
        raise HTTPException(status_code=404, detail="Workspace not found or access denied")
    if access.LEVELS.index(level) < access.LEVELS.index("edit"):
        raise HTTPException(status_code=403, detail="Requires edit access to this workspace")
    if archived and archived["archived_at"] is not None:
        raise HTTPException(status_code=409, detail="This project is archived; restore it first")


def _owned_batch(batch_id: str, member_id: str | None) -> dict:
    """A batch is visible only to the member who created it (and who can still reach its workspace)."""
    batch = get_upload_batch(batch_id)
    if not batch or batch.get("created_by") != member_id:
        raise HTTPException(status_code=404, detail="Batch not found")
    kind = batch.get("container_kind") or "matter"
    _require_workspace(kind, batch.get("container_id") or batch["matter_id"], member_id)
    return batch


@router.get("/health")
def uploads_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


@router.post("/batches")
def create_batch(
    matter_id: Optional[str] = Form(default=None),
    client_id: Optional[str] = Form(default=None),
    files: list[UploadFile] = File(...),
    relative_paths: Optional[list[str]] = Form(default=None),
    container_kind: str = Form(default="matter"),
    container_id: Optional[str] = Form(default=None),
    folder_prefix: str = Form(default=""),
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
    if container_kind not in ("matter", "project", "library", "firm"):
        raise HTTPException(status_code=422, detail="container_kind must be matter, project, library or firm")
    if container_kind == "firm":
        container_id = "templates"
    if container_kind == "matter":
        container_id = container_id or matter_id
    elif container_kind == "library":
        container_id = container_id or member_id
    if not container_id:
        raise HTTPException(status_code=422, detail="Choose where to upload: a matter, a project or your library")
    from app.firm import FirmError
    from app.workspaces import clean_path

    try:
        folder_prefix = clean_path(folder_prefix)
    except FirmError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    _require_workspace(container_kind, container_id, member_id)
    matter_id = container_id if container_kind == "matter" else None

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
            container_kind=container_kind,
            container_id=container_id,
            folder_prefix=folder_prefix,
        )
    except UploadRejected as exc:
        audit.record("upload.create", member_id=member_id, outcome="denied", object_type=container_kind,
                     object_id=container_id, matter_id=matter_id, detail={"reason": str(exc)})
        status = 413 if "limit" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit.record("upload.create", member_id=member_id, object_type="upload_batch", object_id=result["batch_id"],
                 matter_id=matter_id, detail={"files": [f["relative_path"] for f in result["files"]],
                                              "kind": container_kind, "id": container_id})
    return {"service": SERVICE, **result}


@router.get("/batches")
def my_batches(limit: int = 15, member_id: str | None = Depends(resolve_member)) -> dict:
    """The caller's recent upload batches (newest first), with each file's outcome, for the Documents page."""
    limit = max(1, min(limit, 50))
    with connect() as conn:
        batches = conn.execute(
            f"""
            SELECT b.batch_id, b.matter_id, m.title AS matter_title, b.container_kind, b.container_id,
                   coalesce(m.title, pr.title, CASE WHEN b.container_kind = 'library' THEN 'My library'
                                                   WHEN b.container_kind = 'firm' THEN 'Firm templates' END) AS workspace_title,
                   b.folder_prefix, b.status, b.total_files, b.created_at
            FROM upload_batches b
            LEFT JOIN matters m ON m.matter_id = b.matter_id
            LEFT JOIN projects pr ON b.container_kind = 'project' AND pr.project_id = b.container_id
            LEFT JOIN permissions p ON p.matter_id = m.matter_id
            WHERE b.created_by = %(member_id)s
              AND CASE WHEN b.container_kind = 'matter' THEN m.matter_id IS NOT NULL AND {ACL_CLAUSE}
                       WHEN b.container_kind = 'library' THEN b.container_id = %(member_id)s
                       WHEN b.container_kind = 'firm' THEN TRUE
                       ELSE EXISTS (SELECT 1 FROM project_members pm
                                    LEFT JOIN team_members tm ON pm.principal_type = 'team' AND tm.team_id = pm.principal_id
                                    WHERE pm.project_id = b.container_id
                                      AND ((pm.principal_type = 'member' AND pm.principal_id = %(member_id)s)
                                           OR tm.member_id = %(member_id)s)) END
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
