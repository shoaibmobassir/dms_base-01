#!/usr/bin/env python3
"""Scaffold DMS portal eval dataset from ingested real-filing documents."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from app.db.connection import connect

OUT = ROOT / "evals" / "dms_portal_dataset.jsonl"

SCAFFOLD = [
    {
        "question_id": "DMS-001",
        "type": "factual",
        "question": "Has MSEDCL argued floods constitute force majeure in APL 163/2018?",
        "expected_matter": "MTR-REAL-00001",
        "expected_documents_contain": ["MSEDCL", "APL"],
        "expected_tags": ["Force Majeure", "Flood Damage"],
        "should_abstain": False,
    },
    {
        "question_id": "DMS-016",
        "type": "negative",
        "question": "Have we filed any patent applications for AI technology?",
        "expected_documents_contain": [],
        "should_abstain": True,
    },
]


def main() -> None:
    real_docs: list[dict] = []
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT document_id, matter_id, title, document_type, source_uri
            FROM documents
            WHERE matter_id LIKE 'MTR-REAL-%'
            ORDER BY document_id
            """
        ).fetchall()
        real_docs = [dict(r) for r in rows]

    if OUT.exists():
        print(f"Dataset already exists: {OUT} ({sum(1 for _ in OUT.open())} rows)")
        print("Re-run with --force to overwrite scaffold only.")
        if "--force" not in sys.argv:
            return

    OUT.write_text("\n".join(json.dumps(q) for q in SCAFFOLD) + "\n", encoding="utf-8")
    print(f"Wrote scaffold to {OUT}")
    print(f"Ingested real docs in DB: {len(real_docs)}")
    for doc in real_docs:
        print(f"  {doc['document_id']} | {doc['matter_id']} | {doc['title'][:60]}")


if __name__ == "__main__":
    main()
