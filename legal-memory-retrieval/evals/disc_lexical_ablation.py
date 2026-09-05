#!/usr/bin/env python3
"""P5.6-C5.4 — Discriminative lexical document retrieval ablation.

Frozen: theme routing, CE, vector, GraphRAG, matter hard-scope production path.

Variants:
  A  current OR-BM25 (C5.1 baseline)
  B  discriminative tokens + field weights
  C  B + phrase/concept lanes
  D  C + soft EL/ICA type prior

Usage:
  .venv/bin/python evals/disc_lexical_ablation.py
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
os.environ.setdefault("THEME_SCOPED_DOCUMENT_RETRIEVAL", "off")
os.environ.setdefault("SEMANTIC_DOC_RESOLVE", "off")

from app.db.pool import acquire, close_pool, init_pool  # noqa: E402
from app.query.understand import understand  # noqa: E402
from app.retrieval.disc_lexical import (  # noqa: E402
    EL_ICA_TYPES,
    FieldWeights,
    build_disc_buckets,
    gold_diagnostics,
    score_documents_disc,
)
from app.retrieval.matter_resolver import build_matter_query_rep, to_or_tsquery  # noqa: E402
from app.retrieval.theme_scoped import resolve_theme_keys  # noqa: E402
from evals.metrics import mrr, recall_at_k  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

KS = (5, 10, 20, 50, 100)
VARIANTS = ("A", "B", "C", "D")


def _hit(gold: set[str], ranked: list[str], k: int) -> float:
    return 1.0 if gold and set(ranked[:k]) & gold else 0.0


def _best_rank(gold: set[str], ranked: list[str]) -> int | None:
    pos = {d: i + 1 for i, d in enumerate(ranked)}
    hits = [pos[g] for g in gold if g in pos]
    return min(hits) if hits else None


def _metrics(gold: set[str], ranked: list[str]) -> dict:
    out = {f"R@{k}": round(recall_at_k(gold, ranked, k), 4) for k in KS}
    out.update({f"Hit@{k}": _hit(gold, ranked, k) for k in (20, 50, 100)})
    out["mrr"] = round(mrr(gold, ranked), 4)
    out["best_gold_rank"] = _best_rank(gold, ranked)
    out["n_gold_in_candidates"] = len(gold & set(ranked))
    out["n_candidates"] = len(ranked)
    return out


async def theme_scope(theme_keys: list[str], member_id: str | None) -> dict:
    if not theme_keys:
        return {"matter_ids": [], "document_ids": [], "n_matters": 0, "n_documents": 0}
    sql = """
        SELECT m.matter_id, d.document_id, d.document_type
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
    docs = [r for r in rows if r.get("document_id")]
    doc_ids = sorted({r["document_id"] for r in docs})
    typed = {r["document_id"] for r in docs if r.get("document_type") in EL_ICA_TYPES}
    return {
        "matter_ids": matters,
        "document_ids": doc_ids,
        "typed_ids": typed,
        "n_matters": len(matters),
        "n_documents": len(doc_ids),
        "n_typed": len(typed),
    }


