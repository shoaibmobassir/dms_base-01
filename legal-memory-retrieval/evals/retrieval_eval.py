#!/usr/bin/env python3
"""Retrieval-only eval. Does not score LLM answers."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from app.db.connection import connect
from app.retrieval.engine import parse_channels, retrieve
from evals.metrics import mrr, ndcg_at_k, recall_at_k


def main() -> None:
    channels = parse_channels(None)
    dataset = ROOT / "evals" / "dataset.jsonl"
    questions = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]

    by_type: dict[str, list[dict]] = defaultdict(list)
    overall = []

    with connect() as conn:
        for q in questions:
            member_id = q.get("as_member") or q.get("as_user")
            hits, _ = retrieve(conn, q["question"], member_id=member_id, k=20, channels=channels)
            ranked_docs = list(dict.fromkeys(h["document_id"] for h in hits))
            ranked_matters = list(dict.fromkeys(h["matter_id"] for h in hits))
            gold_docs = set(q.get("expected_documents") or [])
            gold_matters = set(q.get("expected_matters") or [])

            if q.get("expected_access") == "DENIED":
                leak = gold_docs | set(q.get("expected_matters_if_leaked") or [])
                # Gold is empty; any hit on the restricted matter is a leak.
                restricted_matter = None
                # question contains MTR-...
                for token in q["question"].split():
                    if token.startswith("MTR-"):
                        restricted_matter = token.rstrip("?")
                leaked = [m for m in ranked_matters if m == restricted_matter]
                scores = {
                    "recall@10": 1.0 if not leaked else 0.0,
                    "mrr": 1.0 if not leaked else 0.0,
                    "ndcg@10": 1.0 if not leaked else 0.0,
                    "leaked": bool(leaked),
                }
            elif q["type"] == "negative":
                scores = {
                    "recall@10": 1.0 if not ranked_docs else 0.0,
                    "mrr": 1.0 if not ranked_docs else 0.0,
                    "ndcg@10": 1.0 if not ranked_docs else 0.0,
                }
            elif gold_docs:
                scores = {
                    "recall@5": recall_at_k(gold_docs, ranked_docs, 5),
                    "recall@10": recall_at_k(gold_docs, ranked_docs, 10),
                    "recall@20": recall_at_k(gold_docs, ranked_docs, 20),
                    "hit@10": 1.0 if set(ranked_docs[:10]) & gold_docs else 0.0,
                    "mrr": mrr(gold_docs, ranked_docs),
                    "ndcg@10": ndcg_at_k(gold_docs, ranked_docs, 10),
                }
            else:
                scores = {
                    "recall@5": recall_at_k(gold_matters, ranked_matters, 5),
                    "recall@10": recall_at_k(gold_matters, ranked_matters, 10),
                    "recall@20": recall_at_k(gold_matters, ranked_matters, 20),
                    "hit@10": 1.0 if set(ranked_matters[:10]) & gold_matters else 0.0,
                    "mrr": mrr(gold_matters, ranked_matters),
                    "ndcg@10": ndcg_at_k(gold_matters, ranked_matters, 10),
                }

            row = {"question_id": q["question_id"], "type": q["type"], "level": q["level"], **scores}
            overall.append(row)
            by_type[q["type"]].append(row)

    def avg(rows: list[dict], key: str) -> float:
        vals = [r[key] for r in rows if key in r]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    summary = {
        "n": len(overall),
        "channels": channels,
        "baseline": "+".join(channels),
        "overall": {
            "recall@5": avg(overall, "recall@5"),
            "recall@10": avg(overall, "recall@10"),
            "recall@20": avg(overall, "recall@20"),
            "hit@10": avg(overall, "hit@10"),
            "mrr": avg(overall, "mrr"),
            "ndcg@10": avg(overall, "ndcg@10"),
        },
        "by_type": {
            t: {
                "n": len(rows),
                "recall@10": avg(rows, "recall@10"),
                "hit@10": avg(rows, "hit@10"),
                "mrr": avg(rows, "mrr"),
                "ndcg@10": avg(rows, "ndcg@10"),
            }
            for t, rows in sorted(by_type.items())
        },
    }
    out = ROOT / "evals" / "last_retrieval_run.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    runs = ROOT / "evals" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{'-'.join(channels)}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
