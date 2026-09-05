"""
Audit & Tamper-Evident Export API Router: Exporting signed ZIP packages and verifying cryptographic signatures.
Clean-room independent implementation.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, Field

from app.audit.manifest_signer import get_manifest_signer

router = APIRouter(tags=["Audit & Tamper-Evident Exports"])


class ExportBundleRequest(BaseModel):
    title: str
    matter_id: Optional[str] = None
    files: List[Dict[str, str]] = Field(
        ...,
        description="List of { 'path': '...', 'content': '...' } files to bundle",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VerifyManifestRequest(BaseModel):
    manifest_json: str


@router.get("/health")
async def health():
    return {"status": "ok", "service": "audit_tamper_evident"}


@router.post("/export-bundle")
async def create_signed_export_bundle(
    req: ExportBundleRequest,
    x_member_id: Optional[str] = Header(None),
):
    """Generates a tamper-evident ZIP archive with signed SHA-256 MANIFEST.json."""
    signer = get_manifest_signer()

    file_tuples = [
        (f["path"], f["content"].encode("utf-8"))
        for f in req.files
    ]

    meta = dict(req.metadata)
    meta["member_id"] = x_member_id or "ANONYMOUS"
    meta["matter_id"] = req.matter_id or "GENERAL"

    zip_bytes = signer.build_signed_export_zip(
        export_title=req.title,
        files=file_tuples,
        metadata=meta,
    )

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="firmos_signed_export.zip"'},
    )


@router.post("/verify-manifest")
async def verify_export_manifest(req: VerifyManifestRequest):
    """Verifies whether a MANIFEST.json signature has been tampered with."""
    signer = get_manifest_signer()
    is_valid = signer.verify_manifest(req.manifest_json)
    return {
        "is_valid": is_valid,
        "status": "AUTHENTIC" if is_valid else "TAMPERED_OR_INVALID",
    }
