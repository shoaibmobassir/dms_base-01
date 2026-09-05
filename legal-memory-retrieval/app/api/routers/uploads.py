"""Upload batch API — folder-preserving multi-file ingest (FirmOS)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.auth.deps import resolve_member
from app.ingest.upload_batch import create_upload_batch, get_upload_batch, process_upload_batch

router = APIRouter(tags=["uploads"])

SERVICE = "uploads"


@router.get("/health")
def uploads_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


@router.post("/batches")
async def create_batch(
    matter_id: str = Form(...),
    client_id: Optional[str] = Form(default=None),
    files: list[UploadFile] = File(...),
    relative_paths: Optional[list[str]] = Form(default=None),
    member_id: str | None = Depends(resolve_member),
) -> dict:
    """
    Upload one or more files preserving folder hierarchy.

    Pass ``relative_paths`` aligned with ``files`` (e.g. ``Agreements/SPA.pdf``).
    If omitted, uses each file's ``filename``.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    payloads: list[tuple[str, bytes]] = []
    for i, uf in enumerate(files):
        data = await uf.read()
        if relative_paths and i < len(relative_paths) and relative_paths[i]:
            rel = relative_paths[i]
        else:
            rel = uf.filename or f"file_{i}"
        payloads.append((rel, data))

    try:
        result = create_upload_batch(
            matter_id=matter_id,
            files=payloads,
            client_id=client_id,
            created_by=member_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"service": SERVICE, **result}


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    batch = get_upload_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {"service": SERVICE, "batch": batch}


@router.post("/batches/{batch_id}/run")
def run_batch(batch_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    """Process pending files with per-file failure isolation."""
    try:
        result = process_upload_batch(batch_id, created_by=member_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"service": SERVICE, **result}
