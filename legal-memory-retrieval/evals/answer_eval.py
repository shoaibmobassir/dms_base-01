#!/usr/bin/env python3
"""Answer eval: abstention + citation grounding. Does not score LLM prose."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from app.answers.generate import answer_question
from app.db.connection import connect


def main() -> None:
    dataset = ROOT / "evals" / "dataset.jsonl"
    questions = [
        json.loads(line)
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    abstain_ok = 0
    abstain_n = 0
    cite_n = 0
    grounded_n = 0
    grounded_ok = 0

    with connect() as conn:
        for q in questions:
            qtype = q.get("type")
            access = q.get("expected_access")
            if qtype != "negative" and access != "DENIED":
                continue
            abstain_n += 1
            member_id = q.get("as_member") or q.get("as_user")
            out = answer_question(
                conn,
                q["question"],
                member_id=member_id,
                k=10,
                provider="extractive",
            )
            if out["abstained"] and not out["citations"]:
                abstain_ok += 1

        exact = [q for q in questions if q.get("type") == "exact"][:40]
        for q in exact:
            cite_n += 1
            member_id = q.get("as_member") or q.get("as_user")
            out = answer_question(
                conn,
                q["question"],
                member_id=member_id,
                k=10,
                provider="extractive",
            )
            retrieved = {str(h["document_id"]).upper() for h in out["hits"]}
            cited = {c.upper() for c in out["citations"]}
            if out["abstained"]:
                continue
            grounded_n += 1
            if cited and cited <= retrieved:
                grounded_ok += 1

    summary = {
        "abstention_n": abstain_n,
        "abstention_accuracy": round(abstain_ok / abstain_n, 4) if abstain_n else 0.0,
        "exact_sample_n": cite_n,
        "citation_grounded_n": grounded_n,
        "citation_grounding": round(grounded_ok / grounded_n, 4) if grounded_n else 0.0,
        "provider": "extractive",
    }
    out_path = ROOT / "evals" / "last_answer_run.json"
    out_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
