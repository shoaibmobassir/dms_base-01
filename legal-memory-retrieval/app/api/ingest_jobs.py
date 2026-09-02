"""Bulk ingest job API — create, poll, retry failed items."""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from app.db.connection import connect
from app.ingest.jobs import (
    complete_job,
    create_job,
    get_pending_items,
    job_status,
    mark_item,
    register_items,
)
from app.ingest.pipeline import ingest_one, load_manifest


def create_ingest_job(source_root: str, manifest_path: str, workers: int = 1) -> dict:
    source = Path(source_root)
    if not source.is_dir():
        raise HTTPException(status_code=400, detail=f"Invalid source_root: {source_root}")
    manifest = Path(manifest_path)
    if not manifest.is_file():
        raise HTTPException(status_code=400, detail=f"Invalid manifest: {manifest_path}")

    pdfs = sorted(source.glob("*.pdf"))
    if not pdfs:
        raise HTTPException(status_code=400, detail=f"No PDFs found in {source_root}")

    with connect() as conn:
        job_id = create_job(conn, str(source.resolve()), len(pdfs), workers)
        register_items(conn, job_id, [str(p.resolve()) for p in pdfs])

    return {
        "job_id": job_id,
        "status": "pending",
        "total_items": len(pdfs),
        "source_root": str(source.resolve()),
        "manifest": str(manifest.resolve()),
        "workers": workers,
    }


def run_ingest_job(job_id: str, manifest_path: str) -> dict:
    """Process all pending/failed items for a job (sync worker)."""
    manifests = load_manifest(manifest_path)
    with connect() as conn:
        pending = get_pending_items(conn, job_id)
    if not pending:
        with connect() as conn:
            status = job_status(conn, job_id)
        return {"job_id": job_id, "processed": 0, "status": status}

    results = []
    for uri in pending:
        result = ingest_one(uri, manifests, job_id=job_id)
        results.append({"source_uri": uri, **result})

    errors = [r for r in results if r.get("status") == "failed"]
    with connect() as conn:
        if errors:
            import json
            complete_job(conn, job_id, json.dumps(errors[:10]))
        else:
            complete_job(conn, job_id, None)
        status = job_status(conn, job_id)

    return {
        "job_id": job_id,
        "processed": len(results),
        "indexed": sum(1 for r in results if r.get("status") == "indexed"),
        "skipped": sum(1 for r in results if r.get("status") == "skipped"),
        "failed": sum(1 for r in results if r.get("status") == "failed"),
        "status": status,
    }


def get_ingest_job(job_id: str) -> dict:
    with connect() as conn:
        status = job_status(conn, job_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return status


def retry_ingest_job(job_id: str, manifest_path: str) -> dict:
    with connect() as conn:
        status = job_status(conn, job_id)
        if not status:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
        failed = conn.execute(
            "SELECT source_uri FROM ingest_items WHERE job_id = %s AND status = 'failed'",
            (job_id,),
        ).fetchall()
        for row in failed:
            mark_item(conn, job_id, row["source_uri"], "pending")
        conn.execute(
            "UPDATE ingest_jobs SET status = 'running', finished_at = NULL WHERE job_id = %s",
            (job_id,),
        )
        conn.commit()
    return run_ingest_job(job_id, manifest_path)
