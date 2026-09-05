"""
Word Add-in API Router: Endpoints for Word Taskpane, Auth Handoff, Selection Analysis, and Track-Changes Payload Delivery.
Clean-room independent implementation.
"""

from typing import Optional
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.auth.handoff import get_auth_handoff_service
from app.db.connection import connect
from app.drafting.clause_diff_service import get_clause_diff_service
from app.llm.model_router import LLMMessage, get_model_router
from app.retrieval.engine import retrieve

router = APIRouter(tags=["Word Add-in"])


class CreateTicketRequest(BaseModel):
    member_id: str
    email: Optional[str] = None


class ExchangeTicketRequest(BaseModel):
    ticket: str


class AnalyzeSelectionRequest(BaseModel):
    selection_text: str
    matter_id: Optional[str] = None
    action: str = "explain"  # explain | summarize | redline | find_precedents
    provider: Optional[str] = None
    model: Optional[str] = None


class DraftClauseRequest(BaseModel):
    instruction: str
    clause_type: str = "Indemnity / Liability"
    matter_id: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None


@router.get("/health")
async def health():
    return {"status": "ok", "service": "word_addin"}


@router.post("/handoff/ticket")
async def create_handoff_ticket(req: CreateTicketRequest):
    """Generates a short-lived one-time ticket from the web application."""
    svc = get_auth_handoff_service()
    ticket = svc.create_ticket(member_id=req.member_id, email=req.email)
    return {"ticket": ticket, "expires_in_seconds": svc.ttl}


@router.post("/handoff/exchange")
async def exchange_handoff_ticket(req: ExchangeTicketRequest):
    """Exchanges a one-time ticket for active session credentials in Word."""
    svc = get_auth_handoff_service()
    session = svc.exchange_ticket(req.ticket)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired handoff ticket")
    return session


@router.post("/analyze-selection")
async def analyze_word_selection(
    req: AnalyzeSelectionRequest,
    x_member_id: Optional[str] = Header(None),
):
    """Analyzes text currently selected by the lawyer in Microsoft Word."""
    if not req.selection_text.strip():
        raise HTTPException(status_code=400, detail="Selection cannot be empty")

    if req.action == "redline":
        diff_svc = get_clause_diff_service()
        res = await diff_svc.analyze_and_redline(
            clause_text=req.selection_text,
            member_id=x_member_id,
            provider=req.provider,
            model=req.model,
        )
        return {
            "action": "redline",
            "proposed_text": res.proposed_redline,
            "risk_severity": res.risk_severity,
            "rationale": res.deviation_analysis,
            "counter_argument": res.counter_rationale,
            "insert_mode": "track_changes",
        }

    # General AI analysis grounded in firm memory
    with connect() as conn:
        hits, _ = retrieve(
            conn,
            query=req.selection_text[:200],
            member_id=x_member_id,
            k=3,
        )
    evidence = "\n\n".join(
        f"[{h.get('chunk_id', 'CHK-0')}]: {h.get('snippet', h.get('text', ''))}"
        for h in hits
    )

    system_msg = "You are FirmOS Word Assistant. Provide concise, clear legal guidance on the selected text."
    user_msg = (
        f"Selected Text in Word:\n\"{req.selection_text}\"\n\n"
        f"Action Requested: {req.action}\n\n"
        f"Relevant Precedents:\n{evidence}"
    )

    router_inst = get_model_router()
    resp = await router_inst.complete(
        messages=[LLMMessage(role="system", content=system_msg), LLMMessage(role="user", content=user_msg)],
        provider=req.provider,
        model=req.model,
    )

    return {
        "action": req.action,
        "analysis": resp.content,
        "cited_chunks": [h.get("chunk_id", f"CHK-{i}") for i, h in enumerate(hits)],
    }


@router.post("/draft-clause")
async def draft_clause_for_word(
    req: DraftClauseRequest,
    x_member_id: Optional[str] = Header(None),
):
    """Drafts a ready-to-insert contract clause based on lawyer instruction and firm precedents."""
    with connect() as conn:
        hits, _ = retrieve(
            conn,
            query=f"Standard {req.clause_type} clause template",
            member_id=x_member_id,
            k=3,
        )
    evidence = "\n\n".join(
        f"[{h.get('chunk_id', 'CHK-0')}]: {h.get('snippet', h.get('text', ''))}"
        for h in hits
    )

    system_msg = (
        "You are a master contract drafter. Draft a precise, legally robust contract clause.\n"
        "Output ONLY the clause text ready to insert into Microsoft Word, followed by a brief 'Notes for Counsel' block."
    )
    user_msg = f"Instruction: {req.instruction}\nClause Type: {req.clause_type}\n\nPrecedents:\n{evidence}"

    router_inst = get_model_router()
    resp = await router_inst.complete(
        messages=[LLMMessage(role="system", content=system_msg), LLMMessage(role="user", content=user_msg)],
        provider=req.provider,
        model=req.model,
    )

    return {
        "clause_text": resp.content,
        "insert_mode": "replace_or_insert",
        "precedent_chunks": [h.get("chunk_id", f"CHK-{i}") for i, h in enumerate(hits)],
    }

