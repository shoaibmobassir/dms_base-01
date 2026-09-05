"""API Router for High-Concurrency Review Engine (Map-Reduce-Verify)."""
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

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
async def run_review(req: RunReviewRequest) -> dict[str, Any]:
    """Trigger high-concurrency Map -> Reduce -> Verify review across candidate documents."""
    res = await review_engine.run_review(
        title=req.title,
        matter_id=req.matter_id,
        document_ids=req.document_ids,
        requested_features=req.features,
        query_text=req.query,
        member_id=req.member_id,
    )
    return res.to_dict()


@router.get("/{job_id}")
def get_review_job(job_id: str) -> dict[str, Any]:
    """Retrieve review job details and executive summary."""
    with connect() as conn:
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
                """
                SELECT severity, COUNT(*) as count
                FROM findings
                WHERE review_job_id = %(jid)s
                GROUP BY severity
                """,
                {"jid": job_id},
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
) -> dict[str, Any]:
    """Retrieve verified findings with durable evidence anchors for a review job."""
    with connect() as conn:
        with conn.cursor() as cur:
            query = """
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
                WHERE f.review_job_id = %(jid)s
            """
            params: dict[str, Any] = {"jid": job_id, "limit": limit}

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
def update_finding_status(finding_id: str, update: FindingStatusUpdate) -> dict[str, Any]:
    """Update finding status (e.g. accepted, dismissed, reviewed)."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE findings SET
                    status = %(status)s,
                    updated_at = NOW()
                WHERE finding_id = %(fid)s
                RETURNING *
                """,
                {"status": update.status, "fid": finding_id},
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Finding not found")
            conn.commit()
            return dict(row)
