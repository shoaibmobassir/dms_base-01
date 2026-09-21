#!/usr/bin/env python3
"""Score the live retrieval engine on the Harbour Chambers benchmark.

Measures retrieval only (not the answer LLM). Reports Recall/Hit/MRR/nDCG by
query type, analyser intent, channel contribution, and cold vs cached latency.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from app.db.connection import connect
from app.query.understand import understand
from app.retrieval.engine import retrieve
from evals.metrics import mrr, ndcg_at_k, recall_at_k

DATASET = ROOT / "evals" / "harbour_benchmark.jsonl"
OUT_JSON = ROOT / "evals" / "last_harbour_retrieval.json"
OUT_MD = ROOT / "evals" / "last_harbour_retrieval.md"
K = 20


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((pct / 100) * (len(ordered) - 1)))))
    return round(ordered[idx], 1)


def _score(row: dict, hits: list[dict]) -> dict:
    ranked_docs = list(dict.fromkeys(h.get("document_id") for h in hits if h.get("document_id")))
    ranked_matters = list(dict.fromkeys(h.get("matter_id") for h in hits if h.get("matter_id")))
    gold_docs = set(row.get("expected_documents") or [])
    gold_matters = set(row.get("expected_matters") or [])

    if row["type"] == "negative":
        terms = [t.lower() for t in (row.get("absent_terms") or [])]
        blob = " ".join(
            f"{h.get('title') or ''} {h.get('text') or ''}" for h in hits[:10]
        ).lower()
        leaked = any(term in blob for term in terms)
        return {
            "recall@5": 1.0 if not leaked else 0.0,
            "recall@10": 1.0 if not leaked else 0.0,
            "recall@20": 1.0 if not leaked else 0.0,
            "hit@5": 1.0 if not leaked else 0.0,
            "hit@10": 1.0 if not leaked else 0.0,
            "mrr": 1.0 if not leaked else 0.0,
            "ndcg@10": 1.0 if not leaked else 0.0,
            "topic_leak": leaked,
        }

    target = row.get("gold_target") or ("document" if gold_docs else "matter")
    if target == "document" and gold_docs:
        ranked, gold = ranked_docs, gold_docs
    else:
        ranked, gold = ranked_matters, gold_matters
    return {
        "recall@5": recall_at_k(gold, ranked, 5),
        "recall@10": recall_at_k(gold, ranked, 10),
        "recall@20": recall_at_k(gold, ranked, 20),
        "hit@5": 1.0 if set(ranked[:5]) & gold else 0.0,
        "hit@10": 1.0 if set(ranked[:10]) & gold else 0.0,
        "mrr": mrr(gold, ranked),
        "ndcg@10": ndcg_at_k(gold, ranked, 10),
    }


def _avg(rows: list[dict], key: str) -> float:
    vals = [r[key] for r in rows if key in r]
    return round(sum(vals) / len(vals), 4) if vals else 0.0


_STAGE_KEYS = ("rerank", "parallel_wall_ms", "bm25", "vector", "matter_scope_ms")


def summarize_stage_latency(samples: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for key in _STAGE_KEYS:
        values = samples.get(key) or []
        if not values:
            continue
        out[key] = {
            "n": len(values),
            "p50": _percentile(values, 50),
            "p95": _percentile(values, 95),
        }
    return out


def summarize_matter_scope(scope_rows: list[dict]) -> dict:
    if not scope_rows:
        return {"n": 0, "resolved_rate": 0.0, "median_document_universe": 0.0}
    resolved = sum(1 for row in scope_rows if int(row.get("matter_count") or 0) > 0)
    universes = [int(row.get("document_universe") or 0) for row in scope_rows]
    return {
        "n": len(scope_rows),
        "resolved_rate": round(resolved / len(scope_rows), 4),
        "median_document_universe": round(statistics.median(universes), 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Harbour retrieval benchmark")
    parser.add_argument(
        "--types",
        default="",
        help="Comma-separated question types (default: all)",
    )
    parser.add_argument(
        "--dataset",
        default=str(DATASET),
        help="JSONL gold file",
    )
    parser.add_argument(
        "--out-stem",
        default="last_harbour_retrieval",
        help="Output stem under evals/ (full runs only; subsets do not overwrite unless set)",
    )
    args = parser.parse_args()
    dataset = Path(args.dataset)
    if not dataset.is_absolute():
        dataset = ROOT / dataset
    if not dataset.exists():
        raise SystemExit(f"missing {dataset}; run evals/build_harbour_benchmark.py")
    questions = [
        json.loads(line)
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.types.strip():
        wanted = {part.strip() for part in args.types.split(",") if part.strip()}
        questions = [row for row in questions if row.get("type") in wanted]
    if not questions:
        raise SystemExit("no questions after --types filter")
    subset = bool(args.types.strip()) or dataset.resolve() != DATASET.resolve()
    by_type: dict[str, list[dict]] = defaultdict(list)
    intents: dict[str, int] = defaultdict(int)
    channel_nonzero: dict[str, int] = defaultdict(int)
    latencies: list[float] = []
    stage_samples: dict[str, list[float]] = defaultdict(list)
    scope_rows: list[dict] = []
    scope_by_type: dict[str, list[dict]] = defaultdict(list)
    scored: list[dict] = []

    with connect() as conn:
        for row in questions:
            parsed = understand(row["question"])
            intents[parsed.intent] += 1
            t0 = time.perf_counter()
            hits, latency = retrieve(conn, row["question"], member_id=row.get("as_member"), k=K)
            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            latencies.append(elapsed)
            for key, value in (latency or {}).items():
                if key.endswith("_count") and isinstance(value, int) and value > 0:
                    channel_nonzero[key.removesuffix("_count")] += 1
                if key in _STAGE_KEYS and isinstance(value, (int, float)):
                    stage_samples[key].append(float(value))
            scope = (latency or {}).get("matter_scope")
            if isinstance(scope, dict):
                scope_rows.append(scope)
                scope_by_type[row["type"]].append(scope)
            scores = _score(row, hits)
            item = {
                "question_id": row["question_id"],
                "type": row["type"],
                "intent": parsed.intent,
                "latency_ms": elapsed,
                "cache": (latency or {}).get("cache"),
                "n_hits": len(hits),
                **scores,
            }
            scored.append(item)
            by_type[row["type"]].append(item)
            print(
                f"{row['question_id']} {row['type']} intent={parsed.intent} "
                f"hit@10={scores['hit@10']:.0f} {elapsed:.0f}ms",
                flush=True,
            )

        # Immediate repeat, while the 5-minute retrieval TTL is still live.
        warm: list[float] = []
        warm_hits = 0
        for row in questions[:12]:
            t0 = time.perf_counter()
            _hits, latency = retrieve(conn, row["question"], member_id=row.get("as_member"), k=K)
            warm.append(round((time.perf_counter() - t0) * 1000, 1))
            if (latency or {}).get("cache") == "hit":
                warm_hits += 1
            else:
                print(f"WARN cache miss on repeat {row['question_id']}", flush=True)

    summary = {
        "corpus": "harbour-chambers-pcij-unsc-india",
        "n": len(scored),
        "k": K,
        "overall": {
            "recall@5": _avg(scored, "recall@5"),
            "recall@10": _avg(scored, "recall@10"),
            "recall@20": _avg(scored, "recall@20"),
            "hit@5": _avg(scored, "hit@5"),
            "hit@10": _avg(scored, "hit@10"),
            "mrr": _avg(scored, "mrr"),
            "ndcg@10": _avg(scored, "ndcg@10"),
        },
        "by_type": {
            name: {
                "n": len(rows),
                "recall@10": _avg(rows, "recall@10"),
                "hit@5": _avg(rows, "hit@5"),
                "hit@10": _avg(rows, "hit@10"),
                "mrr": _avg(rows, "mrr"),
                "ndcg@10": _avg(rows, "ndcg@10"),
            }
            for name, rows in sorted(by_type.items())
        },
        "analyser_intents": dict(sorted(intents.items())),
        "channel_nonzero_rate": {
            name: round(count / len(scored), 4) if scored else 0.0
            for name, count in sorted(channel_nonzero.items())
        },
        "latency_ms": {
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "mean": round(statistics.fmean(latencies), 1) if latencies else 0.0,
        },
        "stage_latency_ms": summarize_stage_latency(stage_samples),
        "matter_scope": summarize_matter_scope(scope_rows),
        "matter_scope_by_type": {
            name: summarize_matter_scope(rows) for name, rows in sorted(scope_by_type.items())
        },
        "cache_repeat_ms": {
            "n": len(warm),
            "hits": warm_hits,
            "p50": _percentile(warm, 50),
            "mean": round(statistics.fmean(warm), 1) if warm else 0.0,
            "protocol": "immediate repeat of the first 12 questions while the retrieval TTL is still live",
        },
        "notes": [
            "Negative rows score topic leakage, not empty result sets. Hybrid search always returns neighbours.",
            "Permission gold is empty in this corpus (restricted_matters=0), so ACL is not a scored type.",
            "Apex evals/dataset.jsonl is a different corpus and was not used.",
            "cache_repeat_ms is an immediate repeat, not an end-of-run warm number. A multi-minute eval outlives the 5-minute L3 TTL.",
        ],
    }
    if subset:
        summary["filter"] = args.types or dataset.name
    out_json = OUT_JSON
    out_md = OUT_MD
    if subset:
        stem = args.out_stem if args.out_stem != "last_harbour_retrieval" else "last_harbour_retrieval_subset"
        out_json = ROOT / "evals" / f"{stem}.json"
        out_md = ROOT / "evals" / f"{stem}.md"
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = [
        "# Harbour retrieval benchmark",
        "",
        f"n={summary['n']} k={K}",
        "",
        "| Metric | Score |",
        "| ------ | ----: |",
    ]
    for key, value in summary["overall"].items():
        lines.append(f"| {key} | {value:.4f} |")
    lines += ["", "## By type", "", "| Type | n | R@10 | Hit@10 | MRR |", "| ---- | -: | ---: | -----: | --: |"]
    for name, block in summary["by_type"].items():
        lines.append(
            f"| {name} | {block['n']} | {block['recall@10']:.4f} | {block['hit@10']:.4f} | {block['mrr']:.4f} |"
        )
    scope = summary["matter_scope"]
    lines += [
        "",
        f"Cold p50 {summary['latency_ms']['p50']} ms · p95 {summary['latency_ms']['p95']} ms",
        (
            f"Matter scope resolved {scope['resolved_rate']:.4f} "
            f"(n={scope['n']}, median document universe {scope['median_document_universe']})"
        ),
        "Stage latency ms: " + json.dumps(summary["stage_latency_ms"]),
        (
            f"Immediate cache repeat p50 {summary['cache_repeat_ms']['p50']} ms "
            f"({summary['cache_repeat_ms']['hits']}/{summary['cache_repeat_ms']['n']} hits). "
            "This is not an end-of-run warm number."
        ),
        "",
        "Intents: " + json.dumps(summary["analyser_intents"]),
        "",
        "Channel nonzero rate: " + json.dumps(summary["channel_nonzero_rate"]),
    ]
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
