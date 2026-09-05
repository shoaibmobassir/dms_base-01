#!/usr/bin/env python3
"""P5.6-A Matter Routing Ablation.

Frozen baseline = p55_repair_ce_protect + exact-title repair (MATTER_SCOPE=off).

Variants:
  A  Current P5.5
  B  Matter as score (boost matter RRF)
  C  Matter as hard scope
  D  Hierarchical Matter→Doc→Chunk only (within resolved matters)
  E  D + BM25/vector (+ metadata)
  F  E + CE protection (same as E under default CE policy; uses p55_repair for no-CE control)

Promotion vs P5.5 FINAL:
  ΔR@10 >= +1pp AND ΔHit@10 >= +1pp AND ΔMRR >= +1pp AND exact Hit@10 >= 0.99

Usage:
  .venv/bin/python evals/matter_routing_ablation.py
  .venv/bin/python evals/matter_routing_ablation.py --variants A,C,E
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

# P5.5 FINAL frozen baseline (exact repair + CE protect)
P55_BASELINE = {
    "recall@5": 0.675,
    "recall@10": 0.739,
    "recall@20": None,  # filled from A run if present
    "hit@10": 0.926,
    "mrr": 0.805,
    "ndcg@10": 0.759,
    "exact_hit@10": 0.996,
}

VARIANTS: dict[str, dict[str, str]] = {
    "A": {
        "label": "P5.5 baseline",
        "FUSION_POLICY": "p55_repair_ce_protect",
        "MATTER_SCOPE": "off",
        "MATTER_SCOPE_CHANNELS": "",
    },
    "B": {
        "label": "Matter as score",
        "FUSION_POLICY": "p55_repair_ce_protect",
        "MATTER_SCOPE": "score",
        "MATTER_SCOPE_CHANNELS": "",
    },
    "C": {
        "label": "Matter as hard scope",
        "FUSION_POLICY": "p55_repair_ce_protect",
        "MATTER_SCOPE": "hard",
        "MATTER_SCOPE_CHANNELS": "",
    },
    "D": {
        "label": "Hier Matter→Doc→Chunk only",
        "FUSION_POLICY": "p55_repair_ce_protect",
        "MATTER_SCOPE": "hier",
        "MATTER_SCOPE_CHANNELS": "hierarchical",
    },
    "E": {
        "label": "Hier + BM25/vector (no CE)",
        "FUSION_POLICY": "p55_repair",
        "MATTER_SCOPE": "hier",
        "MATTER_SCOPE_CHANNELS": "bm25,vector,metadata,hierarchical",
    },
    "F": {
        "label": "E + CE protection",
        "FUSION_POLICY": "p55_repair_ce_protect",
        "MATTER_SCOPE": "hier",
        "MATTER_SCOPE_CHANNELS": "bm25,vector,metadata,hierarchical",
    },
}


def _avg(rows: list[dict], key: str) -> float:
    vals = [r[key] for r in rows if key in r]
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def run_eval(variant: str, env_extra: dict[str, str]) -> dict:
    env = os.environ.copy()
    for k, v in env_extra.items():
        if v == "":
            env.pop(k, None)
        else:
            env[k] = v
    out = ROOT / "evals" / "runs" / f"p56a_{variant}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "evals" / "retrieval_eval.py")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"eval failed for {variant}: {proc.stderr[-2000:] or proc.stdout[-2000:]}"
        )
    summary = json.loads((ROOT / "evals" / "last_retrieval_run.json").read_text())
    out.write_text(json.dumps(summary, indent=2) + "\n")
    return summary


async def probe_crr(env_extra: dict[str, str], limit: int = 40) -> dict:
    """Average candidate reduction on matter_retrieval questions."""
    for k, v in env_extra.items():
        if v == "":
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    from app.db.pool import close_pool, init_pool
    from app.retrieval.engine_v2 import retrieve_async

    dataset = ROOT / "evals" / "dataset.jsonl"
    questions = [
        json.loads(line)
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    matter_qs = [q for q in questions if q.get("type") == "matter_retrieval"][:limit]

    await init_pool()
    try:
        universes: list[int] = []
        matter_counts: list[int] = []
        crrs: list[float] = []
        fallbacks = 0
        for q in matter_qs:
            _, latency = await retrieve_async(
                q["question"],
                member_id=q.get("as_member") or q.get("as_user"),
                k=20,
            )
            scope = latency.get("matter_scope") or {}
            if scope.get("fallback") == "unscoped" or not scope.get("matter_count"):
                fallbacks += 1
                continue
            du = int(scope.get("document_universe") or 0)
            universes.append(du)
            matter_counts.append(int(scope.get("matter_count") or 0))
            if scope.get("candidate_reduction_ratio"):
                crrs.append(float(scope["candidate_reduction_ratio"]))
        return {
            "n_probed": len(matter_qs),
            "n_scoped": len(universes),
            "n_fallback_unscoped": fallbacks,
            "avg_matter_count": round(sum(matter_counts) / len(matter_counts), 2) if matter_counts else 0.0,
            "avg_document_universe": round(sum(universes) / len(universes), 2) if universes else 0.0,
            "avg_crr": round(sum(crrs) / len(crrs), 2) if crrs else None,
        }
    finally:
        await close_pool()


def promotion_gate(overall: dict, exact_hit: float, baseline: dict) -> dict:
    d_r = overall["recall@10"] - baseline["recall@10"]
    d_h = overall["hit@10"] - baseline["hit@10"]
    d_m = overall["mrr"] - baseline["mrr"]
    pass_gate = (
        d_r >= 0.01
        and d_h >= 0.01
        and d_m >= 0.01
        and exact_hit >= 0.99
    )
    return {
        "pass": pass_gate,
        "delta_recall@10": round(d_r, 4),
        "delta_hit@10": round(d_h, 4),
        "delta_mrr": round(d_m, 4),
        "exact_hit@10": exact_hit,
        "exact_ok": exact_hit >= 0.99,
    }


def extract_row(variant: str, summary: dict, crr: dict | None) -> dict:
    overall = summary["overall"]
    by_type = summary.get("by_type") or {}
    exact = by_type.get("exact") or {}
    exact_hit = float(exact.get("hit@10") or 0.0)
    gate = promotion_gate(overall, exact_hit, P55_BASELINE)
    focus_types = ("matter_retrieval", "semantic", "similar_matter", "exact")
    return {
        "variant": variant,
        "label": VARIANTS[variant]["label"],
        "env": {k: v for k, v in VARIANTS[variant].items() if k != "label"},
        "overall": {
            "recall@5": overall.get("recall@5"),
            "recall@10": overall.get("recall@10"),
            "recall@20": overall.get("recall@20"),
            "hit@10": overall.get("hit@10"),
            "mrr": overall.get("mrr"),
            "ndcg@10": overall.get("ndcg@10"),
        },
        "by_type": {
            t: {
                "recall@10": (by_type.get(t) or {}).get("recall@10"),
                "hit@10": (by_type.get(t) or {}).get("hit@10"),
                "mrr": (by_type.get(t) or {}).get("mrr"),
            }
            for t in focus_types
            if t in by_type
        },
        "promotion": gate,
        "candidate_reduction": crr,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--variants", default="A,B,C,D,E,F")
    p.add_argument("--skip-crr", action="store_true")
    p.add_argument("--crr-limit", type=int, default=40)
    args = p.parse_args()
    names = [x.strip().upper() for x in args.variants.split(",") if x.strip()]

    rows = []
    for name in names:
        if name not in VARIANTS:
            raise SystemExit(f"Unknown variant {name}; choose from {list(VARIANTS)}")
        cfg = VARIANTS[name]
        env_extra = {k: v for k, v in cfg.items() if k != "label"}
        print(f"=== P5.6-A variant {name}: {cfg['label']} ===", flush=True)
        summary = run_eval(name, env_extra)
        crr = None
        if not args.skip_crr and cfg["MATTER_SCOPE"] in {"hard", "hier"}:
            print(f"  probing CRR ({args.crr_limit} matter_retrieval)…", flush=True)
            crr = asyncio.run(probe_crr(env_extra, limit=args.crr_limit))
        row = extract_row(name, summary, crr)
        rows.append(row)
        print(json.dumps(row, indent=2), flush=True)

    payload = {
        "baseline": "p55_repair_ce_protect + exact-title repair",
        "p55_metrics": P55_BASELINE,
        "promotion_rule": "ΔR@10>=+1pp AND ΔHit@10>=+1pp AND ΔMRR>=+1pp AND exact Hit@10>=0.99",
        "runs": rows,
    }
    out = ROOT / "evals" / "last_matter_routing_ablation.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
