#!/usr/bin/env python3
"""P5.6-C5.5-D4/D5 — Role-family oracle ceilings + retrieval.

Oracle families are derived from gold document labels (no per-query hardcoding).

D4:
  A  theme → all docs                         (control ceiling)
  B  theme → oracle role-family docs          (family ceiling)
  +  type ceiling (EL/ICA) for comparison

D5:
  A  theme + raw vector
  B  role-family oracle + raw vector
  C  role-family oracle + contextual vector
  D  role-family oracle + lexical (OR-BM25)

Frozen: CE, GraphRAG, fusion, production flags off.

Usage:
  .venv/bin/python evals/role_family_oracle_ablation.py
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
os.environ.setdefault("THEME_SCOPED_DOCUMENT_RETRIEVAL", "off")
os.environ.setdefault("SEMANTIC_DOC_RESOLVE", "off")

from app.db.pool import acquire, close_pool, init_pool  # noqa: E402
from app.embeddings.minilm import MiniLMEmbedder  # noqa: E402
from app.query.understand import understand  # noqa: E402
from app.retrieval.contextual_embed import aggregate_chunk_scores  # noqa: E402
from app.retrieval.doc_profile import (  # noqa: E402
    EL_ICA_TYPES,
    document_types_for_families,
    infer_role_family,
    oracle_role_families_from_gold,
)
from app.retrieval.matter_resolver import build_matter_query_rep, to_or_tsquery  # noqa: E402
from app.retrieval.theme_scoped import resolve_theme_keys, rrf_merge_doc_lists  # noqa: E402
from evals.metrics import mrr, ndcg_at_k, recall_at_k  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

KS = (5, 10, 20, 50, 100)
C54 = {"R@20": 0.007, "label": "C5.4-D"}
C55 = {"R@20": 0.000, "label": "C5.5 contextual"}

_embedder: MiniLMEmbedder | None = None


def _get_embedder() -> MiniLMEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = MiniLMEmbedder()
    return _embedder


def _hit(gold: set[str], ranked: list[str], k: int) -> float:
    return 1.0 if gold and set(ranked[:k]) & gold else 0.0


def _best(gold: set[str], ranked: list[str]) -> int | None:
    pos = {d: i + 1 for i, d in enumerate(ranked)}
    hits = [pos[g] for g in gold if g in pos]
    return min(hits) if hits else None


def _metrics(gold: set[str], ranked: list[str]) -> dict:
    out = {f"R@{k}": round(recall_at_k(gold, ranked, k), 4) for k in KS}
    out.update({f"Hit@{k}": _hit(gold, ranked, k) for k in (20, 50, 100)})
    out["mrr"] = round(mrr(gold, ranked), 4)
    out["ndcg@20"] = round(ndcg_at_k(gold, ranked, 20), 4)
    out["best_gold_rank"] = _best(gold, ranked)
    out["n_candidates"] = len(ranked)
    return out


async def theme_docs(theme_keys: list[str]) -> list[dict]:
    async with acquire() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT d.document_id, d.matter_id, d.document_type, d.title
                FROM documents d
                JOIN matters m ON m.matter_id = d.matter_id
                WHERE m.theme_key = ANY(%(themes)s)
                """,
                {"themes": theme_keys},
            )
            rows = list(await cur.fetchall())
    for r in rows:
        r["role_family"] = infer_role_family(r.get("document_type"), title=r.get("title"))
    return rows


