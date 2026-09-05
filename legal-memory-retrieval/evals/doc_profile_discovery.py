#!/usr/bin/env python3
"""P5.6-C5.5-D0/D1/D2/D3 — Document profile discovery.

Frozen: theme/matter routing, C5.4 lexical, C5.5 embeddings, CE, GraphRAG.

  D0  gold vs hard-negative dataset (same theme; Research Memo / Opinion / Strategy)
  D1  cheap document feature extraction (no LLM)
  D2  discriminative feature analysis (log-odds)
  D3  explain typed ceiling (.83) — non-EL/ICA gold classification

Usage:
  .venv/bin/python evals/doc_profile_discovery.py
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
from app.query.understand import understand  # noqa: E402
from app.retrieval.doc_profile import (  # noqa: E402
    EL_ICA_TYPES,
    HARD_NEG_TYPES,
    discriminative_table,
    extract_doc_features,
    feature_vector,
    infer_document_role,
)
from app.retrieval.theme_scoped import resolve_theme_keys  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

# Prefer hard negatives that beat gold in C5.5 when available.
_CTX_ABLATION = ROOT / "evals" / "last_contextual_chunk.json"


def _load_c55_hard_neg_ids() -> dict[str, list[str]]:
    if not _CTX_ABLATION.exists():
        return {}
    data = json.loads(_CTX_ABLATION.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for row in data.get("per_query") or []:
        qid = row.get("query_id")
        diag = (row.get("diagnostics") or {}).get("A1") or {}
        ids = [x["document_id"] for x in (diag.get("top_nongold") or [])]
        if qid and ids:
            out[qid] = ids
    return out


async def fetch_docs(doc_ids: list[str]) -> list[dict]:
    if not doc_ids:
        return []
    async with acquire() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT document_id, matter_id, document_type, title,
                       folder_path, body, doc_date::text AS doc_date
                FROM documents
                WHERE document_id = ANY(%(ids)s)
                """,
                {"ids": doc_ids},
            )
            return list(await cur.fetchall())


