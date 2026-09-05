#!/usr/bin/env python3
"""P5.6-C5.5 — Contextual chunk embedding ablation (A1/A2/A3).

Frozen baselines: C5.4-D lexical. Theme routing only. No CE / GraphRAG / fusion.

Variants:
  raw_max     — existing chunks.embedding + max agg (control)
  A1          — embedding_ctx + max
  A2          — embedding_ctx + top-3 mean
  A3          — embedding_ctx + top-5 mean

Query embedding uses the raw question only (isolate document representation).

Usage:
  .venv/bin/python scripts/embed_contextual.py --semantic-themes
  .venv/bin/python evals/contextual_chunk_ablation.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

os.environ.setdefault("FUSION_POLICY", "p55_repair_ce_protect")
os.environ.setdefault("MATTER_SCOPE", "hard")
os.environ.setdefault("THEME_SCOPED_DOCUMENT_RETRIEVAL", "off")
os.environ.setdefault("THEME_SCOPED_DOCUMENT_RESOLVE", "off")
os.environ.setdefault("SEMANTIC_DOC_RESOLVE", "off")

from app.db.pool import acquire, close_pool, init_pool  # noqa: E402
from app.embeddings.minilm import MiniLMEmbedder  # noqa: E402
from app.query.understand import understand  # noqa: E402
from app.retrieval.contextual_embed import (  # noqa: E402
    AggMethod,
    aggregate_chunk_scores,
    gold_vs_nongold_margins,
    percentile,
    type_stratified_top,
)
from app.retrieval.theme_scoped import resolve_theme_keys  # noqa: E402
from evals.metrics import mrr, ndcg_at_k, recall_at_k  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

KS = (5, 10, 20, 50, 100)
# Frozen C5.4-D reference (do not retune against this mid-run)
C54_FROZEN = {
    "variant": "C5.4-D",
    "theme_ceiling": 1.0,
    "typed_ceiling": 0.83,
    "R@20": 0.007,
    "Hit@100": 0.429,
    "avg_best_gold_rank": 147.0,
}

_embedder: MiniLMEmbedder | None = None


def _get_embedder() -> MiniLMEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = MiniLMEmbedder()
    return _embedder


def _hit(gold: set[str], ranked: list[str], k: int) -> float:
    return 1.0 if gold and set(ranked[:k]) & gold else 0.0


def _best_rank(gold: set[str], ranked: list[str]) -> int | None:
    pos = {d: i + 1 for i, d in enumerate(ranked)}
    hits = [pos[g] for g in gold if g in pos]
    return min(hits) if hits else None


def _metrics(gold: set[str], ranked: list[str]) -> dict:
    out = {f"R@{k}": round(recall_at_k(gold, ranked, k), 4) for k in KS}
    out.update({f"Hit@{k}": _hit(gold, ranked, k) for k in (10, 20, 50, 100)})
    out["mrr"] = round(mrr(gold, ranked), 4)
    out["ndcg@20"] = round(ndcg_at_k(gold, ranked, 20), 4)
    out["best_gold_rank"] = _best_rank(gold, ranked)
    out["n_gold_in_candidates"] = len(gold & set(ranked))
    return out


async def theme_scope(theme_keys: list[str]) -> dict:
    sql = """
        SELECT m.matter_id, d.document_id, d.document_type
        FROM matters m
        JOIN documents d ON d.matter_id = m.matter_id
        WHERE m.theme_key = ANY(%(themes)s)
    """
    async with acquire() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, {"themes": theme_keys})
            rows = await cur.fetchall()
    matters = sorted({r["matter_id"] for r in rows})
    docs = sorted({r["document_id"] for r in rows})
    typed = {
        r["document_id"]
        for r in rows
        if r.get("document_type") in {"Engagement Letter", "Initial Case Assessment"}
    }
    return {
        "matter_ids": matters,
        "document_ids": docs,
        "typed_ids": typed,
        "n_matters": len(matters),
        "n_documents": len(docs),
    }


async def ensure_ctx_column(conn) -> bool:
    async with conn.cursor() as cur:
        await cur.execute(
            "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding_ctx vector(384)"
        )
    return True


async def count_ctx(conn, matter_ids: list[str]) -> dict:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT COUNT(*) AS n,
                   COUNT(*) FILTER (WHERE embedding_ctx IS NOT NULL) AS with_ctx,
                   COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS with_raw
            FROM chunks
            WHERE matter_id = ANY(%(mids)s)
            """,
            {"mids": matter_ids},
        )
        return dict(await cur.fetchone())


