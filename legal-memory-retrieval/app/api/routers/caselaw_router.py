"""
Case Law & Citation Verification API Router: Extraction, authority checks, and CourtListener lookups.
Clean-room independent implementation.
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.caselaw.citation_parser import get_citation_parser
from app.caselaw.courtlistener_client import get_courtlistener_client

router = APIRouter(tags=["Case Law & Citations"])


class ExtractCitationsRequest(BaseModel):
    text: str


class VerifyCitationRequest(BaseModel):
    citation: str


@router.get("/health")
async def health():
    return {"status": "ok", "service": "caselaw_citations"}


@router.post("/extract-citations")
async def extract_citations_from_text(req: ExtractCitationsRequest):
    """Extracts all legal case law and statutory citations from raw text or brief."""
    parser = get_citation_parser()
    citations = parser.extract_citations(req.text)
    return [
        {
            "raw": c.raw_citation,
            "normalized": c.normalized_citation,
            "reporter": c.reporter,
            "volume": c.volume,
            "page": c.page,
            "type": c.citation_type,
        }
        for c in citations
    ]


@router.post("/verify")
async def verify_citation(req: VerifyCitationRequest):
    """Verifies citation validity, precedential status, and court metadata via CourtListener."""
    client = get_courtlistener_client()
    opinion = await client.verify_citation(req.citation)
    if not opinion:
        raise HTTPException(status_code=404, detail="Citation authority not found")
    return {
        "citation": opinion.citation,
        "case_name": opinion.case_name,
        "court": opinion.court,
        "date_filed": opinion.date_filed,
        "precedential_status": opinion.precedential_status,
        "is_good_law": opinion.is_good_law,
        "summary": opinion.summary,
        "courtlistener_url": opinion.courtlistener_url,
    }
