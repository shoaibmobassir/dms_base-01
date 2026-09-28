"""API Router for High-Concurrency Review Engine (Map-Reduce-Verify)."""
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.acl import ACL_CLAUSE, doc_acl
from app.auth.deps import resolve_member
from app.db.connection import connect
from app.review import FEATURE_CATALOG, FastReviewEngine, review_engine

router = APIRouter(tags=["reviews"])


class RunReviewRequest(BaseModel):
    title: str = Field(default="Institutional Due Diligence Review")
    matter_id: Optional[str] = None
    document_ids: Optional[List[str]] = None
    features: Optional[List[str]] = None
    query: Optional[str] = None
    member_id: Optional[str] = None


class FindingStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(open|reviewed|accepted|dismissed)$")


@router.get("/health")
def reviews_health() -> dict[str, str]:
    return {"service": "reviews", "status": "ok"}



@router.get("/features")
def list_review_features() -> dict[str, Any]:
    """List catalog of legal review features available for due diligence scans."""
    return {
        "features": [f.to_dict() for f in FEATURE_CATALOG.values()],
        "count": len(FEATURE_CATALOG),
    }


@router.post("/run")
async def run_review(req: RunReviewRequest, member_id: str | None = Depends(resolve_member)) -> dict[str, Any]:
    """Trigger high-concurrency Map -> Reduce -> Verify review across candidate documents.

    The review runs as the signed-in member; a ``member_id`` in the body is ignored, so a caller
    cannot review documents under someone else's access.
    """
    res = await review_engine.run_review(
        title=req.title,
        matter_id=req.matter_id,
        document_ids=req.document_ids,
        requested_features=req.features,
        query_text=req.query,
        member_id=member_id,
    )
    return res.to_dict()


class BatchReviewRequest(BaseModel):
    document_ids: List[str] = Field(..., min_length=1, max_length=500)
    questions: List[str] = Field(..., min_length=1, max_length=10)
    mode: str = Field(default="full", pattern="^(full|screen)$")
    use_cache: bool = True


@router.post("/batch")
def run_batch_review(req: BatchReviewRequest, member_id: str | None = Depends(resolve_member)) -> dict[str, Any]:
    """Answer the same questions for every document in a set (app/review/batch.py).

    Access is the signed-in member's: documents they may not see are dropped, never reviewed.
    """
    from app.review.batch import review_documents

    with connect() as conn:
        return review_documents(conn, req.document_ids, req.questions, member_id, mode=req.mode, use_cache=req.use_cache)


def _require_job(conn, job_id: str, member_id: str | None) -> dict:
    """A review job is visible to the person who ran it and to people who can read its matter."""
    from app import access

    job = conn.execute("SELECT job_id, matter_id, created_by FROM review_jobs WHERE job_id = %s", (job_id,)).fetchone()
    if not job:
        raise HTTPException(status_code=404, detail="Review job not found")
    if member_id is None or job["created_by"] == member_id:
        return job
    if job["matter_id"] and access.matter_level(conn, member_id, job["matter_id"]) != "none":
        return job
    raise HTTPException(status_code=404, detail="Review job not found")


# Findings are shown only on documents the member may read (matter ACL + document privacy).
_FINDING_DOC_ACL = f"""
    EXISTS (SELECT 1 FROM documents fd LEFT JOIN permissions p ON p.matter_id = fd.matter_id
            WHERE fd.document_id = f.document_id AND {ACL_CLAUSE} AND {doc_acl('fd')})
"""


@router.get("/{job_id}")
def get_review_job(job_id: str, member_id: str | None = Depends(resolve_member)) -> dict[str, Any]:
    """Retrieve review job details and executive summary."""
    with connect() as conn:
        _require_job(conn, job_id, member_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_id, matter_id, title, features_requested, target_document_ids,
                       status, total_documents, relevant_documents_count, findings_count,
                       duration_ms, error_summary, created_by, created_at, completed_at
                FROM review_jobs
                WHERE job_id = %(jid)s
                """,
                {"jid": job_id},
            )
            job = cur.fetchone()
            if not job:
                raise HTTPException(status_code=404, detail="Review job not found")

            # Fetch findings count by severity
            cur.execute(
                f"""
                SELECT severity, COUNT(*) as count
                FROM findings f
                WHERE review_job_id = %(jid)s AND {_FINDING_DOC_ACL}
                GROUP BY severity
                """,
                {"jid": job_id, "member_id": member_id},
            )
            severity_counts = {r["severity"]: r["count"] for r in cur.fetchall()}

            return {
                "job": dict(job),
                "severity_summary": severity_counts,
            }


@router.get("/{job_id}/findings")
def get_review_findings(
    job_id: str,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = Query(default=100, le=500),
    member_id: str | None = Depends(resolve_member),
) -> dict[str, Any]:
    """Retrieve verified findings with durable evidence anchors for a review job."""
    with connect() as conn:
        _require_job(conn, job_id, member_id)
        with conn.cursor() as cur:
            query = f"""
                SELECT f.*,
                       d.title AS document_title,
                       COALESCE(
                           json_agg(
                               json_build_object(
                                   'anchor_id', a.anchor_id,
                                   'block_id', a.block_id,
                                   'page_number', a.page_number,
                                   'start_offset', a.start_offset,
                                   'end_offset', a.end_offset,
                                   'quoted_text', a.quoted_text,
                                   'text_hash', a.text_hash,
                                   'confidence', a.anchor_confidence,
                                   'tier', a.resolution_tier
                               )
                           ) FILTER (WHERE a.anchor_id IS NOT NULL), '[]'
                       ) AS evidence_anchors
                FROM findings f
                JOIN documents d ON d.document_id = f.document_id
                LEFT JOIN evidence_anchors a ON a.finding_id = f.finding_id
                WHERE f.review_job_id = %(jid)s AND {_FINDING_DOC_ACL}
            """
            params: dict[str, Any] = {"jid": job_id, "limit": limit, "member_id": member_id}

            if category:
                query += " AND f.category = %(cat)s"
                params["cat"] = category
            if severity:
                query += " AND f.severity = %(sev)s"
                params["sev"] = severity

            query += " GROUP BY f.finding_id, d.title ORDER BY f.created_at DESC LIMIT %(limit)s"

            cur.execute(query, params)
            findings = [dict(r) for r in cur.fetchall()]

            return {
                "job_id": job_id,
                "findings": findings,
                "count": len(findings),
            }


@router.patch("/findings/{finding_id}")
def update_finding_status(finding_id: str, update: FindingStatusUpdate,
                          member_id: str | None = Depends(resolve_member)) -> dict[str, Any]:
    """Update finding status (e.g. accepted, dismissed, reviewed) — on a document the member may read."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE findings f SET
                    status = %(status)s,
                    updated_at = NOW()
                WHERE finding_id = %(fid)s AND {_FINDING_DOC_ACL}
                RETURNING *
                """,
                {"status": update.status, "fid": finding_id, "member_id": member_id},
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Finding not found")
            conn.commit()
            return dict(row)
