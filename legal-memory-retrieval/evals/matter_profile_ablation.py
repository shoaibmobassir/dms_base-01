#!/usr/bin/env python3
"""P5.6-C4 — Matter evidence profile ablation (holder ranking).

Diagnosis: holders are *scattered inside* theme clusters with identical
legal_issues — C1 lexical needs K≈75. C4 adds theme routing + field weights
+ optional in-matter document evidence.

Variants:
  c1_lexical_struct   — C1 baseline
  c4_theme            — theme_key filter / boost only
  c4_profile          — theme + practice + issues + title + parties
  c4_profile_doctype  — profile + document-type intent
  c4_profile_evidence — profile + in-matter doc BM25 evidence
  c4_combined         — all profile signals + doc evidence

Metrics: HolderCoverage@K, HolderHit@K, HolderMRR, Holder nDCG@K,
         median/p90 first-holder rank

Usage:
  .venv/bin/python evals/matter_profile_ablation.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

os.environ.setdefault("FUSION_POLICY", "p55_repair_ce_protect")
os.environ.setdefault("MATTER_SCOPE", "hard")
os.environ.setdefault("SEMANTIC_DOC_RESOLVE", "off")

from app.db.pool import acquire, close_pool, init_pool  # noqa: E402
from app.query.understand import understand  # noqa: E402
from app.retrieval.matter_profile import (  # noqa: E402
    build_query_evidence_intent,
    score_matter_profile,
)
from app.retrieval.matter_resolver import (  # noqa: E402
    holder_coverage,
    min_k_for_coverage,
    to_or_tsquery,
)
from app.storage.postgres import PgMatterStore  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

_matter = PgMatterStore()

VARIANTS = (
    "c1_lexical_struct",
    "c4_theme",
    "c4_profile",
    "c4_profile_doctype",
    "c4_profile_evidence",
    "c4_combined",
)


def holder_mrr(ranked_ids: list[str], holders: set[str]) -> float:
    for i, mid in enumerate(ranked_ids, start=1):
        if mid in holders:
            return 1.0 / i
    return 0.0


def holder_ndcg(ranked_ids: list[str], holders: set[str], k: int) -> float:
    if not holders:
        return 0.0
    dcg = 0.0
    for i, mid in enumerate(ranked_ids[:k], start=1):
        if mid in holders:
            dcg += 1.0 / math.log2(i + 1)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(k, len(holders)) + 1))
    return (dcg / ideal) if ideal else 0.0


def first_holder_rank(ranked_ids: list[str], holders: set[str]) -> int | None:
    for i, mid in enumerate(ranked_ids, start=1):
        if mid in holders:
            return i
    return None


async def gold_holders(gold_docs: set[str]) -> set[str]:
    async with acquire() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT DISTINCT matter_id FROM documents WHERE document_id = ANY(%s)",
                (list(gold_docs),),
            )
            return {r["matter_id"] for r in await cur.fetchall()}


async def rank_c1(question: str, member_id: str | None, k: int) -> list[dict]:
    from app.retrieval.matter_resolver import build_matter_query_rep

    parsed = understand(question)
    rep = build_matter_query_rep(
        question, search_text=parsed.search_text, practice_area=parsed.practice_area,
    )
    tsq = to_or_tsquery(rep.lexical_terms(), max_terms=20)
    if not tsq:
        return []
    async with acquire() as conn:
        rows = await _matter.search_lexical_or(
            conn, tsq, member_id, limit=k, practice_area=rep.practice_area,
        )
    return [
        {"matter_id": r["matter_id"], "score": float(r.get("score") or 0), "channel": "c1"}
        for r in rows
    ]


async def rank_profile(
    question: str,
    member_id: str | None,
    *,
    variant: str,
    pool: int = 400,
) -> list[dict]:
    parsed = understand(question)
    intent = build_query_evidence_intent(
        question, search_text=parsed.search_text, practice_area=parsed.practice_area,
    )
    tsq = to_or_tsquery(intent.rep.lexical_terms(), max_terms=20)
    evidence_tsq = None
    use_doctype = variant in {"c4_profile_doctype", "c4_combined"}
    use_evidence = variant in {"c4_profile_evidence", "c4_combined"}
    if use_evidence:
        evidence_tsq = to_or_tsquery(intent.rep.lexical_terms(), max_terms=16)

    # Candidate generation
    async with acquire() as conn:
        if variant == "c4_theme":
            rows = await _matter.fetch_evidence_profiles(
                conn, member_id,
                theme_keys=intent.theme_keys or None,
                practice_area=None if intent.theme_keys else parsed.practice_area,
                tsquery=None if intent.theme_keys else tsq,
                limit=pool,
            )
        else:
            # Prefer theme-scoped pool when known; else lexical OR pool
            rows = await _matter.fetch_evidence_profiles(
                conn, member_id,
                theme_keys=intent.theme_keys or None,
                practice_area=None if intent.theme_keys else parsed.practice_area,
                tsquery=tsq,
                evidence_tsquery=evidence_tsq,
                limit=pool,
            )
            if not rows and tsq:
                rows = await _matter.fetch_evidence_profiles(
                    conn, member_id, tsquery=tsq, evidence_tsquery=evidence_tsq, limit=pool,
                )

    if not use_doctype:
        intent.doc_type_targets = []

    weights = None
    if variant == "c4_theme":
        weights = {
            "theme": 50.0, "practice": 0.0, "legal_issue": 0.0, "title": 0.0,
            "party": 0.0, "doc_type": 0.0, "doc_evidence": 0.0, "lexical_base": 0.1,
        }
    elif variant == "c4_profile":
        weights = {
            "theme": 50.0, "practice": 8.0, "legal_issue": 6.0, "title": 4.0,
            "party": 3.0, "doc_type": 0.0, "doc_evidence": 0.0, "lexical_base": 1.0,
        }
    elif variant == "c4_profile_doctype":
        weights = {
            "theme": 50.0, "practice": 8.0, "legal_issue": 6.0, "title": 4.0,
            "party": 3.0, "doc_type": 5.0, "doc_evidence": 0.0, "lexical_base": 1.0,
        }
    elif variant == "c4_profile_evidence":
        weights = {
            "theme": 40.0, "practice": 6.0, "legal_issue": 5.0, "title": 3.0,
            "party": 2.0, "doc_type": 0.0, "doc_evidence": 20.0, "lexical_base": 1.0,
        }

    scored: list[dict] = []
    for row in rows:
        profile = {
            "theme_key": row.get("theme_key"),
            "practice_area": row.get("practice_area"),
            "legal_issues": row.get("legal_issues") or [],
            "title": row.get("title"),
            "client_name": row.get("client_name"),
            "opposing_party": row.get("opposing_party"),
            "document_types": row.get("document_types") or [],
            "doc_evidence_score": float(row.get("doc_evidence_score") or 0.0),
            "lexical_score": float(row.get("lexical_score") or 0.0),
        }
        total, parts = score_matter_profile(profile, intent, weights=weights)
        scored.append({
            "matter_id": row["matter_id"],
            "score": total,
            "parts": parts,
            "theme_key": row.get("theme_key"),
            "channel": variant,
        })
    scored.sort(key=lambda r: (-r["score"], r["matter_id"]))
    return scored


async def run(ks: list[int], variants: list[str]) -> dict:
    dataset = ROOT / "evals" / "dataset.jsonl"
    questions = [
        json.loads(line)
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    semantic = [q for q in questions if q.get("type") == "semantic"]
    max_k = max(ks)

    await init_pool()
    results: dict[str, list[dict]] = {v: [] for v in variants}
    try:
        for q in semantic:
            holders = await gold_holders(set(q.get("expected_documents") or []))
            member_id = q.get("as_member") or q.get("as_user")
            intent = build_query_evidence_intent(q["question"])
            print(
                f"{q['question_id']} holders={len(holders)} themes={intent.theme_keys}",
                flush=True,
            )
            for variant in variants:
                if variant == "c1_lexical_struct":
                    ranked = await rank_c1(q["question"], member_id, max(max_k, 200))
                else:
                    ranked = await rank_profile(
                        q["question"], member_id, variant=variant, pool=max(max_k, 400),
                    )
                ids = [r["matter_id"] for r in ranked]
                fhr = first_holder_rank(ids, holders)
                row = {
                    "query_id": q["question_id"],
                    "n_holders": len(holders),
                    "theme_keys": intent.theme_keys,
                    "n_ranked": len(ranked),
                    "first_holder_rank": fhr,
                    "holder_mrr": round(holder_mrr(ids, holders), 4),
                    "min_k_cov_0.9": min_k_for_coverage(ranked, holders, target=0.9, max_k=max_k),
                    "by_k": {},
                }
                for k in ks:
                    cov = holder_coverage(ranked, holders, k=k)
                    cov["holder_ndcg"] = round(holder_ndcg(ids, holders, k), 4)
                    row["by_k"][str(k)] = cov
                results[variant].append(row)
                print(
                    f"  {variant}: cov@20={row['by_k'].get('20',{}).get('holder_coverage')} "
                    f"cov@50={row['by_k'].get('50',{}).get('holder_coverage')} "
                    f"mrr={row['holder_mrr']} first={fhr} min_k_0.9={row['min_k_cov_0.9']}",
                    flush=True,
                )
    finally:
        await close_pool()

    def avg(rows: list[dict], getter) -> float:
        vals = [getter(r) for r in rows]
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    def percentile(vals: list[float], p: float) -> float | None:
        if not vals:
            return None
        vals = sorted(vals)
        idx = min(len(vals) - 1, max(0, int(math.ceil(p * len(vals)) - 1)))
        return vals[idx]

    summary = []
    for variant in variants:
        rows = results[variant]
        firsts = [r["first_holder_rank"] for r in rows if r["first_holder_rank"] is not None]
        entry = {
            "variant": variant,
            "holder_mrr": avg(rows, lambda r: r["holder_mrr"]),
            "median_first_holder_rank": statistics.median(firsts) if firsts else None,
            "p90_first_holder_rank": percentile([float(x) for x in firsts], 0.9),
            "pct_reach_cov_0.9": round(
                sum(1 for r in rows if r["min_k_cov_0.9"] is not None) / len(rows), 4
            ) if rows else 0.0,
            "avg_min_k_cov_0.9": avg(
                [r for r in rows if r["min_k_cov_0.9"] is not None],
                lambda r: r["min_k_cov_0.9"],
            ) if any(r["min_k_cov_0.9"] is not None for r in rows) else None,
            "ks": {},
        }
        for k in ks:
            entry["ks"][str(k)] = {
                "holder_coverage": avg(rows, lambda r, kk=k: r["by_k"][str(kk)]["holder_coverage"]),
                "holder_hit": avg(rows, lambda r, kk=k: r["by_k"][str(kk)]["holder_hit"]),
                "holder_ndcg": avg(rows, lambda r, kk=k: r["by_k"][str(kk)]["holder_ndcg"]),
            }
        summary.append(entry)

    return {
        "experiment": "P5.6-C4 matter evidence profiles",
        "diagnosis": {
            "holder_pattern": "scattered_within_theme",
            "note": "Holders share theme_key/legal_issues with non-holders; theme routing is the primary lift",
            "c1_holder_ranks": "min~1 med~50 p90~114 (scattered)",
        },
        "n_semantic": len(semantic),
        "ks": ks,
        "summary": summary,
        "per_variant": results,
        "gate": {
            "SEMANTIC_DOC_RESOLVE": "off until HolderCoverage@50 >= 0.90",
            "target_cov@50": 0.90,
            "target_cov@20": 0.70,
        },
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ks", default="5,10,20,50,100")
    p.add_argument("--variants", default=",".join(VARIANTS))
    p.add_argument("--out", default="last_matter_profile_ablation")
    args = p.parse_args()
    ks = [int(x) for x in args.ks.split(",") if x.strip()]
    variants = [x.strip() for x in args.variants.split(",") if x.strip()]

    print(f"=== P5.6-C4 matter profile ablation ===", flush=True)
    payload = asyncio.run(run(ks, variants))
    out = ROOT / "evals" / f"{args.out}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")

    md = [
        "# P5.6-C4 Matter Evidence Profiles",
        "",
        "Holder pattern: **scattered within theme** (identical legal_issues).",
        "",
        "| Variant | Cov@20 | Cov@50 | Cov@100 | MRR | nDCG@50 | Med first | P90 first | %≥0.9 |",
        "| ------- | -----: | -----: | ------: | --: | ------: | --------: | --------: | ----: |",
    ]
    for s in payload["summary"]:
        def g(k, key):
            return s["ks"].get(str(k), {}).get(key, 0)

        md.append(
            f"| {s['variant']} | {g(20,'holder_coverage'):.3f} | {g(50,'holder_coverage'):.3f} | "
            f"{g(100,'holder_coverage'):.3f} | {s['holder_mrr']:.3f} | {g(50,'holder_ndcg'):.3f} | "
            f"{s['median_first_holder_rank']} | {s['p90_first_holder_rank']} | {s['pct_reach_cov_0.9']:.2f} |"
        )
    md.append("")
    md.append("SEMANTIC_DOC_RESOLVE remains **off**.")
    (ROOT / "evals" / f"{args.out}.md").write_text("\n".join(md) + "\n")
    print(json.dumps({"summary": payload["summary"]}, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
