#!/usr/bin/env python3
"""P5.6-C5 — Theme-complete document resolution ablation.

C5.0  theme → all docs → document ceiling
C5.1  BM25 (OR) inside theme
C5.2  Vector inside theme
C5.3  BM25 + Vector RRF

No CE. THEME_SCOPED_DOCUMENT_RESOLVE stays off until gate.

Usage:
  .venv/bin/python evals/theme_scoped_doc_ablation.py
  .venv/bin/python evals/theme_scoped_doc_ablation.py --max-themes 1
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
os.environ.setdefault("THEME_SCOPED_DOCUMENT_RESOLVE", "off")
os.environ.setdefault("SEMANTIC_DOC_RESOLVE", "off")

from app.db.pool import acquire, close_pool, init_pool  # noqa: E402
from app.embeddings.minilm import MiniLMEmbedder  # noqa: E402
from app.query.understand import understand  # noqa: E402
from app.retrieval.matter_resolver import to_or_tsquery  # noqa: E402
from app.retrieval.theme_scoped import (  # noqa: E402
    resolve_theme_keys,
    rrf_merge_doc_lists,
    scope_reduction_ratio,
)
from app.storage.postgres import PgSearchStore, PgVectorStore  # noqa: E402
from evals.metrics import mrr, ndcg_at_k, recall_at_k  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

_embedder: MiniLMEmbedder | None = None
_search = PgSearchStore()
_vector = PgVectorStore()

KS = (5, 10, 20, 50, 100)


def _get_embedder() -> MiniLMEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = MiniLMEmbedder()
    return _embedder


def _hit(gold: set[str], ranked: list[str], k: int) -> float:
    return 1.0 if gold and set(ranked[:k]) & gold else 0.0


def _best_gold_rank(gold: set[str], ranked: list[str]) -> int | None:
    pos = {doc_id: i + 1 for i, doc_id in enumerate(ranked)}
    hits = [pos[g] for g in gold if g in pos]
    return min(hits) if hits else None


def _metrics(gold: set[str], ranked: list[str]) -> dict:
    out = {}
    for k in KS:
        out[f"R@{k}"] = round(recall_at_k(gold, ranked, k), 4)
        out[f"Hit@{k}"] = _hit(gold, ranked, k)
    out["mrr"] = round(mrr(gold, ranked), 4)
    out["ndcg@20"] = round(ndcg_at_k(gold, ranked, 20), 4)
    out["best_gold_rank"] = _best_gold_rank(gold, ranked)
    out["n_gold_in_candidates"] = len(gold & set(ranked))
    return out


async def corpus_doc_count() -> int:
    async with acquire() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT COUNT(*) AS n FROM documents")
            row = await cur.fetchone()
            return int(row["n"])


async def theme_scope(
    theme_keys: list[str],
    member_id: str | None,
) -> dict:
    """Return matter_ids and document_ids inside theme(s)."""
    if not theme_keys:
        return {
            "matter_ids": [],
            "document_ids": [],
            "n_matters": 0,
            "n_documents": 0,
        }
    sql = """
        SELECT m.matter_id, d.document_id
        FROM matters m
        JOIN permissions p ON p.matter_id = m.matter_id
        LEFT JOIN documents d ON d.matter_id = m.matter_id
        WHERE m.theme_key = ANY(%(themes)s)
          AND (
            (%(member_id)s::text IS NULL)
            OR p.restricted = FALSE
            OR %(member_id)s::text = ANY (p.allowed_members)
          )
    """
    async with acquire() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, {"themes": theme_keys, "member_id": member_id})
            rows = await cur.fetchall()
    matters = sorted({r["matter_id"] for r in rows})
    docs = sorted({r["document_id"] for r in rows if r.get("document_id")})
    return {
        "matter_ids": matters,
        "document_ids": docs,
        "n_matters": len(matters),
        "n_documents": len(docs),
    }


async def bm25_or_scoped(
    question: str,
    search_text: str,
    matter_ids: list[str],
    member_id: str | None,
    *,
    limit: int = 200,
) -> list[dict]:
    """OR-style FTS over chunks restricted to theme matters."""
    if not matter_ids:
        return []
    from app.retrieval.matter_resolver import build_matter_query_rep

    rep = build_matter_query_rep(question, search_text=search_text)
    tsq = to_or_tsquery(rep.lexical_terms(), max_terms=20)
    if not tsq:
        # fallback AND plainto
        async with acquire() as conn:
            rows = await _search.search(
                conn, search_text or question, member_id, limit=limit,
                filters={"matter_ids": matter_ids},
            )
        return [
            {"document_id": r["document_id"], "matter_id": r["matter_id"],
             "score": float(r.get("score") or 0), "channel": "bm25"}
            for r in rows
        ]

    sql = """
        SELECT d.document_id, d.matter_id, d.title,
               MAX(ts_rank_cd(c.tsv, to_tsquery('english', %(tsquery)s))) AS score
        FROM chunks c
        JOIN documents d ON d.document_id = c.document_id
        JOIN permissions p ON p.matter_id = c.matter_id
        WHERE d.matter_id = ANY(%(matter_ids)s)
          AND c.tsv @@ to_tsquery('english', %(tsquery)s)
          AND (
            (%(member_id)s::text IS NULL)
            OR p.restricted = FALSE
            OR %(member_id)s::text = ANY (p.allowed_members)
          )
        GROUP BY d.document_id, d.matter_id, d.title
        ORDER BY score DESC
        LIMIT %(limit)s
    """
    async with acquire() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                sql,
                {
                    "tsquery": tsq,
                    "matter_ids": matter_ids,
                    "member_id": member_id,
                    "limit": limit,
                },
            )
            rows = list(await cur.fetchall())
    return [
        {
            "document_id": r["document_id"],
            "matter_id": r["matter_id"],
            "score": float(r.get("score") or 0),
            "channel": "bm25_or",
        }
        for r in rows
    ]


async def vector_scoped(
    question: str,
    matter_ids: list[str],
    member_id: str | None,
    *,
    limit: int = 200,
    chunk_pool: int = 5000,
) -> list[dict]:
    """Chunk-vector over theme matters, then collapse to documents.

    ``chunk_pool`` must be >> limit so unique-document coverage is meaningful
    inside themes of ~2k–4k documents.
    """
    if not matter_ids:
        return []
    qvec = _get_embedder().encode([question])[0]
    vec = qvec.tolist() if hasattr(qvec, "tolist") else list(qvec)
    async with acquire() as conn:
        rows = await _vector.search(
            conn, vec, member_id, limit=chunk_pool,
            filters={"matter_ids": matter_ids},
        )
    # Deduplicate by document, keep best chunk score
    best: dict[str, dict] = {}
    for r in rows:
        did = r["document_id"]
        score = float(r.get("score") or 0)
        prev = best.get(did)
        if prev is None or score > prev["score"]:
            best[did] = {
                "document_id": did,
                "matter_id": r["matter_id"],
                "score": score,
                "channel": "vector",
            }
    ordered = sorted(best.values(), key=lambda x: x["score"], reverse=True)
    return ordered[:limit]


async def run_one(
    q: dict,
    *,
    max_themes: int,
    corpus_docs: int,
) -> dict:
    question = q["question"]
    gold = set(q.get("expected_documents") or [])
    member_id = q.get("as_member") or q.get("as_user")
    parsed = understand(question)
    intent = resolve_theme_keys(
        question,
        search_text=parsed.search_text,
        practice_area=parsed.practice_area,
        max_themes=max_themes,
    )
    scope = await theme_scope(intent.theme_keys, member_id)
    scoped_set = set(scope["document_ids"])
    ceiling = (len(scoped_set & gold) / len(gold)) if gold else 0.0

    # C5.1 BM25 OR
    bm25 = await bm25_or_scoped(
        question, parsed.search_text or question, scope["matter_ids"], member_id,
        limit=500,
    )
    bm25_ranked = [r["document_id"] for r in bm25]

    # C5.2 Vector (chunk_pool large; keep top-500 docs for R@K)
    vec = await vector_scoped(
        question, scope["matter_ids"], member_id, limit=500, chunk_pool=8000,
    )
    vec_ranked = [r["document_id"] for r in vec]

    # C5.3 RRF union
    union = rrf_merge_doc_lists([bm25, vec], k=500, weights=[1.0, 1.0])
    union_ranked = [r["document_id"] for r in union]

    srr = scope_reduction_ratio(corpus_docs, scope["n_documents"])

    return {
        "query_id": q["question_id"],
        "question": question,
        "theme_keys": intent.theme_keys,
        "n_gold_docs": len(gold),
        "scope": {
            "n_matters": scope["n_matters"],
            "n_documents": scope["n_documents"],
            "scope_reduction_ratio": srr,
            "corpus_documents": corpus_docs,
        },
        "c5_0_ceiling": {
            "doc_recall_ceiling": round(ceiling, 4),
            "gold_in_scope": len(scoped_set & gold),
        },
        "c5_1_bm25": _metrics(gold, bm25_ranked) | {"n_candidates": len(bm25_ranked)},
        "c5_2_vector": _metrics(gold, vec_ranked) | {"n_candidates": len(vec_ranked)},
        "c5_3_union": _metrics(gold, union_ranked) | {"n_candidates": len(union_ranked)},
    }


async def run(max_themes: int) -> dict:
    dataset = ROOT / "evals" / "dataset.jsonl"
    questions = [
        json.loads(line)
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    semantic = [q for q in questions if q.get("type") == "semantic"]

    await init_pool()
    try:
        corpus_docs = await corpus_doc_count()
        rows = []
        for q in semantic:
            print(f"{q['question_id']}…", flush=True)
            row = await run_one(q, max_themes=max_themes, corpus_docs=corpus_docs)
            rows.append(row)
            print(
                f"  themes={row['theme_keys']} matters={row['scope']['n_matters']} "
                f"docs={row['scope']['n_documents']} SRR={row['scope']['scope_reduction_ratio']} "
                f"ceiling={row['c5_0_ceiling']['doc_recall_ceiling']} "
                f"bm25@20={row['c5_1_bm25']['R@20']} vec@20={row['c5_2_vector']['R@20']} "
                f"union@20={row['c5_3_union']['R@20']}",
                flush=True,
            )
    finally:
        await close_pool()

    def avg(path: str) -> float:
        parts = path.split(".")
        vals = []
        for r in rows:
            cur: object = r
            for p in parts:
                cur = cur[p]  # type: ignore[index]
            if cur is not None:
                vals.append(float(cur))  # type: ignore[arg-type]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    summary = {
        "n": len(rows),
        "max_themes": max_themes,
        "avg_matters": avg("scope.n_matters"),
        "avg_documents": avg("scope.n_documents"),
        "avg_srr": avg("scope.scope_reduction_ratio"),
        "c5_0_ceiling": avg("c5_0_ceiling.doc_recall_ceiling"),
        "c5_1_bm25": {f"R@{k}": avg(f"c5_1_bm25.R@{k}") for k in KS}
        | {f"Hit@{k}": avg(f"c5_1_bm25.Hit@{k}") for k in (20, 50)}
        | {"avg_best_gold_rank": avg("c5_1_bm25.best_gold_rank")},
        "c5_2_vector": {f"R@{k}": avg(f"c5_2_vector.R@{k}") for k in KS}
        | {f"Hit@{k}": avg(f"c5_2_vector.Hit@{k}") for k in (20, 50)}
        | {"avg_best_gold_rank": avg("c5_2_vector.best_gold_rank")},
        "c5_3_union": {f"R@{k}": avg(f"c5_3_union.R@{k}") for k in KS}
        | {f"Hit@{k}": avg(f"c5_3_union.Hit@{k}") for k in (20, 50)}
        | {"mrr": avg("c5_3_union.mrr"), "ndcg@20": avg("c5_3_union.ndcg@20")},
    }

    # Gate (engineering targets from roadmap)
    union_r20 = summary["c5_3_union"]["R@20"]
    ceiling = summary["c5_0_ceiling"]
    gate = {
        "ceiling_ok": ceiling >= 0.95,
        "doc_r20_material": union_r20 > 0.05,
        "union_r20_target": 0.85,
        "union_r20_pass": union_r20 >= 0.85,
        "enable_theme_scoped": ceiling >= 0.95 and union_r20 >= 0.85,
        "ce_next": False,  # only after candidate gen works
    }

    return {
        "experiment": "P5.6-C5 theme-complete document resolution",
        "summary": summary,
        "gate": gate,
        "per_query": rows,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--max-themes", type=int, default=1)
    p.add_argument("--out", default="last_theme_scoped_doc")
    args = p.parse_args()

    print(f"=== P5.6-C5 max_themes={args.max_themes} ===", flush=True)
    payload = asyncio.run(run(args.max_themes))

    out = ROOT / "evals" / f"{args.out}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")

    s = payload["summary"]
    g = payload["gate"]
    md = [
        "# P5.6-C5 Theme-Complete Document Resolution",
        "",
        f"max_themes={args.max_themes}",
        "",
        f"Avg scope: **{s['avg_matters']:.0f} matters → {s['avg_documents']:.0f} docs** "
        f"(SRR **{s['avg_srr']:.1f}×**)",
        "",
        f"C5.0 document ceiling: **{s['c5_0_ceiling']:.3f}**",
        "",
        "| Stage | R@20 | Hit@20 | R@50 | Hit@50 | R@100 |",
        "| ----- | ---: | -----: | ---: | -----: | ----: |",
        f"| C5.1 BM25 OR | {s['c5_1_bm25']['R@20']:.3f} | {s['c5_1_bm25']['Hit@20']:.3f} | "
        f"{s['c5_1_bm25']['R@50']:.3f} | {s['c5_1_bm25']['Hit@50']:.3f} | {s['c5_1_bm25']['R@100']:.3f} |",
        f"| C5.2 Vector | {s['c5_2_vector']['R@20']:.3f} | {s['c5_2_vector']['Hit@20']:.3f} | "
        f"{s['c5_2_vector']['R@50']:.3f} | {s['c5_2_vector']['Hit@50']:.3f} | {s['c5_2_vector']['R@100']:.3f} |",
        f"| C5.3 Union RRF | {s['c5_3_union']['R@20']:.3f} | {s['c5_3_union']['Hit@20']:.3f} | "
        f"{s['c5_3_union']['R@50']:.3f} | {s['c5_3_union']['Hit@50']:.3f} | {s['c5_3_union']['R@100']:.3f} |",
        "",
        f"Gate enable THEME_SCOPED_DOCUMENT_RESOLVE: **{g['enable_theme_scoped']}** "
        f"(ceiling_ok={g['ceiling_ok']}, union_r20_pass={g['union_r20_pass']})",
        "",
        f"BM25 avg best-gold rank: **{s['c5_1_bm25'].get('avg_best_gold_rank')}**; "
        f"Vector avg best-gold rank: **{s['c5_2_vector'].get('avg_best_gold_rank')}**",
        "",
        "CE remains frozen until candidate generation clears.",
    ]
    (ROOT / "evals" / f"{args.out}.md").write_text("\n".join(md) + "\n")
    print(json.dumps({"summary": s, "gate": g}, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
