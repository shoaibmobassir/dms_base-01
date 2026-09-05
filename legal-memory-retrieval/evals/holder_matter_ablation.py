#!/usr/bin/env python3
"""P5.6-C1 — Holder-matter resolution ablation.

Question: Can lexical OR + structured query + vector RRF get *holder*
matters (matters that contain gold documents) into top-K?

Does NOT enable SEMANTIC_DOC_RESOLVE. Does NOT touch CE / P5.6-A.

Variants:
  vector          — open chunk-vector → matter dedupe (C0 baseline)
  lexical         — OR FTS on matter metadata
  lexical_struct  — lexical with concept expansion
  vector_struct   — vector embed(original + concepts)
  hybrid          — RRF(lexical, vector)
  hybrid_struct   — RRF(lexical_struct, vector_struct)

Metric: HolderCoverage@K (= holders_found / n_holders)

Usage:
  .venv/bin/python evals/holder_matter_ablation.py
  .venv/bin/python evals/holder_matter_ablation.py --ks 5,10,20,50,100
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

os.environ.setdefault("FUSION_POLICY", "p55_repair_ce_protect")
os.environ.setdefault("MATTER_SCOPE", "hard")
os.environ.setdefault("SEMANTIC_DOC_RESOLVE", "off")

from app.db.pool import acquire, close_pool, init_pool  # noqa: E402
from app.embeddings.minilm import MiniLMEmbedder  # noqa: E402
from app.query.understand import understand  # noqa: E402
from app.retrieval.contracts import Candidate  # noqa: E402
from app.retrieval.matter_resolver import (  # noqa: E402
    build_matter_query_rep,
    holder_coverage,
    min_k_for_coverage,
    rrf_merge_matter_lists,
    to_or_tsquery,
    vector_matters_from_candidates,
)
from app.storage.postgres import PgMatterStore, PgVectorStore  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

_embedder: MiniLMEmbedder | None = None
_vector = PgVectorStore()
_matter = PgMatterStore()

VARIANTS = (
    "vector",
    "lexical",
    "lexical_struct",
    "vector_struct",
    "hybrid",
    "hybrid_struct",
)


def _get_embedder() -> MiniLMEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = MiniLMEmbedder()
    return _embedder


async def holder_matters_for_docs(gold_docs: set[str]) -> set[str]:
    if not gold_docs:
        return set()
    async with acquire() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT DISTINCT matter_id FROM documents WHERE document_id = ANY(%s)",
                (list(gold_docs),),
            )
            return {r["matter_id"] for r in await cur.fetchall()}


async def vector_matter_list(
    text: str,
    member_id: str | None,
    *,
    pool: int = 500,
    k: int = 200,
) -> list[dict]:
    qvec = _get_embedder().encode([text])[0]
    vec = qvec.tolist() if hasattr(qvec, "tolist") else list(qvec)
    async with acquire() as conn:
        rows = await _vector.search(conn, vec, member_id, limit=pool, filters=None)
    cands = [Candidate.from_db_row(r, "vector") for r in rows]
    return vector_matters_from_candidates(cands, k=k)


async def lexical_matter_list(
    rep,
    member_id: str | None,
    *,
    use_struct: bool,
    k: int = 200,
) -> list[dict]:
    terms = rep.lexical_terms() if use_struct else (
        [rep.search_text] + rep.terms[:12]
    )
    # Always include raw search tokens even without full concept expand
    if not use_struct:
        terms = rep.terms[:16] or [rep.search_text]
    tsquery = to_or_tsquery(terms if use_struct else terms, max_terms=20)
    if not tsquery:
        return []
    practice = rep.practice_area if use_struct else None
    async with acquire() as conn:
        rows = await _matter.search_lexical_or(
            conn, tsquery, member_id, limit=k, practice_area=practice,
        )
    return [
        {
            "matter_id": r["matter_id"],
            "matter_code": r.get("matter_code"),
            "title": r.get("title"),
            "practice_area": r.get("practice_area"),
            "client_name": r.get("client_name"),
            "score": float(r.get("score") or 0.0),
            "channel": "lexical",
        }
        for r in rows
    ]


async def resolve_variant(
    variant: str,
    question: str,
    member_id: str | None,
    *,
    pool_k: int = 200,
) -> list[dict]:
    parsed = understand(question)
    rep = build_matter_query_rep(
        question,
        search_text=parsed.search_text,
        practice_area=parsed.practice_area,
    )

    if variant == "vector":
        return await vector_matter_list(question, member_id, k=pool_k)
    if variant == "vector_struct":
        return await vector_matter_list(rep.vector_text(), member_id, k=pool_k)
    if variant == "lexical":
        return await lexical_matter_list(rep, member_id, use_struct=False, k=pool_k)
    if variant == "lexical_struct":
        return await lexical_matter_list(rep, member_id, use_struct=True, k=pool_k)
    if variant == "hybrid":
        lex = await lexical_matter_list(rep, member_id, use_struct=False, k=pool_k)
        vec = await vector_matter_list(question, member_id, k=pool_k)
        return rrf_merge_matter_lists([lex, vec], k=pool_k, weights=[1.0, 1.0])
    if variant == "hybrid_struct":
        lex = await lexical_matter_list(rep, member_id, use_struct=True, k=pool_k)
        vec = await vector_matter_list(rep.vector_text(), member_id, k=pool_k)
        return rrf_merge_matter_lists([lex, vec], k=pool_k, weights=[1.2, 1.0])
    raise ValueError(variant)


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
            gold_docs = set(q.get("expected_documents") or [])
            holders = await holder_matters_for_docs(gold_docs)
            member_id = q.get("as_member") or q.get("as_user")
            print(
                f"{q['question_id']} holders={len(holders)} docs={len(gold_docs)}",
                flush=True,
            )
            for variant in variants:
                ranked = await resolve_variant(
                    variant, q["question"], member_id, pool_k=max(max_k, 200),
                )
                row = {
                    "query_id": q["question_id"],
                    "question": q["question"],
                    "n_holders": len(holders),
                    "holder_ids": sorted(holders),
                    "n_ranked": len(ranked),
                    "min_k_cov_0.5": min_k_for_coverage(ranked, holders, target=0.5, max_k=max_k),
                    "min_k_cov_0.9": min_k_for_coverage(ranked, holders, target=0.9, max_k=max_k),
                    "by_k": {},
                }
                for k in ks:
                    cov = holder_coverage(ranked, holders, k=k)
                    row["by_k"][str(k)] = cov
                results[variant].append(row)
                c20 = row["by_k"].get("20") or row["by_k"].get(str(ks[0]))
                print(
                    f"  {variant}: cov@20={c20['holder_coverage'] if c20 else None} "
                    f"hit={c20['holder_hit'] if c20 else None} "
                    f"min_k_0.9={row['min_k_cov_0.9']}",
                    flush=True,
                )
    finally:
        await close_pool()

    def avg_cov(rows: list[dict], k: int, key: str) -> float:
        vals = [r["by_k"][str(k)][key] for r in rows if str(k) in r["by_k"]]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    summary = []
    for variant in variants:
        rows = results[variant]
        entry = {"variant": variant, "ks": {}}
        for k in ks:
            entry["ks"][str(k)] = {
                "holder_coverage": avg_cov(rows, k, "holder_coverage"),
                "holder_hit": avg_cov(rows, k, "holder_hit"),
                "holder_precision": avg_cov(rows, k, "holder_precision"),
            }
        # fraction of queries that reach 0.9 coverage within max_k
        reach = [r["min_k_cov_0.9"] for r in rows]
        reachable = [x for x in reach if x is not None]
        entry["pct_reach_cov_0.9"] = round(len(reachable) / len(rows), 4) if rows else 0.0
        entry["avg_min_k_cov_0.9"] = (
            round(sum(reachable) / len(reachable), 2) if reachable else None
        )
        summary.append(entry)

    return {
        "experiment": "P5.6-C1 holder-matter resolution",
        "n_semantic": len(semantic),
        "ks": ks,
        "summary": summary,
        "per_variant": results,
        "gate": {
            "note": "Promote toward C5 only if HolderCoverage@20 ≥ ~0.5 and climbing; C0 doc resolve stays off",
            "target_holder_coverage@20": 0.5,
            "target_holder_coverage@50": 0.9,
        },
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ks", default="5,10,20,50,100")
    p.add_argument("--variants", default=",".join(VARIANTS))
    p.add_argument("--out", default="last_holder_matter_ablation")
    args = p.parse_args()
    ks = [int(x.strip()) for x in args.ks.split(",") if x.strip()]
    variants = [x.strip() for x in args.variants.split(",") if x.strip()]

    print(f"=== P5.6-C1 holder-matter ablation ks={ks} variants={variants} ===", flush=True)
    payload = asyncio.run(run(ks, variants))

    out = ROOT / "evals" / f"{args.out}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")

    md = [
        "# P5.6-C1 Holder-Matter Resolution",
        "",
        "Metric: **HolderCoverage@K** = |holders ∩ top-K| / |holders|",
        "",
        "| Variant | Cov@5 | Cov@10 | Cov@20 | Cov@50 | Cov@100 | Hit@20 | % reach Cov≥0.9 |",
        "| ------- | ----: | -----: | -----: | -----: | ------: | -----: | --------------: |",
    ]
    for s in payload["summary"]:
        ks_map = s["ks"]

        def g(k: int, key: str = "holder_coverage") -> str:
            return f"{ks_map.get(str(k), {}).get(key, 0):.3f}"

        md.append(
            f"| {s['variant']} | {g(5)} | {g(10)} | {g(20)} | {g(50)} | {g(100)} | "
            f"{g(20, 'holder_hit')} | {s['pct_reach_cov_0.9']:.2f} |"
        )
    md.append("")
    md.append("SEMANTIC_DOC_RESOLVE remains **off**.")
    md_path = ROOT / "evals" / f"{args.out}.md"
    md_path.write_text("\n".join(md) + "\n")

    print(json.dumps({"summary": payload["summary"]}, indent=2))
    print(f"wrote {out}")
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
