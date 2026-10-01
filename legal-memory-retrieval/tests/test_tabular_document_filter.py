"""Tabular review fills a cell only from the document in that row (plan 15, C2).

The old filter fell back to the first three hits of *any* document when the row's own
document had none, so a cell could be answered from another matter's text.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from app.review import tabular_service
from app.review.tabular_service import ReviewColumn, TabularReviewService


class _Router:
    def __init__(self):
        self.prompts: list[str] = []

    async def complete(self, messages, **_kw):
        self.prompts.append(messages[-1].content)
        return SimpleNamespace(content=json.dumps({"value": "30 days", "confidence": 0.9, "reasoning": "r", "cited_chunks": ["CHK-A1"]}))


def _run(monkeypatch, hits: list[dict]) -> tuple[dict, _Router]:
    monkeypatch.setattr(tabular_service, "retrieve", lambda conn, query, member_id, k: (hits, {}))
    service = TabularReviewService.__new__(TabularReviewService)
    service.router = _Router()
    column = ReviewColumn(id="notice", label="Notice period", prompt="What is the notice period?")
    out = asyncio.run(service.run_matrix_extraction("R1", "t", ["DOC-A"], [column], member_id="MEM-00001"))
    return out["DOC-A"]["notice"], service.router


def test_cell_abstains_when_only_other_documents_match(monkeypatch):
    other = [{"document_id": "DOC-B", "chunk_id": "CHK-B1", "title": "Other", "text": "Notice is 90 days."}]
    cell, router = _run(monkeypatch, other)
    assert cell["status"] == "abstained" and cell["value"] == "—"
    assert router.prompts == [], "no model call may see another document's text"


def test_cell_uses_only_its_own_document(monkeypatch):
    hits = [
        {"document_id": "DOC-B", "chunk_id": "CHK-B1", "title": "Other", "text": "Notice is 90 days."},
        {"document_id": "doc-a", "chunk_id": "CHK-A1", "title": "Mine", "text": "Notice is 30 days."},
    ]
    cell, router = _run(monkeypatch, hits)
    assert cell["value"] == "30 days"
    assert len(router.prompts) == 1
    assert "30 days" in router.prompts[0] and "90 days" not in router.prompts[0]
