"""Validate DMS portal eval dataset schema."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "dms_portal_dataset.jsonl"


def test_dms_dataset_schema() -> None:
    assert DATASET.exists(), "evals/dms_portal_dataset.jsonl missing"
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) >= 10
    for row in rows:
        assert "question_id" in row
        assert "question" in row
        assert "should_abstain" in row


def test_dms_dataset_has_negative_and_factual() -> None:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    types = {r.get("type") for r in rows}
    assert "negative" in types
    assert "factual" in types or "procedural" in types