async def search_chunks(
    conn,
    qvec: list[float],
    matter_ids: list[str],
    document_ids: list[str] | None,
    *,
    column: str,
    limit: int,
) -> list[dict]:
    if column not in {"embedding", "embedding_ctx"}:
        raise ValueError(column)
    doc_clause = ""
    params: dict = {
        "qvec": qvec,
        "matter_ids": matter_ids,
        "limit": limit,
        "document_ids": document_ids or ["__none__"],
    }
    if document_ids is not None:
        doc_clause = "AND c.document_id = ANY(%(document_ids)s)"
    sql = f"""
        SELECT c.chunk_id, c.document_id, c.matter_id, c.chunk_index,
               d.title, d.document_type,
               1.0 - (c.{column} <=> %(qvec)s::vector) AS score
        FROM chunks c
        JOIN documents d ON d.document_id = c.document_id
        WHERE c.matter_id = ANY(%(matter_ids)s)
          AND c.{column} IS NOT NULL
          {doc_clause}
        ORDER BY c.{column} <=> %(qvec)s::vector
        LIMIT %(limit)s
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        return list(await cur.fetchall())


async def lexical_docs(
    question: str,
    search_text: str,
    matter_ids: list[str],
    document_ids: list[str] | None,
    *,
    limit: int = 500,
) -> list[dict]:
    rep = build_matter_query_rep(question, search_text=search_text)
    tsq = to_or_tsquery(rep.lexical_terms(), max_terms=20)
    if not tsq or not matter_ids:
        return []
    doc_clause = ""
    params: dict = {
        "tsquery": tsq,
        "matter_ids": matter_ids,
        "limit": limit,
        "document_ids": document_ids or ["__none__"],
    }
    if document_ids is not None:
        doc_clause = "AND d.document_id = ANY(%(document_ids)s)"
    sql = f"""
        SELECT d.document_id, d.matter_id, d.title, d.document_type,
               MAX(ts_rank_cd(c.tsv, to_tsquery('english', %(tsquery)s))) AS score
        FROM chunks c
        JOIN documents d ON d.document_id = c.document_id
        WHERE d.matter_id = ANY(%(matter_ids)s)
          AND c.tsv @@ to_tsquery('english', %(tsquery)s)
          {doc_clause}
        GROUP BY d.document_id, d.matter_id, d.title, d.document_type
        ORDER BY score DESC
        LIMIT %(limit)s
    """
    async with acquire() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            rows = list(await cur.fetchall())
    return [
        {
            "document_id": r["document_id"],
            "matter_id": r["matter_id"],
            "title": r.get("title"),
            "document_type": r.get("document_type"),
            "score": float(r.get("score") or 0),
            "channel": "bm25_or",
        }
        for r in rows
    ]


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
    docs = await theme_docs(intent.theme_keys)
    by_id = {d["document_id"]: d for d in docs}
    gold_meta = [by_id[g] for g in gold if g in by_id]

    # D4.1 oracle from gold labels
    oracle = oracle_role_families_from_gold(gold_meta)
    families = [x["family"] for x in oracle]
    allowed_types = set(document_types_for_families(families))

    theme_ids = {d["document_id"] for d in docs}
    type_ids = {d["document_id"] for d in docs if d.get("document_type") in EL_ICA_TYPES}
    family_ids = {d["document_id"] for d in docs if d.get("role_family") in set(families)}

    def ceiling(scope: set[str]) -> float:
        return (len(scope & gold) / len(gold)) if gold else 0.0

    ceilings = {
        "theme": round(ceiling(theme_ids), 4),
        "role_family": round(ceiling(family_ids), 4),
        "document_type_el_ica": round(ceiling(type_ids), 4),
        "n_theme": len(theme_ids),
        "n_role_family": len(family_ids),
        "n_el_ica": len(type_ids),
        "scope_reduction_theme_to_family": (
            round(len(theme_ids) / max(len(family_ids), 1), 2)
        ),
    }

    matter_ids = sorted({d["matter_id"] for d in docs})
    family_list = sorted(family_ids)
    qvec = _get_embedder().encode([question])[0]

    async with acquire() as conn:
        raw_theme = await search_chunks(
            conn, qvec, matter_ids, None, column="embedding", limit=chunk_limit,
        )
        raw_fam = await search_chunks(
            conn, qvec, matter_ids, family_list, column="embedding", limit=chunk_limit,
        )
        ctx_fam = await search_chunks(
            conn, qvec, matter_ids, family_list, column="embedding_ctx", limit=chunk_limit,
        )

    lex_fam = await lexical_docs(
        question, parsed.search_text or question, matter_ids, family_list, limit=doc_limit,
    )

    d5_a = aggregate_chunk_scores(raw_theme, method="max")[:doc_limit]
    d5_b = aggregate_chunk_scores(raw_fam, method="max")[:doc_limit]
    d5_c = aggregate_chunk_scores(ctx_fam, method="max")[:doc_limit]
    d5_d = lex_fam[:doc_limit]

    # Optional light hybrid for diagnostics (not weight-tuned)
    d5_e = rrf_merge_doc_lists([d5_d, d5_c], k=doc_limit, weights=[1.0, 1.0])

    variants = {
        "D5_A_theme_raw": _metrics(gold, [r["document_id"] for r in d5_a]) | {
            "label": "theme + raw vector",
        },
        "D5_B_family_raw": _metrics(gold, [r["document_id"] for r in d5_b]) | {
            "label": "role-family + raw vector",
        },
        "D5_C_family_ctx": _metrics(gold, [r["document_id"] for r in d5_c]) | {
            "label": "role-family + contextual vector",
        },
        "D5_D_family_lex": _metrics(gold, [r["document_id"] for r in d5_d]) | {
            "label": "role-family + lexical",
        },
        "D5_E_family_lex_ctx": _metrics(gold, [r["document_id"] for r in d5_e]) | {
            "label": "role-family + lexical∪ctx RRF",
        },
    }

    return {
        "query_id": q["question_id"],
        "question": question,
        "theme_keys": intent.theme_keys,
        "oracle_role_families": oracle,
        "allowed_document_types": sorted(allowed_types),
        "ceilings": ceilings,
        "variants": variants,
        "diagnostics": {
            "D5_C_top": [
                {
                    "document_id": r["document_id"],
                    "document_type": r.get("document_type"),
                    "score": round(float(r["score"]), 4),
                    "in_gold": r["document_id"] in gold,
                }
                for r in d5_c[:8]
            ],
            "D5_D_top": [
                {
                    "document_id": r["document_id"],
                    "document_type": r.get("document_type"),
                    "score": round(float(r["score"]), 4),
                    "in_gold": r["document_id"] in gold,
                }
                for r in d5_d[:8]
            ],
        },
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
            c = row["ceilings"]
            v = row["variants"]
            print(
                f"  families={[x['family'] for x in row['oracle_role_families']]} "
                f"ceil theme={c['theme']} family={c['role_family']} type={c['document_type_el_ica']} "
                f"| D5C@20={v['D5_C_family_ctx']['R@20']} D5D@20={v['D5_D_family_lex']['R@20']} "
                f"D5E@20={v['D5_E_family_lex_ctx']['R@20']}",
                flush=True,
            )
    finally:
        await close_pool()

    def avg_ceil(key: str) -> float:
        return round(sum(r["ceilings"][key] for r in rows) / len(rows), 4)

    def avg_var(name: str, key: str) -> float:
        vals = [
            float(r["variants"][name][key])
            for r in rows
            if r["variants"][name].get(key) is not None
        ]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    summary = {
        "n": len(rows),
        "ceilings": {
            "theme": avg_ceil("theme"),
            "role_family": avg_ceil("role_family"),
            "document_type_el_ica": avg_ceil("document_type_el_ica"),
            "avg_n_role_family": round(
                sum(r["ceilings"]["n_role_family"] for r in rows) / len(rows), 1
            ),
            "avg_n_theme": round(sum(r["ceilings"]["n_theme"] for r in rows) / len(rows), 1),
            "avg_scope_reduction": round(
                sum(r["ceilings"]["scope_reduction_theme_to_family"] for r in rows) / len(rows), 2
            ),
        },
        "baselines": {"C5.4-D": C54, "C5.5_ctx": C55},
        "variants": {},
    }
    for name in (
        "D5_A_theme_raw",
        "D5_B_family_raw",
        "D5_C_family_ctx",
        "D5_D_family_lex",
        "D5_E_family_lex_ctx",
    ):
        summary["variants"][name] = {
            "label": rows[0]["variants"][name]["label"],
            **{f"R@{k}": avg_var(name, f"R@{k}") for k in KS},
            **{f"Hit@{k}": avg_var(name, f"Hit@{k}") for k in (20, 50, 100)},
            "mrr": avg_var(name, "mrr"),
            "avg_best_gold_rank": avg_var(name, "best_gold_rank"),
        }

    best_r20 = max(
        summary["variants"][n]["R@20"]
        for n in summary["variants"]
    )
    gate = {
        "role_family_ceiling_ok": summary["ceilings"]["role_family"] >= 0.95,
        "beats_c54": best_r20 > C54["R@20"] + 0.05,
        "beats_c55": best_r20 > C55["R@20"] + 0.05,
        "material_r20": best_r20 >= 0.30,
        "strong_r20": best_r20 >= 0.70,
        "best_r20": best_r20,
        "enable_role_conditioned": False,  # oracle only
        "ce_next": False,
        "next": (
            "build role-conditioned retrieval"
            if best_r20 >= 0.30
            else "document-purpose/content profiling below genre"
        ),
    }

    return {
        "experiment": "P5.6-C5.5-D4/D5 role-family oracle",
        "summary": summary,
        "gate": gate,
        "per_query": rows,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--chunk-limit", type=int, default=2000)
    p.add_argument("--doc-limit", type=int, default=500)
    p.add_argument("--out", default="last_role_family_oracle")
    args = p.parse_args()

    print("=== P5.6-C5.5-D4/D5 role-family oracle ===", flush=True)
    payload = asyncio.run(run(args.chunk_limit, args.doc_limit))

    out = ROOT / "evals" / f"{args.out}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")

    s = payload["summary"]
    g = payload["gate"]
    c = s["ceilings"]
    md = [
        "# P5.6-C5.5-D4/D5 Role-Family Oracle",
        "",
        "## D4 ceilings",
        "",
        f"| Scope | Ceiling | Avg docs |",
        f"| ----- | ------: | -------: |",
        f"| Theme | **{c['theme']:.3f}** | {c['avg_n_theme']:.0f} |",
        f"| Role family (oracle) | **{c['role_family']:.3f}** | {c['avg_n_role_family']:.0f} |",
        f"| Document type EL/ICA | **{c['document_type_el_ica']:.3f}** | — |",
        f"",
        f"Theme→family scope reduction **{c['avg_scope_reduction']:.1f}×**",
        "",
        "## D5 retrieval (oracle hard scope)",
        "",
        "| Variant | R@20 | Hit@20 | R@50 | R@100 | MRR | avg best-gold |",
        "| ------- | ---: | -----: | ---: | ----: | --: | ------------: |",
    ]
    for name, x in s["variants"].items():
        md.append(
            f"| {name} {x['label']} | {x['R@20']:.3f} | {x['Hit@20']:.3f} | "
            f"{x['R@50']:.3f} | {x['R@100']:.3f} | {x['mrr']:.3f} | "
            f"{x.get('avg_best_gold_rank')} |"
        )
    md += [
        "",
        f"vs C5.4-D R@20={C54['R@20']} · C5.5 ctx R@20={C55['R@20']}",
        "",
        f"Gate: family_ceil_ok={g['role_family_ceiling_ok']} "
        f"material_r20={g['material_r20']} best_r20={g['best_r20']} → **{g['next']}**",
        "",
        "Oracle only — production role routing should prioritize, not hard-exclude.",
        "THEME_SCOPED_DOCUMENT_RETRIEVAL remains off. CE / GraphRAG frozen.",
    ]
    (ROOT / "evals" / f"{args.out}.md").write_text("\n".join(md) + "\n")
    print(json.dumps({"ceilings": c, "variants": {
        k: {"R@20": v["R@20"], "R@100": v["R@100"], "Hit@20": v["Hit@20"]}
        for k, v in s["variants"].items()
    }, "gate": g}, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
