"""
Audit & Tamper-Evident Export API Router: Exporting signed ZIP packages and verifying cryptographic signatures.
Clean-room independent implementation.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from app.audit import events as audit
from app.audit.manifest_signer import get_manifest_signer
from app.auth.deps import resolve_member
from app.db.connection import connect

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
def create_signed_export_bundle(
    req: ExportBundleRequest,
    member_id: Optional[str] = Depends(resolve_member),
):
    """Generates a tamper-evident ZIP archive with signed SHA-256 MANIFEST.json."""
    signer = get_manifest_signer()

    file_tuples = [
        (f["path"], f["content"].encode("utf-8"))
        for f in req.files
    ]

    meta = dict(req.metadata)
    # The authenticated member, never a client-supplied header.
    meta["member_id"] = member_id or "ANONYMOUS"
    meta["matter_id"] = req.matter_id or "GENERAL"

    zip_bytes = signer.build_signed_export_zip(
        export_title=req.title,
        files=file_tuples,
        metadata=meta,
    )

    audit.record("export.bundle", member_id=member_id, object_type="export", matter_id=req.matter_id,
                 detail={"title": req.title, "files": [f["path"] for f in req.files]})
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


# ── Audit stream (production plan 08, step B) ─────────────────────────────────


def _require_admin(member_id: Optional[str]) -> str:
    if not audit.is_admin(member_id):
        audit.record("audit.read", member_id=member_id, outcome="denied")
        raise HTTPException(status_code=403, detail="Administrator access required")
    return member_id  # type: ignore[return-value]


@router.get("/events")
def list_audit_events(
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    member: Optional[str] = Query(default=None, description="filter by acting member"),
    matter_id: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None, description="exact action, or prefix ending with '.' (e.g. 'document.')"),
    outcome: Optional[str] = Query(default=None, pattern="^(success|denied|failure)$"),
    after_seq: int = Query(default=0, ge=0, description="page by sequence number"),
    limit: int = Query(default=500, ge=1, le=10000),
    format: str = Query(default="json", pattern="^(json|jsonl)$"),
    member_id: Optional[str] = Depends(resolve_member),
):
    """Administrator export of the audit stream (JSON page or JSONL download)."""
    admin = _require_admin(member_id)
    wheres, params = ["seq > %(after)s"], {"after": after_seq, "limit": limit}
    for col, val in (("member_id", member), ("matter_id", matter_id), ("outcome", outcome)):
        if val:
            wheres.append(f"{col} = %({col})s")
            params[col] = val
    if since:
        wheres.append("occurred_at >= %(since)s")
        params["since"] = since
    if until:
        wheres.append("occurred_at < %(until)s")
        params["until"] = until
    if action:
        if action.endswith("."):
            wheres.append("action LIKE %(action)s")
            params["action"] = action + "%"
        else:
            wheres.append("action = %(action)s")
            params["action"] = action
    sql = f"SELECT * FROM audit_events WHERE {' AND '.join(wheres)} ORDER BY seq LIMIT %(limit)s"
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = list(cur.fetchall())
    audit.record("audit.export", member_id=admin, detail={
        "filters": {k: str(v) for k, v in params.items() if k not in ("limit",)}, "rows": len(rows), "format": format,
    })
    if format == "jsonl":
        body = "".join(json.dumps(r, default=str) + "\n" for r in rows)
        return StreamingResponse(
            iter([body]),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": 'attachment; filename="audit-events.jsonl"'},
        )
    next_seq = rows[-1]["seq"] if len(rows) == limit else None
    return {"service": "audit", "events": rows, "next_after_seq": next_seq}


@router.get("/events/verify")
def verify_audit_chain(member_id: Optional[str] = Depends(resolve_member)) -> dict:
    """Recompute the hash chain; reports the first tampered or missing row."""
    admin = _require_admin(member_id)
    result = audit.verify_chain()
    audit.record("audit.verify", member_id=admin, detail=result)
    return {"service": "audit", **result}
