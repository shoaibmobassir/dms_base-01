#!/usr/bin/env python3
"""P5.6-B0 Semantic candidate survival — diagnosis only.

Freeze: P5.6-A hard matter scope + CE protect. Do not change matter routing.

Usage:
  .venv/bin/python evals/semantic_candidate_survival.py
  MATTER_SCOPE=hard FUSION_POLICY=p55_repair_ce_protect \\
    .venv/bin/python evals/semantic_candidate_survival.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

# Freeze production path for this diagnosis
os.environ.setdefault("FUSION_POLICY", "p55_repair_ce_protect")
os.environ.setdefault("MATTER_SCOPE", "hard")

from app.db.pool import close_pool, init_pool  # noqa: E402
from app.retrieval.semantic_survival import (  # noqa: E402
    aggregate_survival,
    semantic_survival_query,
)


async def run(limit: int | None) -> dict:
    dataset = ROOT / "evals" / "dataset.jsonl"
    questions = [
        json.loads(line)
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    semantic = [q for q in questions if q.get("type") == "semantic"]
    if limit is not None:
        semantic = semantic[:limit]

    await init_pool()
    rows = []
    try:
        for i, q in enumerate(semantic, start=1):
            gold_docs = set(q.get("expected_documents") or [])
            gold_matters = set(q.get("expected_matters") or [])
            print(f"[{i}/{len(semantic)}] {q['question_id']}: {q['question'][:70]}…", flush=True)
            row = await semantic_survival_query(
                q["question"],
                query_id=q["question_id"],
                member_id=q.get("as_member") or q.get("as_user"),
                gold_docs=gold_docs,
                gold_matters=gold_matters,
                k=20,
            )
            rows.append(row)
            u = row.union.recall.get("R@20") if row.union else None
            f = row.fusion.recall.get("R@20") if row.fusion else None
            c = row.ce.recall.get("R@20") if row.ce else None
            fin = row.final.recall.get("R@20") if row.final else None
            print(
                f"  intent={row.intent} drop={row.drop_stage} "
                f"union@20={u} fusion@20={f} ce@20={c} final@20={fin}",
                flush=True,
            )
    finally:
        await close_pool()

    agg = aggregate_survival(rows)
    payload = {
        "freeze": {
            "FUSION_POLICY": os.environ.get("FUSION_POLICY"),
            "MATTER_SCOPE": os.environ.get("MATTER_SCOPE"),
            "note": "P5.6-B0 diagnosis only — no matter routing / fusion / embedding changes",
        },
        "aggregate": agg,
        "per_query": [r.to_dict() for r in rows],
    }
    return payload


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--out",
        default="last_semantic_survival",
        help="Output stem under evals/",
    )
    args = p.parse_args()
    payload = asyncio.run(run(args.limit))

    out = ROOT / "evals" / f"{args.out}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # Compact markdown table for humans
    table = payload["aggregate"]["stage_table_R@20"]
    md_lines = [
        "# P5.6-B0 Semantic Candidate Survival",
        "",
        f"Outcome: **{payload['aggregate']['outcome']}**",
        "",
        payload["aggregate"]["guidance"],
        "",
        "| Stage | Semantic R@20 | Hit@20 |",
        "| ----- | ------------: | -----: |",
    ]
    hit = payload["aggregate"]["stage_table_Hit@20"]
    for stage in (
        "bm25", "vector", "metadata", "matter", "matter_scope",
        "hierarchical", "graph_seed", "union", "fusion", "ce", "final",
    ):
        r = table.get(stage)
        h = hit.get(stage)
        if r is None and h is None:
            continue
        md_lines.append(f"| {stage} | {r:.4f} | {h:.4f} |")
    md_lines.append("")
    md_lines.append("### Matter-level (theme clusters)")
    md_lines.append("")
    md_lines.append("| Stage | Matter R@20 | Matter Hit@20 |")
    md_lines.append("| ----- | ----------: | ------------: |")
    mtable = payload["aggregate"].get("matter_stage_table_R@20") or {}
    mhit = payload["aggregate"].get("matter_stage_table_Hit@20") or {}
    for stage in ("bm25", "vector", "matter", "union", "fusion", "ce", "final"):
        r = mtable.get(stage)
        h = mhit.get(stage)
        if r is None and h is None:
            continue
        md_lines.append(f"| {stage} | {r:.4f} | {h:.4f} |")
    md_lines.append("")
    md_lines.append(f"Drop stages: `{payload['aggregate']['drop_stage_counts']}`")
    md_path = ROOT / "evals" / f"{args.out}.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(json.dumps(payload["aggregate"], indent=2))
    print(f"\nwrote {out}")
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