async def theme_hard_neg_candidates(
    theme_keys: list[str],
    gold: set[str],
    *,
    per_type: int = 8,
) -> list[str]:
    """Sample confusing types inside theme (exclude gold)."""
    async with acquire() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT d.document_id, d.document_type
                FROM documents d
                JOIN matters m ON m.matter_id = d.matter_id
                WHERE m.theme_key = ANY(%(themes)s)
                  AND d.document_type = ANY(%(types)s)
                  AND NOT (d.document_id = ANY(%(gold)s))
                ORDER BY d.document_type, d.document_id
                """,
                {
                    "themes": theme_keys,
                    "types": list(HARD_NEG_TYPES),
                    "gold": list(gold) or ["__none__"],
                },
            )
            rows = await cur.fetchall()
    by_type: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        by_type[r["document_type"]].append(r["document_id"])
    out: list[str] = []
    for dtype in sorted(by_type):
        out.extend(by_type[dtype][:per_type])
    return out


async def run_one(q: dict, c55_negs: dict[str, list[str]]) -> dict:
    question = q["question"]
    qid = q["question_id"]
    gold_ids = list(q.get("expected_documents") or [])
    gold = set(gold_ids)
    parsed = understand(question)
    intent = resolve_theme_keys(
        question,
        search_text=parsed.search_text,
        practice_area=parsed.practice_area,
        max_themes=1,
    )

    # D0 hard negatives: C5.5 top non-gold ∪ type-sampled theme docs
    neg_ids = list(dict.fromkeys(
        (c55_negs.get(qid) or []) + await theme_hard_neg_candidates(intent.theme_keys, gold)
    ))
    # Cap for feature extraction cost
    neg_ids = neg_ids[:40]

    gold_rows = await fetch_docs(gold_ids)
    neg_rows = await fetch_docs(neg_ids)

    gold_feats = [
        extract_doc_features(
            document_id=r["document_id"],
            matter_id=r.get("matter_id"),
            document_type=r.get("document_type"),
            title=r.get("title"),
            body=r.get("body"),
            folder_path=r.get("folder_path"),
        )
        for r in gold_rows
    ]
    neg_feats = [
        extract_doc_features(
            document_id=r["document_id"],
            matter_id=r.get("matter_id"),
            document_type=r.get("document_type"),
            title=r.get("title"),
            body=r.get("body"),
            folder_path=r.get("folder_path"),
        )
        for r in neg_rows
    ]

    typed = {f.document_id for f in gold_feats if f.is_el_ica}
    typed_ceil = (len(typed) / len(gold)) if gold else 0.0

    # D3: non-EL/ICA gold classification
    non_typed = []
    for f in gold_feats:
        if f.is_el_ica:
            continue
        non_typed.append({
            "document_id": f.document_id,
            "document_type": f.document_type,
            "document_role": f.document_role,
            "title": f.title,
            "char_count": f.char_count,
            "classification": (
                "B_benchmark_non_el_ica"
                if f.document_type not in EL_ICA_TYPES
                else "A_label_problem"
            ),
        })

    return {
        "query_id": qid,
        "question": question,
        "theme_keys": intent.theme_keys,
        "n_gold": len(gold_feats),
        "n_hard_neg": len(neg_feats),
        "typed_ceiling": round(typed_ceil, 4),
        "gold_type_counts": dict(Counter(f.document_type for f in gold_feats)),
        "gold_role_counts": dict(Counter(f.document_role for f in gold_feats)),
        "hard_neg_type_counts": dict(Counter(f.document_type for f in neg_feats)),
        "non_el_ica_gold": non_typed,
        "positives": [f.to_dict() for f in gold_feats],
        "hard_negatives": [f.to_dict() for f in neg_feats],
        "positive_vectors": [feature_vector(f) for f in gold_feats],
        "negative_vectors": [feature_vector(f) for f in neg_feats],
    }


async def run() -> dict:
    questions = [
        json.loads(line)
        for line in (ROOT / "evals" / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    semantic = [q for q in questions if q.get("type") == "semantic"]
    c55_negs = _load_c55_hard_neg_ids()

    await init_pool()
    try:
        rows = []
        for q in semantic:
            print(f"{q['question_id']}…", flush=True)
            row = await run_one(q, c55_negs)
            rows.append(row)
            print(
                f"  theme={row['theme_keys']} gold={row['n_gold']} "
                f"neg={row['n_hard_neg']} typed_ceil={row['typed_ceiling']} "
                f"gold_types={row['gold_type_counts']}",
                flush=True,
            )
    finally:
        await close_pool()

    # Global D2 across all queries
    all_pos = [v for r in rows for v in r["positive_vectors"]]
    all_neg = [v for r in rows for v in r["negative_vectors"]]
    memo_neg = [
        vec
        for r in rows
        for d, vec in zip(r["hard_negatives"], r["negative_vectors"])
        if d.get("document_type") in HARD_NEG_TYPES
    ]

    disc_all = discriminative_table(all_pos, all_neg)
    disc_vs_confusers = discriminative_table(all_pos, memo_neg) if memo_neg else disc_all

    # Distribution summary table (means for key features)
    def mean_feat(vectors: list[dict], key: str) -> float:
        if not vectors:
            return 0.0
        return round(sum(float(v.get(key, 0)) for v in vectors) / len(vectors), 3)

    summary_compare = []
    for key in (
        "is_el_ica", "signature_present", "engagement_header", "assessment_header",
        "memo_header", "opinion_header", "short_doc_lt_800_chars", "long_doc_gt_1200_chars",
        "word_count", "char_count", "shall_count", "citation_count", "party_mention_count",
        "defined_term_count", "role_engagement", "role_research",
    ):
        summary_compare.append({
            "feature": key,
            "mean_gold": mean_feat(all_pos, key),
            "mean_hard_neg": mean_feat(all_neg, key),
            "mean_confuser_types": mean_feat(memo_neg, key),
        })

    # D3 aggregate
    non_typed_all = [x for r in rows for x in r["non_el_ica_gold"]]
    typed_ceils = [r["typed_ceiling"] for r in rows]
    d3 = {
        "avg_typed_ceiling": round(sum(typed_ceils) / len(typed_ceils), 4),
        "n_non_el_ica_gold": len(non_typed_all),
        "non_el_ica_type_counts": dict(Counter(x["document_type"] for x in non_typed_all)),
        "non_el_ica_role_counts": dict(Counter(x["document_role"] for x in non_typed_all)),
        "by_query": [
            {
                "query_id": r["query_id"],
                "typed_ceiling": r["typed_ceiling"],
                "non_el_ica": r["non_el_ica_gold"],
            }
            for r in rows
            if r["non_el_ica_gold"]
        ],
        "interpretation": (
            "B_benchmark_problem"
            if non_typed_all and all(
                x["classification"] == "B_benchmark_non_el_ica" for x in non_typed_all
            )
            else "mixed"
        ),
    }

    # Strip heavy body-less vectors from per_query export for dataset artifact
    dataset = []
    for r in rows:
        dataset.append({
            "query_id": r["query_id"],
            "question": r["question"],
            "theme_keys": r["theme_keys"],
            "positives": [
                {
                    "document_id": d["document_id"],
                    "document_type": d["document_type"],
                    "document_role": d["document_role"],
                    "title": d["title"],
                    "char_count": d["char_count"],
                    "word_count": d["word_count"],
                    "signature_present": d["signature_present"],
                    "engagement_header": d["engagement_header"],
                    "assessment_header": d["assessment_header"],
                }
                for d in r["positives"]
            ],
            "hard_negatives": [
                {
                    "document_id": d["document_id"],
                    "document_type": d["document_type"],
                    "document_role": d["document_role"],
                    "title": d["title"],
                    "char_count": d["char_count"],
                    "word_count": d["word_count"],
                    "memo_header": d["memo_header"],
                    "opinion_header": d["opinion_header"],
                }
                for d in r["hard_negatives"]
            ],
        })

    top_signals = [x for x in disc_vs_confusers if x["abs_log_odds"] >= 1.0][:15]
    weak_signals = [
        x for x in disc_vs_confusers
        if x["feature"] in {
            "citation_count", "shall_count", "agreement_count", "party_mention_count",
        } or x["abs_log_odds"] < 0.3
    ][:10]

    return {
        "experiment": "P5.6-C5.5-D document profile discovery (D0–D3)",
        "freeze": {
            "theme_routing": True,
            "c54_lexical": True,
            "c55_ctx_embeddings": True,
            "ce": False,
            "graphrag": False,
        },
        "summary": {
            "n_queries": len(rows),
            "n_gold_docs": len(all_pos),
            "n_hard_neg_docs": len(all_neg),
            "avg_typed_ceiling": d3["avg_typed_ceiling"],
            "top_discriminative_features": top_signals,
            "distribution_compare": summary_compare,
            "d3_typed_ceiling": d3,
        },
        "discriminative_vs_all_hard_neg": disc_all[:25],
        "discriminative_vs_confuser_types": disc_vs_confusers[:25],
        "weak_or_topical": weak_signals,
        "dataset": dataset,
        "per_query": [
            {k: v for k, v in r.items() if k not in {"positive_vectors", "negative_vectors"}}
            for r in rows
        ],
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="last_doc_profile_discovery")
    args = p.parse_args()

    print("=== P5.6-C5.5-D document profile discovery ===", flush=True)
    payload = asyncio.run(run())

    out = ROOT / "evals" / f"{args.out}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")

    # Compact dataset artifact
    ds = ROOT / "evals" / "gold_vs_hardneg_dataset.jsonl"
    with ds.open("w", encoding="utf-8") as f:
        for row in payload["dataset"]:
            f.write(json.dumps(row) + "\n")

    s = payload["summary"]
    d3 = s["d3_typed_ceiling"]
    md = [
        "# P5.6-C5.5-D Document Profile Discovery",
        "",
        f"Queries **{s['n_queries']}** · gold docs **{s['n_gold_docs']}** · "
        f"hard-neg **{s['n_hard_neg_docs']}** · typed ceiling **{s['avg_typed_ceiling']:.3f}**",
        "",
        "## D3 — Why typed ceiling ≈ .83",
        "",
        f"Interpretation: **{d3['interpretation']}**",
        f"Non-EL/ICA gold docs: **{d3['n_non_el_ica_gold']}** → "
        f"`{d3['non_el_ica_type_counts']}`",
        "",
        "## D2 — Top discriminative features (gold vs Research Memo / Opinion / Strategy)",
        "",
        "| Feature | P(gold) | P(hard-neg) | mean_gold | mean_neg | log_odds |",
        "| ------- | ------: | ----------: | --------: | -------: | -------: |",
    ]
    for x in s["top_discriminative_features"]:
        md.append(
            f"| {x['feature']} | {x['p_gold']:.3f} | {x['p_hard_neg']:.3f} | "
            f"{x['mean_gold']} | {x['mean_hard_neg']} | {x['log_odds']:.2f} |"
        )
    md += [
        "",
        "## Distribution snapshot",
        "",
        "| Feature | Gold | Hard-neg | Confuser types |",
        "| ------- | ---: | -------: | -------------: |",
    ]
    for x in s["distribution_compare"]:
        md.append(
            f"| {x['feature']} | {x['mean_gold']} | {x['mean_hard_neg']} | "
            f"{x['mean_confuser_types']} |"
        )
    md += [
        "",
        f"Dataset: `{ds.name}`",
        "",
        "Next: D4 type-oracle / D5 role-oracle retrieval (only after reviewing signals).",
        "THEME_SCOPED_DOCUMENT_RETRIEVAL remains off.",
    ]
    (ROOT / "evals" / f"{args.out}.md").write_text("\n".join(md) + "\n")
    print(json.dumps({
        "avg_typed_ceiling": s["avg_typed_ceiling"],
        "d3": d3["non_el_ica_type_counts"],
        "top5": [
            {k: x[k] for k in ("feature", "p_gold", "p_hard_neg", "log_odds")}
            for x in s["top_discriminative_features"][:5]
        ],
    }, indent=2))
    print(f"wrote {out}")
    print(f"wrote {ds}")


if __name__ == "__main__":
    main()
