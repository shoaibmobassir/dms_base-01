#!/usr/bin/env python3
"""P5.6-C5.5-D6 — Within-family purpose profiling + oracle retrieval.

D6.0  same-theme + same-role-family hard negatives
D6.1–D6.3  purpose taxonomy / title-header-opening signals
D6.4  purpose ceiling (vs theme / role / type)
D6.5–D6.7  oracle purpose + lexical / contextual / hybrid

Oracle purposes derived from gold labels (no query hardcoding).
Flags stay off.

Usage:
  .venv/bin/python evals/purpose_profile_ablation.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter, defaultdict
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
    discriminative_table,
    infer_role_family,
    oracle_role_families_from_gold,
)
from app.retrieval.doc_purpose import (  # noqa: E402
    document_types_for_purposes,
    infer_purpose,
    oracle_purposes_from_gold,
    purpose_card,
)
from app.retrieval.matter_resolver import build_matter_query_rep, to_or_tsquery  # noqa: E402
from app.retrieval.theme_scoped import resolve_theme_keys, rrf_merge_doc_lists  # noqa: E402
from evals.metrics import mrr, ndcg_at_k, recall_at_k  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

KS = (5, 10, 20, 50, 100)
D5_REF = {"R@20": 0.043, "Hit@20": 0.571, "label": "D5 family+lexical"}
C54_REF = {"R@20": 0.007}

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


async def fetch_theme_docs(theme_keys: list[str]) -> list[dict]:
    async with acquire() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT d.document_id, d.matter_id, d.document_type, d.title,
                       left(d.body, 2000) AS body
                FROM documents d
                JOIN matters m ON m.matter_id = d.matter_id
                WHERE m.theme_key = ANY(%(themes)s)
                """,
                {"themes": theme_keys},
            )
            return list(await cur.fetchall())


async def search_chunks(
    conn,
    qvec: list[float],
    matter_ids: list[str],
    document_ids: list[str] | None,
    *,
    column: str,
    limit: int,
) -> list[dict]:
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


