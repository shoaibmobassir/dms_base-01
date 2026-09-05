"""
Tabular Review API Router: Endpoints for Matrix Reviews, Real-Time Extraction, and Spreadsheet Exports.
Clean-room independent implementation.
"""

from typing import Any, Dict, List, Optional
import uuid
from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.review.spreadsheet_exporter import SpreadsheetExporter
from app.review.tabular_service import ReviewColumn, get_tabular_service

router = APIRouter(tags=["Tabular Reviews"])

# In-memory / cache store for reviews (persisted or in-flight)
_REVIEWS_DB: Dict[str, Dict[str, Any]] = {}


class ColumnSchema(BaseModel):
    id: str
    label: str
    prompt: str
    data_type: str = "text"
    options: List[str] = Field(default_factory=list)


class CreateTabularReviewRequest(BaseModel):
    title: str
    matter_id: Optional[str] = None
    document_ids: List[str]
    columns: List[ColumnSchema]
    model: Optional[str] = None
    provider: Optional[str] = None


class PatchCellRequest(BaseModel):
    value: str
    reasoning: Optional[str] = None


@router.get("/health")
async def health():
    return {"status": "ok", "service": "tabular_reviews"}


@router.post("/reviews")
async def create_and_run_tabular_review(
    req: CreateTabularReviewRequest,
    x_member_id: Optional[str] = Header(None),
):
    """Creates a new tabular review and triggers concurrent cell extraction."""
    review_id = f"REV-{uuid.uuid4().hex[:8].upper()}"
    tabular_svc = get_tabular_service()

    col_objs = [
        ReviewColumn(
            id=c.id,
            label=c.label,
            prompt=c.prompt,
            data_type=c.data_type,
            options=c.options,
        )
        for c in req.columns
    ]

    # Execute extraction
    cells_data = await tabular_svc.run_matrix_extraction(
        review_id=review_id,
        title=req.title,
        document_ids=req.document_ids,
        columns=col_objs,
        member_id=x_member_id,
        model=req.model,
        provider=req.provider,
    )

    review_record = {
        "review_id": review_id,
        "title": req.title,
        "matter_id": req.matter_id,
        "document_ids": req.document_ids,
        "columns": [c.dict() for c in req.columns],
        "cells": cells_data,
        "status": "completed",
        "member_id": x_member_id,
    }
    _REVIEWS_DB[review_id] = review_record

    return review_record


@router.get("/reviews")
async def list_tabular_reviews():
    """Lists all active and completed tabular reviews."""
    return list(_REVIEWS_DB.values())


@router.get("/reviews/{review_id}")
async def get_tabular_review(review_id: str):
    """Retrieves detailed matrix review results."""
    if review_id not in _REVIEWS_DB:
        raise HTTPException(status_code=404, detail="Review not found")
    return _REVIEWS_DB[review_id]


@router.patch("/reviews/{review_id}/cells/{doc_id}/{col_id}")
async def patch_cell_value(
    review_id: str,
    doc_id: str,
    col_id: str,
    req: PatchCellRequest,
):
    """Allows lawyers to override or verify an extracted cell value."""
    if review_id not in _REVIEWS_DB:
        raise HTTPException(status_code=404, detail="Review not found")
    
    rev = _REVIEWS_DB[review_id]
    if doc_id not in rev["cells"]:
        rev["cells"][doc_id] = {}
    
    rev["cells"][doc_id][col_id] = {
        "value": req.value,
        "confidence": 1.0,
        "citations": rev["cells"][doc_id].get(col_id, {}).get("citations", []),
        "reasoning": req.reasoning or "Human lawyer verified override",
        "is_overridden": True,
        "status": "completed",
    }
    return rev["cells"][doc_id][col_id]


@router.get("/reviews/{review_id}/export/xlsx")
async def export_review_xlsx(review_id: str):
    """Exports the tabular review into a styled Excel workbook with citations."""
    if review_id not in _REVIEWS_DB:
        raise HTTPException(status_code=404, detail="Review not found")

    rev = _REVIEWS_DB[review_id]
    rows = [{"document_id": d_id, "title": d_id} for d_id in rev["document_ids"]]
    
    xlsx_bytes = SpreadsheetExporter.export_xlsx(
        title=rev["title"],
        columns=rev["columns"],
        rows=rows,
        cells=rev["cells"],
    )

    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{review_id}_review.xlsx"'},
    )
