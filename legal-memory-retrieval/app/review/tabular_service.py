"""
Tabular Review Service: High-Throughput Batch Document Intelligence and Matrix Reviews.
Clean-room independent implementation.
"""

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import logging
from typing import Any, Dict, List, Optional
import uuid

from app.db.connection import connect
from app.llm.model_router import LLMMessage, get_model_router
from app.retrieval.engine import retrieve

logger = logging.getLogger(__name__)


@dataclass
class ReviewColumn:
    id: str
    label: str
    prompt: str
    data_type: str = "text"  # text | date | currency | boolean | choice
    options: List[str] = field(default_factory=list)


@dataclass
class CellResult:
    value: str
    confidence: float
    citations: List[str]
    reasoning: str
    is_overridden: bool = False
    status: str = "completed"  # pending | completed | error | abstained


class TabularReviewService:
    """Manages creation, execution, and updating of matrix document reviews."""

    def __init__(self):
        self.router = get_model_router()

    async def run_matrix_extraction(
        self,
        review_id: str,
        title: str,
        document_ids: List[str],
        columns: List[ReviewColumn],
        member_id: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Runs concurrent extraction for each (document, column) pair."""
        results: Dict[str, Dict[str, Any]] = {}
        semaphore = asyncio.Semaphore(5)  # Control concurrency

        async def _extract_cell(doc_id: str, col: ReviewColumn):
            async with semaphore:
                try:
                    # 1. Retrieve document content / chunks
                    retrieval_query = f"{col.prompt} in document {doc_id}"
                    with connect() as conn:
                        hits, _ = retrieve(
                            conn,
                            query=retrieval_query,
                            member_id=member_id,
                            k=5,
                        )
                    
                    # Filter hits to target document if present
                    doc_hits = [
                        h for h in hits
                        if h.get("doc_id") == doc_id or (h.get("doc_id") and h.get("doc_id").startswith(doc_id))
                    ]
                    if not doc_hits:
                        doc_hits = hits[:3]

                    if not doc_hits:
                        return doc_id, col.id, CellResult(
                            value="—",
                            confidence=0.0,
                            citations=[],
                            reasoning="No evidence retrieved for this document.",
                            status="abstained",
                        )

                    context_text = "\n\n".join(
                        f"[{h.get('chunk_id', 'CHK-0')} - {h.get('title', doc_id)}]: {h.get('snippet', h.get('text', ''))}"
                        for h in doc_hits
                    )
                    chunk_ids = [h.get("chunk_id", f"CHK-{i}") for i, h in enumerate(doc_hits)]


                    # 2. Extract structured cell value using LLM
                    system_prompt = (
                        "You are an expert legal review analyst. Extract the requested criterion from the provided legal text.\n"
                        "Respond strictly in JSON format with keys:\n"
                        "- 'value': the concise extracted answer (or 'Not Specified' if not in text)\n"
                        "- 'confidence': float between 0.0 and 1.0\n"
                        "- 'reasoning': short 1-sentence legal explanation\n"
                        "- 'cited_chunks': list of chunk IDs that support this finding."
                    )
                    user_prompt = (
                        f"Criterion to extract: {col.label}\n"
                        f"Instructions: {col.prompt}\n"
                        f"Expected Data Type: {col.data_type}\n\n"
                        f"Document Excerpts:\n{context_text}"
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
                        val = parsed.get("value", "Not Specified")
                        conf = float(parsed.get("confidence", 0.9))
                        reason = parsed.get("reasoning", "")
                        cits = [c for c in parsed.get("cited_chunks", chunk_ids) if c in chunk_ids]
                        if not cits:
                            cits = chunk_ids[:2]

                        return doc_id, col.id, CellResult(
                            value=str(val),
                            confidence=conf,
                            citations=cits,
                            reasoning=reason,
                            status="completed" if val != "Not Specified" else "abstained",
                        )
                    except Exception:
                        return doc_id, col.id, CellResult(
                            value=llm_resp.content[:100],
                            confidence=0.7,
                            citations=chunk_ids[:1],
                            reasoning="Direct extraction result.",
                            status="completed",
                        )
                except Exception as exc:
                    logger.error("Failed cell extraction for doc %s col %s: %s", doc_id, col.id, exc)
                    return doc_id, col.id, CellResult(
                        value="Error",
                        confidence=0.0,
                        citations=[],
                        reasoning=str(exc),
                        status="error",
                    )

        tasks = []
        for doc_id in document_ids:
            for col in columns:
                tasks.append(_extract_cell(doc_id, col))

        extracted_cells = await asyncio.gather(*tasks)

        for doc_id, col_id, cell_res in extracted_cells:
            if doc_id not in results:
                results[doc_id] = {}
            results[doc_id][col_id] = asdict(cell_res)

        return results


_tabular_service: Optional[TabularReviewService] = None


def get_tabular_service() -> TabularReviewService:
    global _tabular_service
    if _tabular_service is None:
        _tabular_service = TabularReviewService()
    return _tabular_service