async def search_chunks(
    conn,
    qvec: list[float],
    matter_ids: list[str],
    *,
    column: str,
    limit: int,
) -> list[dict]:
    if column not in {"embedding", "embedding_ctx"}:
        raise ValueError(column)
    sql = f"""
        SELECT c.chunk_id, c.document_id, c.matter_id, c.chunk_index,
               c.section_title, c.folder_path,
               d.title, d.document_type, d.folder_path AS doc_folder_path,
               1.0 - (c.{column} <=> %(qvec)s::vector) AS score
        FROM chunks c
        JOIN documents d ON d.document_id = c.document_id
        WHERE c.matter_id = ANY(%(matter_ids)s)
          AND c.{column} IS NOT NULL
        ORDER BY c.{column} <=> %(qvec)s::vector
        LIMIT %(limit)s
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            sql, {"qvec": qvec, "matter_ids": matter_ids, "limit": limit},
        )
        return list(await cur.fetchall())


def best_chunk_per_gold(
    gold: set[str], chunk_rows: list[dict],
) -> dict[str, dict]:
    best: dict[str, dict] = {}
    for r in chunk_rows:
        did = r["document_id"]
        if did not in gold:
            continue
        prev = best.get(did)
        if prev is None or float(r["score"]) > float(prev["score"]):
            best[did] = r
    return best


async def run_one(q: dict, *, chunk_limit: int, doc_limit: int) -> dict:
    question = q["question"]
    gold = set(q.get("expected_documents") or [])
    parsed = understand(question)
    intent = resolve_theme_keys(
        question,
        search_text=parsed.search_text,
        practice_area=parsed.practice_area,
        max_themes=1,
    )
    scope = await theme_scope(intent.theme_keys)
    scoped = set(scope["document_ids"])
    ceiling = (len(scoped & gold) / len(gold)) if gold else 0.0
    typed_ceil = (len(set(scope["typed_ids"]) & gold) / len(gold)) if gold else 0.0

    qvec = _get_embedder().encode([question])[0]

    async with acquire() as conn:
        await ensure_ctx_column(conn)
        cov = await count_ctx(conn, scope["matter_ids"])
        raw_chunks = await search_chunks(
            conn, qvec, scope["matter_ids"], column="embedding", limit=chunk_limit,
        )
        ctx_chunks = await search_chunks(
            conn, qvec, scope["matter_ids"], column="embedding_ctx", limit=chunk_limit,
        )

    variants: dict[str, dict] = {}
    diagnostics: dict[str, dict] = {}

    configs: list[tuple[str, list[dict], AggMethod]] = [
        ("raw_max", raw_chunks, "max"),
        ("A1", ctx_chunks, "max"),
        ("A2", ctx_chunks, "top3_mean"),
        ("A3", ctx_chunks, "top5_mean"),
    ]

    for name, chunks, method in configs:
        docs = aggregate_chunk_scores(chunks, method=method)[:doc_limit]
        ranked = [d["document_id"] for d in docs]
        gold_chunks = best_chunk_per_gold(gold, chunks)
        margins = gold_vs_nongold_margins(gold, docs, gold_chunks)
        variants[name] = _metrics(gold, ranked) | {
            "label": f"{'raw' if name.startswith('raw') else 'ctx'} + {method}",
            "n_chunk_hits": len(chunks),
            "n_doc_candidates": len(docs),
            "unique_docs_in_chunk_hits": len({c["document_id"] for c in chunks}),
        }
        diagnostics[name] = {
            "type_stratified": type_stratified_top(docs, gold, k=20),
            "gold": [asdict(g) for g in margins],
            "top_nongold": [
                {
                    "document_id": d["document_id"],
                    "rank": i + 1,
                    "score": round(d["score"], 4),
                    "document_type": d.get("document_type"),
                    "title": d.get("title"),
                    "best_chunk_id": d.get("best_chunk_id"),
                    "best_chunk_score": round(float(d.get("best_chunk_score") or 0), 4),
                }
                for i, d in enumerate(docs)
                if d["document_id"] not in gold
            ][:5],
        }

    return {
        "query_id": q["question_id"],
        "question": question,
        "theme_keys": intent.theme_keys,
        "n_gold": len(gold),
        "scope": {
            "n_matters": scope["n_matters"],
            "n_documents": scope["n_documents"],
            "chunk_coverage": cov,
        },
        "ceiling": round(ceiling, 4),
        "typed_ceiling": round(typed_ceil, 4),
        "variants": variants,
        "diagnostics": diagnostics,
    }


async def run(chunk_limit: int, doc_limit: int) -> dict:
    questions = [
        json.loads(line)
        for line in (ROOT / "evals" / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    semantic = [q for q in questions if q.get("type") == "semantic"]

    await init_pool()
    try:
        rows = []
        for q in semantic:
            print(f"{q['question_id']}…", flush=True)
            row = await run_one(q, chunk_limit=chunk_limit, doc_limit=doc_limit)
            rows.append(row)
            v = row["variants"]
            print(
                f"  theme={row['theme_keys']} ctx={row['scope']['chunk_coverage'].get('with_ctx')} "
                f"raw@20={v['raw_max']['R@20']} A1@20={v['A1']['R@20']} "
                f"A2@20={v['A2']['R@20']} A3@20={v['A3']['R@20']} "
                f"A1_best={v['A1']['best_gold_rank']}",
                flush=True,
            )
    finally:
        await close_pool()

    def avg(variant: str, key: str) -> float:
        vals = [
            float(r["variants"][variant][key])
            for r in rows
            if r["variants"][variant].get(key) is not None
        ]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    def rank_stats(variant: str) -> dict:
        vals = [
            float(r["variants"][variant]["best_gold_rank"])
            for r in rows
            if r["variants"][variant].get("best_gold_rank") is not None
        ]
        return {
            "avg_best_gold_rank": round(sum(vals) / len(vals), 4) if vals else None,
            "median_best_gold_rank": (
                None if not vals else round(sorted(vals)[len(vals) // 2], 4)
            ),
            "p90_best_gold_rank": (
                None if not vals else round(percentile(vals, 0.9) or 0, 4)
            ),
        }

    summary = {
        "n": len(rows),
        "avg_ceiling": round(sum(r["ceiling"] for r in rows) / len(rows), 4),
        "avg_typed_ceiling": round(sum(r["typed_ceiling"] for r in rows) / len(rows), 4),
        "c54_frozen": C54_FROZEN,
        "variants": {},
    }
    for name in ("raw_max", "A1", "A2", "A3"):
        summary["variants"][name] = {
            "label": rows[0]["variants"][name]["label"] if rows else name,
            **{f"R@{k}": avg(name, f"R@{k}") for k in KS},
            **{f"Hit@{k}": avg(name, f"Hit@{k}") for k in (10, 20, 50, 100)},
            "mrr": avg(name, "mrr"),
            "ndcg@20": avg(name, "ndcg@20"),
            **rank_stats(name),
        }

    a1_r20 = summary["variants"]["A1"]["R@20"]
    a1_r100 = summary["variants"]["A1"]["R@100"]
    gate = {
        "case_a_pass": a1_r20 >= 0.70,
        "case_b_partial": a1_r100 >= 0.50 and a1_r20 < 0.70,
        "case_c_fail": a1_r100 < 0.15,
        "beats_c54_r20": a1_r20 > C54_FROZEN["R@20"] + 0.05,
        "beats_raw_r20": a1_r20 > summary["variants"]["raw_max"]["R@20"] + 0.05,
        "enable_ctx_lane": False,
        "ce_next": False,
        "next": (
            "C5.6 hybrid" if a1_r20 >= 0.70
            else "tune aggregation / sections (B)" if a1_r100 >= 0.50
            else "inspect EL/ICA vs Research Memo representation"
        ),
    }

    return {
        "experiment": "P5.6-C5.5 contextual chunk embeddings A1/A2/A3",
        "summary": summary,
        "gate": gate,
        "per_query": rows,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--chunk-limit", type=int, default=2000)
    p.add_argument("--doc-limit", type=int, default=500)
    p.add_argument("--out", default="last_contextual_chunk")
    args = p.parse_args()

    print("=== P5.6-C5.5 contextual chunks A1/A2/A3 ===", flush=True)
    print(f"frozen C5.4-D R@20={C54_FROZEN['R@20']}", flush=True)
    payload = asyncio.run(run(args.chunk_limit, args.doc_limit))

    out = ROOT / "evals" / f"{args.out}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")

    s = payload["summary"]
    g = payload["gate"]
    md = [
        "# P5.6-C5.5 Contextual Chunk Embeddings (A1/A2/A3)",
        "",
        f"Frozen C5.4-D: R@20 **{C54_FROZEN['R@20']}**, Hit@100 **{C54_FROZEN['Hit@100']}**",
        "",
        f"Theme ceiling **{s['avg_ceiling']:.3f}**; typed ceiling **{s['avg_typed_ceiling']:.3f}**",
        "",
        "| Variant | R@20 | Hit@20 | R@50 | R@100 | MRR | avg best-gold |",
        "| ------- | ---: | -----: | ---: | ----: | --: | ------------: |",
    ]
    for name in ("raw_max", "A1", "A2", "A3"):
        x = s["variants"][name]
        md.append(
            f"| {name} {x['label']} | {x['R@20']:.3f} | {x['Hit@20']:.3f} | "
            f"{x['R@50']:.3f} | {x['R@100']:.3f} | {x['mrr']:.3f} | "
            f"{x.get('avg_best_gold_rank')} |"
        )
    md += [
        "",
        f"Gate: case_a={g['case_a_pass']} case_b={g['case_b_partial']} "
        f"case_c={g['case_c_fail']} beats_c54={g['beats_c54_r20']} → **{g['next']}**",
        "",
        "CE / GraphRAG / fusion remain frozen. Query text = raw question only.",
    ]
    (ROOT / "evals" / f"{args.out}.md").write_text("\n".join(md) + "\n")
    print(json.dumps({"summary": s, "gate": g}, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
