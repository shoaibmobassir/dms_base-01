#!/usr/bin/env python3
"""P5.4 retrieval diagnosis — stage ranks CSV (no fusion policy changes).

Usage (from legal-memory-retrieval/):

  .venv/bin/python evals/retrieval_diagnose.py
  .venv/bin/python evals/retrieval_diagnose.py --limit 40
  .venv/bin/python evals/retrieval_diagnose.py --types cross_document,graph_reasoning,matter_retrieval,negative

Writes:
  evals/last_retrieval_diagnose.csv
  evals/last_retrieval_diagnose_summary.json
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from app.retrieval.diagnose import (  # noqa: E402
    diagnose_query,
    per_query_ranking_stats,
    summarize_rows,
)


def _load_questions(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def _run(args: argparse.Namespace) -> dict:
    dataset = ROOT / "evals" / "dataset.jsonl"
    questions = _load_questions(dataset)
    if args.types:
        wanted = {t.strip() for t in args.types.split(",") if t.strip()}
        questions = [q for q in questions if q.get("type") in wanted]
    if args.limit and args.limit > 0:
        questions = questions[: args.limit]

    all_rows = []
    per_type_stats: dict[str, list[dict]] = defaultdict(list)
    drop_stage_counter: Counter = Counter()
    combo_counter: Counter = Counter()

    for i, q in enumerate(questions, start=1):
        member_id = q.get("as_member") or q.get("as_user")
        gold_docs = set(q.get("expected_documents") or [])
        gold_matters = set(q.get("expected_matters") or [])
        # Permission DENIED: treat leaked matter as "relevant" for false-positive analysis
        if q.get("expected_access") == "DENIED":
            gold_docs = set()
            gold_matters = set()

        result = await diagnose_query(
            q["question"],
            query_id=str(q.get("question_id") or f"Q{i}"),
            query_type=str(q.get("type") or ""),
            member_id=member_id,
            k=args.k,
            gold_docs=gold_docs,
            gold_matters=gold_matters,
        )
        all_rows.extend(result.rows)
        qstats = per_query_ranking_stats(result.rows)
        per_type_stats[result.query_type or "unknown"].append(qstats)

        summary = summarize_rows(result.rows)
        drop_stage_counter.update(summary.get("relevant_drop_stages") or {})
        combo_counter.update(summary.get("relevant_channel_combos") or {})

        if i % 25 == 0 or i == len(questions):
            print(f"diagnosed {i}/{len(questions)}", flush=True)

    # Write CSV
    stem = args.out or "last_retrieval_diagnose"
    out_csv = ROOT / "evals" / f"{stem}.csv"
    fieldnames = list(all_rows[0].to_dict().keys()) if all_rows else []
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row.to_dict())

    def avg(rows: list[dict], key: str) -> float:
        vals = [r[key] for r in rows if key in r]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    by_type = {
        t: {
            "n": len(rows),
            "hit@10": avg(rows, "hit@10"),
            "mrr": avg(rows, "mrr"),
            "relevant@1": avg(rows, "relevant@1"),
            "relevant@5": avg(rows, "relevant@5"),
            "relevant@10": avg(rows, "relevant@10"),
        }
        for t, rows in sorted(per_type_stats.items())
    }

    overall_rows = [s for stats in per_type_stats.values() for s in stats]
    negative_fp = None
    neg_questions = [q for q in questions if q.get("type") == "negative"]
    if neg_questions:
        neg_rows = [r for r in all_rows if r.query_type == "negative"]
        by_q: dict[str, list] = defaultdict(list)
        for r in neg_rows:
            by_q[str(r.query_id)].append(r)
        fp_hits = 0
        for q in neg_questions:
            qid = str(q.get("question_id") or "")
            rows = by_q.get(qid, [])
            if any(r.final_rank is not None and r.final_rank <= 10 for r in rows):
                fp_hits += 1
        n_neg = len(neg_questions)
        negative_fp = {
            "n": n_neg,
            "queries_with_any_hit@10": fp_hits,
            "abstain_rate@10": round(1.0 - (fp_hits / n_neg), 4) if n_neg else 0.0,
            "queries_with_zero_candidates": sum(
                1 for q in neg_questions if not by_q.get(str(q.get("question_id") or ""))
            ),
        }

    payload = {
        "n_queries": len(questions),
        "n_candidate_rows": len(all_rows),
        "k": args.k,
        "csv": str(out_csv.relative_to(ROOT)),
        "overall": {
            "hit@10": avg(overall_rows, "hit@10"),
            "mrr": avg(overall_rows, "mrr"),
            "relevant@1": avg(overall_rows, "relevant@1"),
            "relevant@5": avg(overall_rows, "relevant@5"),
            "relevant@10": avg(overall_rows, "relevant@10"),
        },
        "by_type": by_type,
        "negative_false_positives": negative_fp,
        "relevant_drop_stages": dict(drop_stage_counter),
        "relevant_channel_combos_top": dict(combo_counter.most_common(40)),
        "hypothesis": (
            "If fusion_or_hierarchy_channel dominates relevant_drop_stages, "
            "fix hierarchical/fusion policy (P5.5). If reranker dominates, "
            "defer to P5.8 — but still remove hierarchy score overrides first."
        ),
    }
    out_json = ROOT / "evals" / f"{stem}_summary.json"
    out_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return payload


def main() -> None:
    p = argparse.ArgumentParser(description="P5.4 retrieval stage-rank diagnosis")
    p.add_argument("--limit", type=int, default=0, help="Max questions (0 = all)")
    p.add_argument("--k", type=int, default=20, help="Final top-k kept")
    p.add_argument(
        "--types",
        type=str,
        default="",
        help="Comma-separated question types to include",
    )
    p.add_argument(
        "--out",
        type=str,
        default="last_retrieval_diagnose",
        help="Output stem under evals/ (writes {stem}.csv and {stem}_summary.json)",
    )
    args = p.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
