#!/usr/bin/env python3
"""Exact-query failure taxonomy (P5.5.1).

Classifies each type=exact miss:
  A gold_never_retrieved
  B gold_rank_gt_10
  E same_matter_wrong_docs   (matter_id matches gold but doc ids differ)
  F duplicate_title_other_matter
  J other

Usage:
  .venv/bin/python evals/exact_failure_taxonomy.py
  .venv/bin/python evals/exact_failure_taxonomy.py --limit 50
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from app.db.connection import connect  # noqa: E402
from app.db.pool import init_pool, pool_stats  # noqa: E402
from app.query.understand import understand  # noqa: E402
from app.retrieval.engine_v2 import retrieve_async  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402


def _matter_for_docs(doc_ids: list[str]) -> dict[str, str]:
    if not doc_ids:
        return {}
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT document_id, matter_id, title FROM documents WHERE document_id = ANY(%(ids)s)",
                {"ids": doc_ids},
            )
            return {
                r["document_id"]: r["matter_id"] for r in cur.fetchall()
            }


def _titles_for_matters(matter_ids: list[str]) -> dict[str, str]:
    if not matter_ids:
        return {}
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT matter_id, title FROM matters WHERE matter_id = ANY(%(ids)s)",
                {"ids": list(matter_ids)},
            )
            return {r["matter_id"]: r["title"] for r in cur.fetchall()}


def classify(
    *,
    gold_docs: set[str],
    ranked: list[str],
    gold_matters: set[str],
    ranked_matters: dict[str, str],
    matter_titles: dict[str, str],
    search_text: str,
) -> str:
    gold_in_pool = [d for d in ranked if d in gold_docs]
    if not gold_in_pool:
        # Same matter as gold?
        got_matters = {ranked_matters.get(d) for d in ranked[:10] if ranked_matters.get(d)}
        if got_matters & gold_matters:
            return "E_same_matter_wrong_docs"
        # Duplicate title?
        gold_titles = {matter_titles.get(m, "") for m in gold_matters}
        got_titles = {matter_titles.get(m, "") for m in got_matters if m}
        if gold_titles & got_titles and search_text:
            return "F_duplicate_title_other_matter"
        return "A_gold_never_retrieved"
    best = min(ranked.index(d) for d in gold_in_pool) + 1
    if best > 10:
        return "B_gold_rank_gt_10"
    return "HIT"


async def run(limit: int) -> dict:
    if not pool_stats().get("initialized"):
        await init_pool()

    questions = [
        json.loads(line)
        for line in (ROOT / "evals" / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    exact = [q for q in questions if q.get("type") == "exact"]
    if limit > 0:
        exact = exact[:limit]

    rows = []
    taxonomy = Counter()
    hits = 0

    for i, q in enumerate(exact, start=1):
        gold = set(q.get("expected_documents") or [])
        parsed = understand(q["question"])
        cands, _lat = await retrieve_async(
            q["question"], member_id=q.get("as_member") or q.get("as_user"), k=50,
        )
        ranked = list(dict.fromkeys(c.document_id for c in cands))
        hit = bool(set(ranked[:10]) & gold)
        if hit:
            hits += 1
            label = "HIT"
        else:
            all_ids = list(gold) + ranked[:20]
            doc_matters = _matter_for_docs(all_ids)
            gold_matters = {doc_matters[d] for d in gold if d in doc_matters}
            matter_titles = _titles_for_matters(list(gold_matters | set(doc_matters.values())))
            label = classify(
                gold_docs=gold,
                ranked=ranked,
                gold_matters=gold_matters,
                ranked_matters=doc_matters,
                matter_titles=matter_titles,
                search_text=parsed.search_text,
            )
        taxonomy[label] += 1
        if label != "HIT":
            rows.append({
                "question_id": q.get("question_id"),
                "query": q["question"],
                "search_text": parsed.search_text,
                "label": label,
                "gold": sorted(gold)[:5],
                "top10": ranked[:10],
                "best_gold_rank": (
                    min((ranked.index(d) + 1) for d in gold if d in ranked)
                    if any(d in ranked for d in gold) else None
                ),
            })
        if i % 40 == 0:
            print(f"exact {i}/{len(exact)} hit@10={hits/i:.3f}", flush=True)

    summary = {
        "n": len(exact),
        "hit@10": round(hits / len(exact), 4) if exact else 0.0,
        "taxonomy": dict(taxonomy),
        "misses": rows,
    }
    out = ROOT / "evals" / "last_exact_taxonomy.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"n": summary["n"], "hit@10": summary["hit@10"], "taxonomy": summary["taxonomy"]}, indent=2))
    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()
    asyncio.run(run(args.limit))


if __name__ == "__main__":
    main()
