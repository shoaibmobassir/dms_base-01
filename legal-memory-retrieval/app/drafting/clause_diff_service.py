"""
Clause Diff & Legal Risk Analysis Service.
Clean-room independent implementation.
"""

from dataclasses import dataclass
import json
import logging
from typing import Any, Dict, List, Optional

from app.db.connection import connect
from app.llm.model_router import LLMMessage, get_model_router
from app.retrieval.engine import retrieve

logger = logging.getLogger(__name__)


@dataclass
class ClauseDiffResult:
    original_clause: str
    proposed_redline: str
    risk_severity: str  # low | medium | high | critical
    deviation_analysis: str
    counter_rationale: str
    firm_precedent_chunk: Optional[str] = None


class ClauseDiffService:
    """Analyzes contractual clauses against firm precedent standards and generates redlines."""

    def __init__(self):
        self.router = get_model_router()

    async def analyze_and_redline(
        self,
        clause_text: str,
        clause_type: str = "Limitation of Liability / Indemnity",
        client_stance: str = "Customer / Disclosing Party",
        member_id: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> ClauseDiffResult:
        # 1. Retrieve firm standard clause precedent from Knowledge Vault
        vault_query = f"Standard precedent {clause_type} market position"
        with connect() as conn:
            hits, _ = retrieve(
                conn,
                query=vault_query,
                member_id=member_id,
                k=3,
            )

        precedent_text = "\n\n".join(
            f"[{h.get('chunk_id', 'CHK-0')}]: {h.get('snippet', h.get('text', ''))}"
            for h in hits
        )
        precedent_chunk_id = hits[0].get("chunk_id") if hits else None


        # 2. LLM Risk Assessment and Redlining
        system_prompt = (
            "You are a senior partner specializing in commercial contracts.\n"
            "Analyze the proposed clause against market standards and firm precedent.\n"
            "Produce a structured JSON output with:\n"
            "- 'proposed_redline': the rewritten clause text with optimal protective wording\n"
            "- 'risk_severity': 'low' | 'medium' | 'high' | 'critical'\n"
            "- 'deviation_analysis': precise explanation of how the clause exposes the client\n"
            "- 'counter_rationale': strategic argument to present to opposing counsel."
        )

        user_prompt = (
            f"Clause Type: {clause_type}\n"
            f"Client Stance: {client_stance}\n\n"
            f"Target Clause to Review:\n\"{clause_text}\"\n\n"
            f"Firm Standard Precedents:\n{precedent_text}"
        )

        llm_resp = await self.router.complete(
            messages=[
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_prompt),
            ],
            provider=provider,
            model=model,
            json_mode=True,
        )

        try:
            parsed = json.loads(llm_resp.content)
            return ClauseDiffResult(
                original_clause=clause_text,
                proposed_redline=parsed.get("proposed_redline", clause_text),
                risk_severity=parsed.get("risk_severity", "medium"),
                deviation_analysis=parsed.get("deviation_analysis", "Review recommended."),
                counter_rationale=parsed.get("counter_rationale", "Standard market compromise."),
                firm_precedent_chunk=precedent_chunk_id,
            )
        except Exception:
            return ClauseDiffResult(
                original_clause=clause_text,
                proposed_redline=clause_text,
                risk_severity="medium",
                deviation_analysis="Standard clause requires review.",
                counter_rationale="Protect client interests.",
                firm_precedent_chunk=precedent_chunk_id,
            )


_clause_diff_service: Optional[ClauseDiffService] = None


def get_clause_diff_service() -> ClauseDiffService:
    global _clause_diff_service
    if _clause_diff_service is None:
        _clause_diff_service = ClauseDiffService()
    return _clause_diff_service