def _purpose_feature_vector(sig) -> dict[str, float]:
    return {
        f"purpose_{p}": 1.0 if sig.purpose == p else 0.0
        for p in (
            "ESTABLISH", "PROPOSE", "ASSESS", "ANALYZE", "PLEAD", "RECORD", "OTHER",
        )
    } | {
        "has_phrase_hit": 1.0 if sig.phrase_hits else 0.0,
        "has_title_token": 1.0 if sig.title_purpose_tokens else 0.0,
        "source_type": 1.0 if sig.purpose_source.startswith("type") else 0.0,
    }


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
    docs = await fetch_theme_docs(intent.theme_keys)
    by_id = {d["document_id"]: d for d in docs}

    # Annotate purpose for all theme docs (opening only — cheap)
    annotated = []
    for d in docs:
        sig = infer_purpose(d.get("document_type"), title=d.get("title"), body=d.get("body"))
        annotated.append({**d, "role_family": sig.role_family, "purpose": sig.purpose, "_sig": sig})

    gold_meta = [by_id[g] for g in gold if g in by_id]
    gold_ann = [a for a in annotated if a["document_id"] in gold]
    role_oracle = oracle_role_families_from_gold(gold_ann)
    purpose_oracle = oracle_purposes_from_gold(gold_ann)
    families = {x["family"] for x in role_oracle}
    purposes = {x["purpose"] for x in purpose_oracle}

    theme_ids = {a["document_id"] for a in annotated}
    family_ids = {a["document_id"] for a in annotated if a["role_family"] in families}
    purpose_ids = {
        a["document_id"] for a in annotated
        if a["role_family"] in families and a["purpose"] in purposes
    }
    type_ids = {a["document_id"] for a in annotated if a.get("document_type") in EL_ICA_TYPES}

    def ceil(scope: set[str]) -> float:
        return (len(scope & gold) / len(gold)) if gold else 0.0

    ceilings = {
        "theme": round(ceil(theme_ids), 4),
        "role_family": round(ceil(family_ids), 4),
        "purpose": round(ceil(purpose_ids), 4),
        "document_type_el_ica": round(ceil(type_ids), 4),
        "n_theme": len(theme_ids),
        "n_role_family": len(family_ids),
        "n_purpose": len(purpose_ids),
        "scope_reduction_family_to_purpose": round(
            len(family_ids) / max(len(purpose_ids), 1), 2
        ),
    }

    # D6.0 within-family hard negatives (same family, not gold)
    # Prefer same family + different purpose, else same purpose competitors
    family_pool = [a for a in annotated if a["role_family"] in families and a["document_id"] not in gold]
    same_purpose_neg = [a for a in family_pool if a["purpose"] in purposes]
    diff_purpose_neg = [a for a in family_pool if a["purpose"] not in purposes]
    hard_negs = (diff_purpose_neg[:15] + same_purpose_neg[:15])[:30]

    # D6.2 discriminative purpose features gold vs within-family hard-neg
    pos_vecs = [_purpose_feature_vector(a["_sig"]) for a in gold_ann]
    neg_vecs = [_purpose_feature_vector(a["_sig"]) for a in hard_negs]
    disc = discriminative_table(pos_vecs, neg_vecs) if pos_vecs and neg_vecs else []

    # Cards: one gold + one hard-neg
    cards = []
    if gold_ann:
        cards.append(purpose_card(gold_ann[0], gold_ann[0]["_sig"]))
    if hard_negs:
        cards.append(purpose_card(hard_negs[0], hard_negs[0]["_sig"]))

    matter_ids = sorted({a["matter_id"] for a in annotated})
    purpose_list = sorted(purpose_ids)
    family_list = sorted(family_ids)
    qvec = _get_embedder().encode([question])[0]

    async with acquire() as conn:
        # D6-A control: role family only
        ctx_fam = await search_chunks(
            conn, qvec, matter_ids, family_list, column="embedding_ctx", limit=chunk_limit,
        )
        # D6-C purpose + ctx
        ctx_purp = await search_chunks(
            conn, qvec, matter_ids, purpose_list, column="embedding_ctx", limit=chunk_limit,
        )
        raw_purp = await search_chunks(
            conn, qvec, matter_ids, purpose_list, column="embedding", limit=chunk_limit,
        )

    lex_fam = await lexical_docs(
        question, parsed.search_text or question, matter_ids, family_list, limit=doc_limit,
    )
    lex_purp = await lexical_docs(
        question, parsed.search_text or question, matter_ids, purpose_list, limit=doc_limit,
    )

    d6_a = lex_fam[:doc_limit]  # role family + lexical (D5-D control)
    d6_b = lex_purp[:doc_limit]
    d6_c = aggregate_chunk_scores(ctx_purp, method="max")[:doc_limit]
    d6_d = rrf_merge_doc_lists([d6_b, d6_c], k=doc_limit, weights=[1.0, 1.0])
    d6_raw = aggregate_chunk_scores(raw_purp, method="max")[:doc_limit]

    variants = {
        "D6_A_family_lex": _metrics(gold, [r["document_id"] for r in d6_a]) | {
            "label": "role-family + lexical (D5 control)",
        },
        "D6_B_purpose_lex": _metrics(gold, [r["document_id"] for r in d6_b]) | {
            "label": "role+purpose + lexical",
        },
        "D6_C_purpose_ctx": _metrics(gold, [r["document_id"] for r in d6_c]) | {
            "label": "role+purpose + contextual",
        },
        "D6_D_purpose_hybrid": _metrics(gold, [r["document_id"] for r in d6_d]) | {
            "label": "role+purpose + lex∪ctx RRF",
        },
        "D6_purpose_raw": _metrics(gold, [r["document_id"] for r in d6_raw]) | {
            "label": "role+purpose + raw vector",
        },
    }

    return {
        "query_id": q["question_id"],
        "question": question,
        "theme_keys": intent.theme_keys,
        "oracle_role_families": role_oracle,
        "oracle_purposes": purpose_oracle,
        "allowed_types_for_purpose": document_types_for_purposes(purposes),
        "ceilings": ceilings,
        "hard_neg_summary": {
            "n": len(hard_negs),
            "type_counts": dict(Counter(a["document_type"] for a in hard_negs)),
            "purpose_counts": dict(Counter(a["purpose"] for a in hard_negs)),
        },
        "discriminative_purpose_features": disc[:12],
        "purpose_cards": cards,
        "variants": variants,
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
                f"  purposes={[x['purpose'] for x in row['oracle_purposes']]} "
                f"ceil T/R/P={c['theme']}/{c['role_family']}/{c['purpose']} "
                f"n_p={c['n_purpose']} "
                f"| D6B@20={v['D6_B_purpose_lex']['R@20']} "
                f"D6C@20={v['D6_C_purpose_ctx']['R@20']} "
                f"D6D@20={v['D6_D_purpose_hybrid']['R@20']}",
                flush=True,
            )
    finally:
        await close_pool()

    def avg_c(key: str) -> float:
        return round(sum(r["ceilings"][key] for r in rows) / len(rows), 4)

    def avg_v(name: str, key: str) -> float:
        vals = [
            float(r["variants"][name][key])
            for r in rows
            if r["variants"][name].get(key) is not None
        ]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    summary = {
        "n": len(rows),
        "ceilings": {
            "theme": avg_c("theme"),
            "role_family": avg_c("role_family"),
            "purpose": avg_c("purpose"),
            "document_type_el_ica": avg_c("document_type_el_ica"),
            "avg_n_purpose": round(sum(r["ceilings"]["n_purpose"] for r in rows) / len(rows), 1),
            "avg_n_role_family": round(
                sum(r["ceilings"]["n_role_family"] for r in rows) / len(rows), 1
            ),
            "avg_family_to_purpose_reduction": round(
                sum(r["ceilings"]["scope_reduction_family_to_purpose"] for r in rows) / len(rows), 2
            ),
        },
        "baselines": {"C5.4-D": C54_REF, "D5_family_lex": D5_REF},
        "variants": {},
    }
    for name in (
        "D6_A_family_lex",
        "D6_B_purpose_lex",
        "D6_C_purpose_ctx",
        "D6_D_purpose_hybrid",
        "D6_purpose_raw",
    ):
        summary["variants"][name] = {
            "label": rows[0]["variants"][name]["label"],
            **{f"R@{k}": avg_v(name, f"R@{k}") for k in KS},
            **{f"Hit@{k}": avg_v(name, f"Hit@{k}") for k in (20, 50, 100)},
            "mrr": avg_v(name, "mrr"),
            "avg_best_gold_rank": avg_v(name, "best_gold_rank"),
        }

    best_r20 = max(summary["variants"][n]["R@20"] for n in summary["variants"])
    d6b = summary["variants"]["D6_B_purpose_lex"]["R@20"]
    d5 = D5_REF["R@20"]
    purpose_ceil = summary["ceilings"]["purpose"]

    gate = {
        "pass1_purpose_ceiling": purpose_ceil >= 0.90,
        "pass2_further_reduction": summary["ceilings"]["avg_family_to_purpose_reduction"] > 1.05,
        "pass3_beats_d5": d6b > d5 + 0.02,
        "material_r20_020": best_r20 >= 0.20,
        "strong_r20_040": best_r20 >= 0.40,
        "best_r20": best_r20,
        "purpose_as_hard_scope": purpose_ceil >= 0.95,
        "purpose_as_soft_feature": purpose_ceil < 0.90,
        "next": (
            "soft purpose profile + RRF (role→purpose→lex/sem)"
            if (purpose_ceil >= 0.90 and d6b > d5)
            else "proposition/evidence-level retrieval"
            if purpose_ceil < 0.90 or best_r20 < d5 + 0.01
            else "continue purpose feature enrichment"
        ),
    }

    # Compact hard-neg dataset
    dataset = []
    for r in rows:
        dataset.append({
            "query_id": r["query_id"],
            "oracle_purposes": r["oracle_purposes"],
            "oracle_role_families": r["oracle_role_families"],
            "ceilings": r["ceilings"],
            "hard_neg_summary": r["hard_neg_summary"],
            "purpose_cards": r["purpose_cards"],
        })

    return {
        "experiment": "P5.6-C5.5-D6 within-family purpose profiling",
        "summary": summary,
        "gate": gate,
        "dataset": dataset,
        "per_query": rows,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--chunk-limit", type=int, default=2000)
    p.add_argument("--doc-limit", type=int, default=500)
    p.add_argument("--out", default="last_purpose_profile")
    args = p.parse_args()

    print("=== P5.6-C5.5-D6 purpose profile ===", flush=True)
    payload = asyncio.run(run(args.chunk_limit, args.doc_limit))

    out = ROOT / "evals" / f"{args.out}.json"
    out.write_text(json.dumps(payload, indent=2, default=str) + "\n")

    ds = ROOT / "evals" / "purpose_hardneg_dataset.jsonl"
    with ds.open("w", encoding="utf-8") as f:
        for row in payload["dataset"]:
            f.write(json.dumps(row) + "\n")

    s = payload["summary"]
    g = payload["gate"]
    c = s["ceilings"]
    md = [
        "# P5.6-C5.5-D6 Within-Family Purpose Profiling",
        "",
        "## Ceilings",
        "",
        "| Scope | Ceiling | Avg docs |",
        "| ----- | ------: | -------: |",
        f"| Theme | **{c['theme']:.3f}** | — |",
        f"| Role family | **{c['role_family']:.3f}** | {c['avg_n_role_family']:.0f} |",
        f"| **Purpose (oracle)** | **{c['purpose']:.3f}** | **{c['avg_n_purpose']:.0f}** |",
        f"| Type EL/ICA | {c['document_type_el_ica']:.3f} | — |",
        "",
        f"Family→purpose reduction **{c['avg_family_to_purpose_reduction']:.2f}×**",
        "",
        "## Retrieval (oracle purpose hard scope)",
        "",
        "| Variant | R@20 | Hit@20 | R@100 | MRR | avg best-gold |",
        "| ------- | ---: | -----: | ----: | --: | ------------: |",
    ]
    for name, x in s["variants"].items():
        md.append(
            f"| {name} {x['label']} | {x['R@20']:.3f} | {x['Hit@20']:.3f} | "
            f"{x['R@100']:.3f} | {x['mrr']:.3f} | {x.get('avg_best_gold_rank')} |"
        )
    md += [
        "",
        f"vs D5 family+lex R@20={D5_REF['R@20']} · C5.4-D={C54_REF['R@20']}",
        "",
        f"Gate: purpose_ceil≥.90={g['pass1_purpose_ceiling']} "
        f"beats_d5={g['pass3_beats_d5']} material_020={g['material_r20_020']} "
        f"→ **{g['next']}**",
        "",
        "Flags remain OFF. Oracle only — production purpose must be soft.",
    ]
    (ROOT / "evals" / f"{args.out}.md").write_text("\n".join(md) + "\n")
    print(json.dumps({"ceilings": c, "variants": {
        k: {"R@20": v["R@20"], "Hit@20": v["Hit@20"], "R@100": v["R@100"]}
        for k, v in s["variants"].items()
    }, "gate": g}, indent=2))
    print(f"wrote {out}")
    print(f"wrote {ds}")


if __name__ == "__main__":
    main()