async def bm25_or_baseline(
    question: str,
    search_text: str,
    matter_ids: list[str],
    member_id: str | None,
    *,
    limit: int = 500,
) -> list[dict]:
    rep = build_matter_query_rep(question, search_text=search_text)
    tsq = to_or_tsquery(rep.lexical_terms(), max_terms=20)
    if not tsq or not matter_ids:
        return []
    sql = """
        SELECT d.document_id, d.matter_id, d.title, d.document_type,
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
        GROUP BY d.document_id, d.matter_id, d.title, d.document_type
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
            return list(await cur.fetchall())


async def run_one(q: dict, *, limit: int) -> dict:
    question = q["question"]
    gold = set(q.get("expected_documents") or [])
    member_id = q.get("as_member") or q.get("as_user")
    parsed = understand(question)
    intent = resolve_theme_keys(
        question,
        search_text=parsed.search_text,
        practice_area=parsed.practice_area,
        max_themes=1,
    )
    scope = await theme_scope(intent.theme_keys, member_id)
    scoped = set(scope["document_ids"])
    typed = set(scope["typed_ids"])
    ceiling = (len(scoped & gold) / len(gold)) if gold else 0.0
    typed_ceil = (len(typed & gold) / len(gold)) if gold else 0.0

    out: dict = {
        "query_id": q["question_id"],
        "question": question,
        "theme_keys": intent.theme_keys,
        "n_gold": len(gold),
        "scope": {
            "n_matters": scope["n_matters"],
            "n_documents": scope["n_documents"],
            "n_typed_el_ica": scope["n_typed"],
        },
        "ceiling": round(ceiling, 4),
        "typed_ceiling": round(typed_ceil, 4),
        "variants": {},
        "token_buckets": {},
        "diagnostics": {},
    }

    # A — OR-BM25 baseline
    a_rows = await bm25_or_baseline(
        question, parsed.search_text or question, scope["matter_ids"], member_id,
        limit=limit,
    )
    a_ranked = [r["document_id"] for r in a_rows]
    out["variants"]["A"] = _metrics(gold, a_ranked) | {
        "label": "OR-BM25 baseline",
        "candidate_reduction": round(
            1.0 - (len(a_ranked) / max(scope["n_documents"], 1)), 4
        ),
    }

    async with acquire() as conn:
        _rep, buckets = await build_disc_buckets(
            conn,
            question,
            search_text=parsed.search_text,
            matter_ids=scope["matter_ids"],
        )
        out["token_buckets"] = {
            "rare": buckets.rare[:12],
            "moderate": buckets.moderate[:12],
            "common": buckets.common[:12],
            "phrases": buckets.phrases[:8],
            "concepts": buckets.concepts[:8],
            "n_docs": buckets.n_docs,
            "term_df": {k: buckets.term_df[k] for k in list(buckets.term_df)[:16]},
        }

        # B — discriminative + field weights
        b_scored = await score_documents_disc(
            conn, scope["matter_ids"], buckets,
            use_phrase=False, use_concept=False, use_type_prior=False,
            member_id=member_id, limit=limit,
        )
        # C — + phrase/concept
        c_scored = await score_documents_disc(
            conn, scope["matter_ids"], buckets,
            use_phrase=True, use_concept=True, use_type_prior=False,
            member_id=member_id, limit=limit,
        )
        # D — + EL/ICA prior
        d_scored = await score_documents_disc(
            conn, scope["matter_ids"], buckets,
            use_phrase=True, use_concept=True, use_type_prior=True,
            member_id=member_id, limit=limit,
            weights=FieldWeights(),
        )

    for key, scored, label in (
        ("B", b_scored, "disc field-weighted"),
        ("C", c_scored, "disc + phrase/concept"),
        ("D", d_scored, "disc + phrase/concept + EL/ICA prior"),
    ):
        ranked = [s.document_id for s in scored]
        out["variants"][key] = _metrics(gold, ranked) | {
            "label": label,
            "candidate_reduction": round(
                1.0 - (len(ranked) / max(scope["n_documents"], 1)), 4
            ),
        }
        out["diagnostics"][key] = gold_diagnostics(gold, scored, top_nongold=3)[0]

    # A diagnostics: ranks only
    a_ranks = {r["document_id"]: i + 1 for i, r in enumerate(a_rows)}
    out["diagnostics"]["A"] = {
        "gold": [
            {
                "document_id": gid,
                "rank": a_ranks.get(gid),
                "missing_from_candidates": gid not in a_ranks,
            }
            for gid in sorted(gold)
        ],
        "top_nongold": [
            {
                "document_id": r["document_id"],
                "rank": i + 1,
                "title": r.get("title"),
                "document_type": r.get("document_type"),
                "score": float(r.get("score") or 0),
            }
            for i, r in enumerate(a_rows[:3])
        ],
    }
    return out


async def run(limit: int) -> dict:
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
            row = await run_one(q, limit=limit)
            rows.append(row)
            vs = row["variants"]
            print(
                f"  theme={row['theme_keys']} typed_ceil={row['typed_ceiling']} "
                f"A@20={vs['A']['R@20']} B@20={vs['B']['R@20']} "
                f"C@20={vs['C']['R@20']} D@20={vs['D']['R@20']} "
                f"D_best={vs['D']['best_gold_rank']}",
                flush=True,
            )
    finally:
        await close_pool()

    def avg(variant: str, key: str) -> float:
        vals = []
        for r in rows:
            v = r["variants"][variant].get(key)
            if v is not None:
                vals.append(float(v))
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    summary = {
        "n": len(rows),
        "avg_ceiling": round(sum(r["ceiling"] for r in rows) / len(rows), 4),
        "avg_typed_ceiling": round(sum(r["typed_ceiling"] for r in rows) / len(rows), 4),
        "variants": {},
    }
    for v in VARIANTS:
        summary["variants"][v] = {
            "label": rows[0]["variants"][v]["label"] if rows else v,
            **{f"R@{k}": avg(v, f"R@{k}") for k in KS},
            **{f"Hit@{k}": avg(v, f"Hit@{k}") for k in (20, 50, 100)},
            "mrr": avg(v, "mrr"),
            "avg_best_gold_rank": avg(v, "best_gold_rank"),
            "avg_candidates": avg(v, "n_candidates"),
        }

    d_r20 = summary["variants"]["D"]["R@20"]
    a_r20 = summary["variants"]["A"]["R@20"]
    gate = {
        "d_materially_above_a": d_r20 >= max(0.15, a_r20 + 0.10),
        "d_r20": d_r20,
        "a_r20": a_r20,
        "enable_theme_scoped_retrieval": False,  # still need ~0.85 later
        "next_if_d_fails": "C5.5 contextual document embeddings",
        "next_if_d_wins": "continue lexical weight ablation; then C5.6 hybrid",
        "ce_next": False,
    }

    return {
        "experiment": "P5.6-C5.4 discriminative lexical document retrieval",
        "summary": summary,
        "gate": gate,
        "per_query": rows,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--out", default="last_disc_lexical")
    args = p.parse_args()

    print("=== P5.6-C5.4 discriminative lexical ===", flush=True)
    payload = asyncio.run(run(args.limit))

    out = ROOT / "evals" / f"{args.out}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")

    s = payload["summary"]
    g = payload["gate"]
    md = [
        "# P5.6-C5.4 Discriminative Lexical Document Retrieval",
        "",
        f"Theme ceiling avg **{s['avg_ceiling']:.3f}**; typed (EL+ICA) ceiling **{s['avg_typed_ceiling']:.3f}**",
        "",
        "| Variant | R@20 | Hit@20 | R@50 | R@100 | MRR | avg best-gold |",
        "| ------- | ---: | -----: | ---: | ----: | --: | ------------: |",
    ]
    for v in VARIANTS:
        x = s["variants"][v]
        md.append(
            f"| {v} {x['label']} | {x['R@20']:.3f} | {x['Hit@20']:.3f} | "
            f"{x['R@50']:.3f} | {x['R@100']:.3f} | {x['mrr']:.3f} | "
            f"{x.get('avg_best_gold_rank')} |"
        )
    md += [
        "",
        f"Gate D materially > A: **{g['d_materially_above_a']}** "
        f"(D R@20={g['d_r20']}, A R@20={g['a_r20']})",
        "",
        f"If D fails → `{g['next_if_d_fails']}`",
        f"If D wins → `{g['next_if_d_wins']}`",
        "",
        "CE / vector / GraphRAG remain frozen.",
    ]
    (ROOT / "evals" / f"{args.out}.md").write_text("\n".join(md) + "\n")
    print(json.dumps({"summary": s, "gate": g}, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
