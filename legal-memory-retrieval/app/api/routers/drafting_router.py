"""
Drafting & Redline API Router: Clause analysis, deviation scoring, and native Word tracked changes generation.
Clean-room independent implementation.
"""

from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel

from app.drafting.clause_diff_service import get_clause_diff_service
from app.drafting.docx_redline_generator import DocxRedlineGenerator

router = APIRouter(tags=["Drafting & Redlining"])


class RedlineClauseRequest(BaseModel):
    clause_text: str
    clause_type: str = "Limitation of Liability / Indemnity"
    client_stance: str = "Customer / Disclosing Party"
    provider: Optional[str] = None
    model: Optional[str] = None


class GenerateTrackedDocxRequest(BaseModel):
    original_text: str
    revised_text: str
    title: str = "Redlined Agreement"
    author: str = "FirmOS AI Review"


@router.get("/health")
async def health():
    return {"status": "ok", "service": "drafting_redline"}


@router.post("/redline-clause")
async def redline_clause(
    req: RedlineClauseRequest,
    x_member_id: Optional[str] = Header(None),
):
    """Analyzes a clause against firm standards, rating risk and suggesting protective counter-wording."""
    svc = get_clause_diff_service()
    res = await svc.analyze_and_redline(
        clause_text=req.clause_text,
        clause_type=req.clause_type,
        client_stance=req.client_stance,
        member_id=x_member_id,
        provider=req.provider,
        model=req.model,
    )
    return {
        "original_clause": res.original_clause,
        "proposed_redline": res.proposed_redline,
        "risk_severity": res.risk_severity,
        "deviation_analysis": res.deviation_analysis,
        "counter_rationale": res.counter_rationale,
        "firm_precedent_chunk": res.firm_precedent_chunk,
    }


@router.post("/generate-docx-tracked")
async def generate_tracked_docx(req: GenerateTrackedDocxRequest):
    """Generates a downloadable Microsoft Word .docx file with native tracked changes (<w:ins>, <w:del>)."""
    generator = DocxRedlineGenerator(author=req.author)
    docx_bytes = generator.create_tracked_diff_docx(
        original_text=req.original_text,
        revised_text=req.revised_text,
        title=req.title,
    )

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="redline_review.docx"'},
    )
