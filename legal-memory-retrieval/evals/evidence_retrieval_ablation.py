#!/usr/bin/env python3
"""P5.6-C7 — Evidence-first retrieval ablation (phrase / proximity / role / RRF).

C7.2+ lexical OR + phrase + proximity + hybrid lexical RRF
C7.3 semantic (raw + contextual)
C7.4 hybrid RRF (lexical×vector)
C7.4b stronger multiplicative soft role prior

Scope: theme matters + soft role prior (no hard EL/ICA exclude).
Hard-role deep-pool remains diagnostic only.

Usage:
  .venv/bin/python evals/build_gold_evidence.py
  .venv/bin/python evals/evidence_retrieval_ablation.py
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
from app.retrieval.evidence import (  # noqa: E402
    aggregate_evidence_to_documents,
    apply_soft_role_prior,
    hybrid_lexical_evidence,
    lexical_evidence_search,
    phrase_evidence_search,
    proximity_evidence_search,
    rrf_evidence,
    vector_evidence_search,
)
from app.retrieval.evidence_rerank import rerank_evidence  # noqa: E402
from app.retrieval.proposition import query_propositions_from_dict  # noqa: E402
from app.retrieval.theme_scoped import resolve_theme_keys  # noqa: E402
from evals.metrics import mrr, ndcg_at_k, recall_at_k  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

KS = (5, 10, 20, 50, 100)
D5_DOC_R20 = 0.043
C74_SOFT_R20_REF = 0.020

VARIANT_NAMES = (
    "lexical",
    "phrase",
    "proximity",
    "hybrid_lexical",
    "lexical_hard_role",
    "vector_raw",
    "vector_ctx",
    "hybrid_rrf",
    "hybrid_hard_role",
    "ce_soft",
    "ce_hard_role",
)
SOFT_VARIANTS = (
    "lexical",
    "phrase",
    "proximity",
    "hybrid_lexical",
    "vector_raw",
    "vector_ctx",
    "hybrid_rrf",
    "ce_soft",
)

_embedder: MiniLMEmbedder | None = None


def _hard_role_filter(spans, preferred: set[str]):
    if not preferred:
        return spans
    return [s for s in spans if s.role_family in preferred]


def _get_embedder() -> MiniLMEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = MiniLMEmbedder()
    return _embedder


def _hit(gold: set[str], ranked: list[str], k: int) -> float:
    return 1.0 if gold and set(ranked[:k]) & gold else 0.0


def _metrics(gold: set[str], ranked: list[str]) -> dict:
    out = {f"R@{k}": round(recall_at_k(gold, ranked, k), 4) for k in KS}
    out.update({f"Hit@{k}": _hit(gold, ranked, k) for k in (20, 50, 100)})
    out["mrr"] = round(mrr(gold, ranked), 4)
    out["ndcg@20"] = round(ndcg_at_k(gold, ranked, 20), 4)
    return out


async def theme_matter_ids(theme_keys: list[str]) -> list[str]:
    async with acquire() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT matter_id FROM matters WHERE theme_key = ANY(%(t)s)",
                {"t": theme_keys},
            )
            return [r["matter_id"] for r in await cur.fetchall()]


def load_gold_evidence() -> dict[tuple[str, str], set[str]]:
    path = ROOT / "evals" / "gold_evidence.jsonl"
    out: dict[tuple[str, str], set[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        key = (row["query_id"], row["proposition_id"])
        out[key] = {g["chunk_id"] for g in row.get("gold_evidence") or []}
    return out


def load_gold_docs() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for line in (ROOT / "evals" / "dataset.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        q = json.loads(line)
        if q.get("type") != "semantic":
            continue
        out[q["question_id"]] = set(q.get("expected_documents") or [])
    return out


async def run(limit: int) -> dict:
    gold_map = load_gold_evidence()
    gold_docs = load_gold_docs()
    prop_rows = [
        query_propositions_from_dict(json.loads(line))
        for line in (ROOT / "evals" / "propositions.jsonl").read_text().splitlines()
        if line.strip()
    ]

    await init_pool()
    try:
        rows = []
        for qp in prop_rows:
            print(f"{qp.query_id}…", flush=True)
            intent_themes = qp.theme_hints or resolve_theme_keys(qp.query, max_themes=1).theme_keys
            matters = await theme_matter_ids(intent_themes)
            preferred = set(qp.role_families or [])
            prop_results = []

            async with acquire() as conn:
                for prop in qp.propositions:
                    gold = gold_map.get((qp.query_id, prop.id), set())
                    deep = max(limit * 10, 500)

                    lex_deep = await lexical_evidence_search(conn, prop, matters, limit=deep)
                    phrase = apply_soft_role_prior(
                        await phrase_evidence_search(conn, prop, matters, limit=limit),
                        preferred,
                    )
                    prox = apply_soft_role_prior(
                        await proximity_evidence_search(conn, prop, matters, limit=limit),
                        preferred,
                    )
                    hyb_lex_raw = await hybrid_lexical_evidence(
                        conn, prop, matters, limit=limit,
                    )
                    hyb_lex = apply_soft_role_prior(hyb_lex_raw, preferred)

                    lex = apply_soft_role_prior(lex_deep[:limit], preferred)
                    lex_hard = apply_soft_role_prior(
                        _hard_role_filter(lex_deep, preferred)[:limit],
                        preferred,
                    )

                    qvec = _get_embedder().encode([prop.retrieval_text()])[0]
                    vec_raw = apply_soft_role_prior(
                        await vector_evidence_search(
                            conn, qvec, prop, matters, column="embedding", limit=limit,
                        ),
                        preferred,
                    )
                    vec_ctx_deep = await vector_evidence_search(
                        conn, qvec, prop, matters, column="embedding_ctx", limit=deep,
                    )
                    vec_ctx = apply_soft_role_prior(vec_ctx_deep[:limit], preferred)
                    vec_ctx_hard = apply_soft_role_prior(
                        _hard_role_filter(vec_ctx_deep, preferred)[:limit],
                        preferred,
                    )

                    hybrid = rrf_evidence([hyb_lex, vec_ctx], k=limit)
                    hybrid_hard = rrf_evidence([lex_hard, vec_ctx_hard], k=limit)

                    ce_soft = rerank_evidence(prop, hyb_lex, limit=limit)
                    ce_hard = rerank_evidence(prop, lex_hard, limit=limit)

                    variants = {
                        "lexical": _metrics(gold, [s.chunk_id for s in lex]),
                        "phrase": _metrics(gold, [s.chunk_id for s in phrase]),
                        "proximity": _metrics(gold, [s.chunk_id for s in prox]),
                        "hybrid_lexical": _metrics(gold, [s.chunk_id for s in hyb_lex]),
                        "lexical_hard_role": _metrics(gold, [s.chunk_id for s in lex_hard]),
                        "vector_raw": _metrics(gold, [s.chunk_id for s in vec_raw]),
                        "vector_ctx": _metrics(gold, [s.chunk_id for s in vec_ctx]),
                        "hybrid_rrf": _metrics(gold, [s.chunk_id for s in hybrid]),
                        "hybrid_hard_role": _metrics(gold, [s.chunk_id for s in hybrid_hard]),
                        "ce_soft": _metrics(gold, [s.chunk_id for s in ce_soft]),
                        "ce_hard_role": _metrics(gold, [s.chunk_id for s in ce_hard]),
                    }
                    docs = aggregate_evidence_to_documents(ce_hard, method="max")
                    prop_results.append({
                        "proposition_id": prop.id,
                        "claim": prop.claim,
                        "n_gold_evidence": len(gold),
                        "variants": variants,
                        "doc_from_hybrid": _metrics(
                            gold_docs.get(qp.query_id, set()),
                            [d["document_id"] for d in docs],
                        ),
                        "survival": {
                            "lex": len(gold & {s.chunk_id for s in lex}),
                            "phrase": len(gold & {s.chunk_id for s in phrase}),
                            "proximity": len(gold & {s.chunk_id for s in prox}),
                            "hyb_lex": len(gold & {s.chunk_id for s in hyb_lex}),
                            "lex_hard": len(gold & {s.chunk_id for s in lex_hard}),
                            "ce_soft": len(gold & {s.chunk_id for s in ce_soft}),
                            "ce_hard": len(gold & {s.chunk_id for s in ce_hard}),
                        },
                    })

            def avg_var(name: str, metric: str) -> float:
                vals = [float(p["variants"][name][metric]) for p in prop_results]
                return round(sum(vals) / len(vals), 4) if vals else 0.0

            row = {
                "query_id": qp.query_id,
                "query": qp.query,
                "themes": intent_themes,
                "role_families": list(preferred),
                "n_propositions": len(prop_results),
                "variants": {
                    name: {f"R@{k}": avg_var(name, f"R@{k}") for k in KS}
                    | {f"Hit@{k}": avg_var(name, f"Hit@{k}") for k in (20, 50, 100)}
                    | {"mrr": avg_var(name, "mrr"), "ndcg@20": avg_var(name, "ndcg@20")}
                    for name in VARIANT_NAMES
                },
                "doc_from_hybrid": {
                    f"R@{k}": round(
                        sum(float(p["doc_from_hybrid"][f"R@{k}"]) for p in prop_results)
                        / max(len(prop_results), 1),
                        4,
                    )
                    for k in (20, 50, 100)
                },
                "propositions": prop_results,
            }
            rows.append(row)
            v = row["variants"]
            print(
                f"  lex={v['lexical']['R@20']} hybLex={v['hybrid_lexical']['R@20']} "
                f"hard={v['lexical_hard_role']['R@20']} "
                f"ceSoft={v['ce_soft']['R@20']} ceHard={v['ce_hard_role']['R@20']} "
                f"Hit20soft={v['ce_soft']['Hit@20']} Hit20hard={v['ce_hard_role']['Hit@20']}",
                flush=True,
            )
    finally:
        await close_pool()

    def avg(name: str, key: str) -> float:
        vals = [float(r["variants"][name][key]) for r in rows]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    summary = {
        "n_queries": len(rows),
        "variants": {
            name: {
                **{f"R@{k}": avg(name, f"R@{k}") for k in KS},
                **{f"Hit@{k}": avg(name, f"Hit@{k}") for k in (20, 50, 100)},
                "mrr": avg(name, "mrr"),
                "ndcg@20": avg(name, "ndcg@20"),
            }
            for name in VARIANT_NAMES
        },
        "doc_from_hybrid_R@20": round(
            sum(r["doc_from_hybrid"]["R@20"] for r in rows) / max(len(rows), 1), 4
        ),
        "d5_doc_r20_ref": D5_DOC_R20,
        "c74_soft_r20_ref": C74_SOFT_R20_REF,
    }
    soft_best_r = max(summary["variants"][n]["R@20"] for n in SOFT_VARIANTS)
    soft_best_hit = max(summary["variants"][n]["Hit@20"] for n in SOFT_VARIANTS)
    best_ev = max(summary["variants"][n]["R@20"] for n in VARIANT_NAMES)
    ce_soft_r = summary["variants"]["ce_soft"]["R@20"]
    ce_hard_r = summary["variants"]["ce_hard_role"]["R@20"]
    hard_r = summary["variants"]["lexical_hard_role"]["R@20"]
    ce_helps_hard = ce_hard_r > hard_r + 0.02
    ce_ready_prod = soft_best_hit >= 0.50 or soft_best_r >= 0.20
    gate = {
        "evidence_r20_material": soft_best_r >= 0.20,
        "evidence_r20_strong": soft_best_r >= 0.50,
        "soft_hit20": soft_best_hit,
        "hard_role_diagnostic_r20": hard_r,
        "ce_soft_r20": ce_soft_r,
        "ce_hard_r20": ce_hard_r,
        "ce_helps_hard_pool": ce_helps_hard,
        "beats_c74_soft": soft_best_r > C74_SOFT_R20_REF + 0.02,
        "beats_d5_doc_via_agg": summary["doc_from_hybrid_R@20"] > D5_DOC_R20 + 0.05,
        "best_evidence_r20_soft": soft_best_r,
        "best_evidence_r20_any": best_ev,
        "ce_production": False,
        "graphrag_next": False,
        "next": (
            "C7.6 evidence→doc aggregation"
            if ce_helps_hard or ce_ready_prod
            else "candidate generation still bottleneck; CE cannot invent gold"
        ),
    }
    return {
        "experiment": "P5.6-C7.4b/C7.5 phrase+proximity+soft role+CE evidence",
        "summary": summary,
        "gate": gate,
        "per_query": rows,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--out", default="last_evidence_retrieval")
    args = p.parse_args()

    gold_path = ROOT / "evals" / "gold_evidence.jsonl"
    if not gold_path.exists():
        print("missing gold_evidence.jsonl — run evals/build_gold_evidence.py first")
        sys.exit(1)

    print("=== P5.6-C7.4b/C7.5 evidence + CE ===", flush=True)
    payload = asyncio.run(run(args.limit))
    out = ROOT / "evals" / f"{args.out}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")

    s = payload["summary"]
    g = payload["gate"]
    md = [
        "# P5.6-C7.4b / C7.5 Evidence Retrieval + CE",
        "",
        "Soft role: ×2.5 preferred / ×0.7 ANALYSIS. CE = proposition↔passage.",
        "Flags OFF. CE not enabled for document ranking.",
        "",
        "| Variant | Ev R@20 | Hit@20 | Ev R@50 | Ev R@100 | MRR |",
        "| ------- | ------: | -----: | ------: | -------: | --: |",
    ]
    for name, x in s["variants"].items():
        md.append(
            f"| {name} | {x['R@20']:.3f} | {x['Hit@20']:.3f} | "
            f"{x['R@50']:.3f} | {x['R@100']:.3f} | {x['mrr']:.3f} |"
        )
    md += [
        "",
        f"Doc-from-ce_hard R@20 **{s['doc_from_hybrid_R@20']:.3f}** "
        f"(D5 ref {D5_DOC_R20})",
        "",
        f"Gate: soft_r20={g['best_evidence_r20_soft']:.3f} "
        f"ce_hard={g['ce_hard_r20']:.3f} helps_hard={g['ce_helps_hard_pool']} "
        f"→ **{g['next']}**",
    ]
    (ROOT / "evals" / f"{args.out}.md").write_text("\n".join(md) + "\n")
    print(json.dumps({"summary": s, "gate": g}, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
