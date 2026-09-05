#!/usr/bin/env python3
"""P5.6-C0 — Vector matter → scoped document resolution ablation.

Question: Can vector-retrieved matters act as a reliable routing layer
for document retrieval?

  semantic query
       ↓
  open vector (wide)
       ↓
  top-K matters
       ↓
  documents INSIDE those matters
       ↓
  BM25 + vector (scoped) + document heads
       ↓
  Document R@20 / Hit@20

Usage:
  .venv/bin/python evals/semantic_doc_resolve_ablation.py
  .venv/bin/python evals/semantic_doc_resolve_ablation.py --ks 5,10,20,50
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

# Freeze P5.6-A / CE; C0 is isolated semantic routing
os.environ.setdefault("FUSION_POLICY", "p55_repair_ce_protect")
os.environ.setdefault("MATTER_SCOPE", "hard")

from app.db.pool import acquire, close_pool, init_pool  # noqa: E402
from app.embeddings.minilm import MiniLMEmbedder  # noqa: E402
from app.query.understand import understand  # noqa: E402
from app.retrieval.contracts import Candidate  # noqa: E402
from app.retrieval.semantic_resolve import (  # noqa: E402
    matter_ids_from_ranked,
    rank_matters_from_vector,
    routing_stats,
)
from app.storage.postgres import (  # noqa: E402
    PgMatterStore,
    PgSearchStore,
    PgVectorStore,
)

_embedder: MiniLMEmbedder | None = None
_vector = PgVectorStore()
_search = PgSearchStore()
_matter = PgMatterStore()


def _get_embedder() -> MiniLMEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = MiniLMEmbedder()
    return _embedder


def _recall(gold: set[str], ranked: list[str], k: int) -> float:
    if not gold:
        return 0.0
    return len(set(ranked[:k]) & gold) / len(gold)


def _hit(gold: set[str], ranked: list[str], k: int) -> float:
    return 1.0 if gold and set(ranked[:k]) & gold else 0.0


def _doc_rank(cands: list[Candidate]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for c in sorted(cands, key=lambda x: x.raw_score, reverse=True):
        if c.document_id and c.document_id not in seen:
            seen.add(c.document_id)
            out.append(c.document_id)
    return out


async def _vector_open(
    query: str,
    member_id: str | None,
    limit: int = 300,
) -> list[Candidate]:
    """Open-corpus vector without VECTOR_MIN_SCORE (matter discovery)."""
    qvec = _get_embedder().encode([query])[0]
    async with acquire() as conn:
        rows = await _vector.search(
            conn,
            qvec.tolist() if hasattr(qvec, "tolist") else list(qvec),
            member_id,
            limit=limit,
            filters=None,
        )
    return [Candidate.from_db_row(r, "vector") for r in rows]


async def _docs_in_matters(
    matter_ids: list[str],
    member_id: str | None,
    limit: int = 2000,
) -> tuple[list[Candidate], set[str]]:
    """All chunk-0 heads inside matters (not one-per-matter)."""
    if not matter_ids:
        return [], set()
    from psycopg.rows import dict_row

    sql = """
        SELECT d.document_id, d.matter_id, d.matter_code, d.title, d.document_type,
               d.author_name, d.doc_date,
               m.client_name, m.court, m.practice_area,
               c.chunk_id, c.chunk_index, c.text,
               1.0 AS score
        FROM documents d
        JOIN matters m ON m.matter_id = d.matter_id
        JOIN permissions p ON p.matter_id = d.matter_id
        JOIN chunks c ON c.document_id = d.document_id AND c.chunk_index = 0
        WHERE d.matter_id = ANY(%(matter_ids)s)
          AND (
            (%(member_id)s::text IS NULL)
            OR p.restricted = FALSE
            OR %(member_id)s::text = ANY (p.allowed_members)
          )
        ORDER BY d.matter_id, d.document_id
        LIMIT %(limit)s
    """
    params = {"matter_ids": matter_ids, "member_id": member_id, "limit": limit}
    async with acquire() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            rows = list(await cur.fetchall())
    all_ids = {r["document_id"] for r in rows}
    heads = [Candidate.from_db_row(r, "matter_scope") for r in rows]
    return heads, all_ids


async def _scoped_bm25(
    query: str,
    member_id: str | None,
    matter_ids: list[str],
    limit: int = 100,
) -> list[Candidate]:
    filters = {"matter_ids": matter_ids}
    async with acquire() as conn:
        rows = await _search.search(
            conn, query, member_id, limit=limit, filters=filters,
        )
    return [Candidate.from_db_row(r, "bm25") for r in rows]


async def _scoped_vector(
    query: str,
    member_id: str | None,
    matter_ids: list[str],
    limit: int = 100,
) -> list[Candidate]:
    qvec = _get_embedder().encode([query])[0]
    filters = {"matter_ids": matter_ids}
    async with acquire() as conn:
        rows = await _vector.search(
            conn,
            qvec.tolist() if hasattr(qvec, "tolist") else list(qvec),
            member_id,
            limit=limit,
            filters=filters,
        )
    return [Candidate.from_db_row(r, "vector") for r in rows]


async def run_c0_one(
    question: str,
    *,
    member_id: str | None,
    gold_docs: set[str],
    gold_matters: set[str],
    matter_k: int,
    vector_pool: int = 300,
) -> dict:
    parsed = understand(question)
    search = parsed.search_text or parsed.raw

    open_vec = await _vector_open(question, member_id, limit=vector_pool)
    ranked = rank_matters_from_vector(open_vec, k=matter_k)
    mids = matter_ids_from_ranked(ranked)

    heads, docs_in_scope = await _docs_in_matters(mids, member_id)
    route = routing_stats(ranked, gold_matters, gold_docs, docs_in_scope)

    bm25 = await _scoped_bm25(search, member_id, mids, limit=100)
    # Fallback: raw query if cleaned search empty
    if not bm25 and search != question:
        bm25 = await _scoped_bm25(question, member_id, mids, limit=100)
    scoped_vec = await _scoped_vector(question, member_id, mids, limit=100)

    # Union pool: heads + bm25 + scoped vector (dedupe by doc, keep best score)
    pool: dict[str, Candidate] = {}
    for c in heads + bm25 + scoped_vec:
        prev = pool.get(c.document_id)
        if prev is None or c.raw_score > prev.raw_score:
            pool[c.document_id] = c
    ranked_docs = _doc_rank(list(pool.values()))

    # Also: oracle rank = gold docs that exist in scope first, then rest
    # (ceiling already in route); for Doc R@20 use retrieved ranking
    return {
        "intent": parsed.intent,
        "search_text": search,
        "matter_k": matter_k,
        "n_open_vector": len(open_vec),
        "n_docs_in_scope": len(docs_in_scope),
        "n_heads": len(heads),
        "n_bm25": len(bm25),
        "n_scoped_vector": len(scoped_vec),
        "n_pool_docs": len(ranked_docs),
        "routing": route,
        "doc_R@5": round(_recall(gold_docs, ranked_docs, 5), 4),
        "doc_R@10": round(_recall(gold_docs, ranked_docs, 10), 4),
        "doc_R@20": round(_recall(gold_docs, ranked_docs, 20), 4),
        "doc_R@50": round(_recall(gold_docs, ranked_docs, 50), 4),
        "doc_Hit@10": _hit(gold_docs, ranked_docs, 10),
        "doc_Hit@20": _hit(gold_docs, ranked_docs, 20),
        "doc_recall_ceiling": route.get("doc_recall_ceiling"),
        "matter_recall@K": route["matter_recall"],
        "matter_Hit@K": route["matter_hit"],
        "matter_precision@K": route["matter_precision"],
    }


async def run_ablation(ks: list[int]) -> dict:
    dataset = ROOT / "evals" / "dataset.jsonl"
    questions = [
        json.loads(line)
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    semantic = [q for q in questions if q.get("type") == "semantic"]

    await init_pool()
    try:
        by_k: dict[str, list[dict]] = {str(k): [] for k in ks}
        # Baseline: open vector docs only (no matter routing) — Doc R@20 expect ~0
        baseline_rows = []
        for q in semantic:
            gold_docs = set(q.get("expected_documents") or [])
            gold_matters = set(q.get("expected_matters") or [])
            member_id = q.get("as_member") or q.get("as_user")
            open_vec = await _vector_open(q["question"], member_id, limit=300)
            ranked_docs = _doc_rank(open_vec)
            baseline_rows.append({
                "query_id": q["question_id"],
                "doc_R@20": round(_recall(gold_docs, ranked_docs, 20), 4),
                "doc_Hit@20": _hit(gold_docs, ranked_docs, 20),
                "n_pool_docs": len(ranked_docs),
            })

            for k in ks:
                print(f"  {q['question_id']} K={k}…", flush=True)
                row = await run_c0_one(
                    q["question"],
                    member_id=member_id,
                    gold_docs=gold_docs,
                    gold_matters=gold_matters,
                    matter_k=k,
                )
                row["query_id"] = q["question_id"]
                row["question"] = q["question"]
                by_k[str(k)].append(row)
    finally:
        await close_pool()

    def avg(rows: list[dict], key: str) -> float:
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    summary_rows = []
    for k in ks:
        rows = by_k[str(k)]
        summary_rows.append({
            "matter_k": k,
            "matter_recall@K": avg(rows, "matter_recall@K"),
            "matter_Hit@K": avg(rows, "matter_Hit@K"),
            "matter_precision@K": avg(rows, "matter_precision@K"),
            "doc_recall_ceiling": avg(rows, "doc_recall_ceiling"),
            "doc_R@20": avg(rows, "doc_R@20"),
            "doc_Hit@20": avg(rows, "doc_Hit@20"),
            "doc_R@10": avg(rows, "doc_R@10"),
            "doc_Hit@10": avg(rows, "doc_Hit@10"),
            "avg_docs_in_scope": avg(rows, "n_docs_in_scope"),
            "avg_pool_docs": avg(rows, "n_pool_docs"),
            "avg_bm25": avg(rows, "n_bm25"),
        })

    return {
        "experiment": "P5.6-C0 vector-matter → scoped documents",
        "n_semantic": len(semantic),
        "baseline_open_vector": {
            "doc_R@20": avg(baseline_rows, "doc_R@20"),
            "doc_Hit@20": avg(baseline_rows, "doc_Hit@20"),
        },
        "by_k": summary_rows,
        "per_query": by_k,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ks", default="5,10,20,50")
    p.add_argument("--out", default="last_semantic_doc_resolve")
    args = p.parse_args()
    ks = [int(x.strip()) for x in args.ks.split(",") if x.strip()]

    print(f"=== P5.6-C0 ablation ks={ks} ===", flush=True)
    payload = asyncio.run(run_ablation(ks))

    out = ROOT / "evals" / f"{args.out}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")

    md = [
        "# P5.6-C0 Semantic Document Resolution",
        "",
        "Question: Can vector-retrieved matters route document retrieval?",
        "",
        f"Baseline open-vector Doc R@20: **{payload['baseline_open_vector']['doc_R@20']}** "
        f"(Hit@20 {payload['baseline_open_vector']['doc_Hit@20']})",
        "",
        "| Matter K | Matter Hit@K | Matter R@K | Doc ceiling | Doc R@20 | Doc Hit@20 | Avg docs in scope |",
        "| -------: | -----------: | ---------: | ----------: | -------: | ---------: | ----------------: |",
    ]
    for row in payload["by_k"]:
        md.append(
            f"| {row['matter_k']} | {row['matter_Hit@K']:.3f} | "
            f"{row['matter_recall@K']:.3f} | {row['doc_recall_ceiling']:.3f} | "
            f"{row['doc_R@20']:.3f} | {row['doc_Hit@20']:.3f} | "
            f"{row['avg_docs_in_scope']:.0f} |"
        )
    md.append("")
    md_path = ROOT / "evals" / f"{args.out}.md"
    md_path.write_text("\n".join(md) + "\n")

    print(json.dumps({"baseline": payload["baseline_open_vector"], "by_k": payload["by_k"]}, indent=2))
    print(f"wrote {out}")
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
