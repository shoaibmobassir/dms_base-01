"""Retrieval evaluation runner — measures quality across architecture changes.

Computes:
  Recall@K      — fraction of expected documents found in top-K
  MRR           — reciprocal rank of the first expected document
  NDCG@K        — normalized discounted cumulative gain
  Precision@K   — fraction of top-K that are expected documents
  Zero-result % — fraction of queries with no results

Usage:
    python -m evals.evaluate                      # run all queries
    python -m evals.evaluate --query-id eval-001  # run single query
    python -m evals.evaluate --compare v1 v2      # compare two runs

Every retrieval architecture change should produce:
    Recall@10:   before → after
    MRR:         before → after
    NDCG@10:     before → after
    P95 latency: before → after

No merge if Recall@10 drops.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BENCHMARK_PATH = Path(__file__).parent / "benchmark.json"
RESULTS_DIR = Path(__file__).parent / "results"


@dataclass
class QueryResult:
    query_id: str
    query: str
    intent: str
    difficulty: str
    expected_matters: list[str]
    expected_documents: list[str]
    retrieved_matters: list[str]
    retrieved_documents: list[str]
    latency_ms: float
    result_count: int
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    recall_at_50: float = 0.0
    mrr: float = 0.0
    ndcg_at_10: float = 0.0
    precision_at_5: float = 0.0


@dataclass
class EvalSummary:
    timestamp: str
    engine_version: str
    total_queries: int
    evaluated_queries: int  # queries with expected docs/matters
    skipped_queries: int    # queries without expected docs/matters
    avg_recall_at_5: float = 0.0
    avg_recall_at_10: float = 0.0
    avg_recall_at_50: float = 0.0
    avg_mrr: float = 0.0
    avg_ndcg_at_10: float = 0.0
    avg_precision_at_5: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    zero_result_pct: float = 0.0
    by_intent: dict[str, dict[str, float]] = field(default_factory=dict)
    by_difficulty: dict[str, dict[str, float]] = field(default_factory=dict)
    query_results: list[dict] = field(default_factory=list)


# ── Metric computation ──────────────────────────────────────────────────────


def _recall_at_k(retrieved: list[str], expected: list[str], k: int) -> float:
    """Fraction of expected items found in top-K retrieved."""
    if not expected:
        return 0.0
    top_k = set(retrieved[:k])
    found = len(top_k & set(expected))
    return found / len(expected)


def _mrr(retrieved: list[str], expected: list[str]) -> float:
    """Mean Reciprocal Rank — reciprocal of the rank of the first relevant result."""
    expected_set = set(expected)
    for rank, item in enumerate(retrieved, start=1):
        if item in expected_set:
            return 1.0 / rank
    return 0.0


def _dcg_at_k(retrieved: list[str], expected: set[str], k: int) -> float:
    """Discounted Cumulative Gain at K."""
    dcg = 0.0
    for i, item in enumerate(retrieved[:k]):
        if item in expected:
            dcg += 1.0 / math.log2(i + 2)  # i+2 because rank starts at 1
    return dcg


def _ndcg_at_k(retrieved: list[str], expected: list[str], k: int) -> float:
    """Normalized DCG at K."""
    if not expected:
        return 0.0
    expected_set = set(expected)
    actual_dcg = _dcg_at_k(retrieved, expected_set, k)
    # Ideal DCG: all relevant items at top
    ideal = _dcg_at_k(expected, expected_set, k)
    if ideal == 0:
        return 0.0
    return actual_dcg / ideal


def _precision_at_k(retrieved: list[str], expected: list[str], k: int) -> float:
    """Fraction of top-K results that are relevant."""
    if not retrieved[:k]:
        return 0.0
    top_k = retrieved[:k]
    expected_set = set(expected)
    relevant = sum(1 for item in top_k if item in expected_set)
    return relevant / len(top_k)


def _percentile(values: list[float], pct: float) -> float:
    """Compute percentile from sorted values."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = int(len(sorted_v) * pct / 100.0)
    idx = min(idx, len(sorted_v) - 1)
    return sorted_v[idx]


# ── Main evaluation ─────────────────────────────────────────────────────────


def evaluate_query(
    query_spec: dict,
    retrieve_fn,
) -> QueryResult:
    """Run a single benchmark query and compute metrics."""
    query = query_spec["query"]
    expected_matters = query_spec.get("expected_matters", [])
    expected_docs = query_spec.get("expected_documents", [])

    t0 = time.perf_counter()
    hits, latency = retrieve_fn(query)
    elapsed = (time.perf_counter() - t0) * 1000

    retrieved_docs = [h.get("document_id", "") for h in hits if h.get("document_id")]
    retrieved_matters = [h.get("matter_id", "") for h in hits if h.get("matter_id")]

    # Use documents if available, otherwise fall back to matters
    expected = expected_docs if expected_docs else expected_matters
    retrieved = retrieved_docs if expected_docs else retrieved_matters

    return QueryResult(
        query_id=query_spec["id"],
        query=query,
        intent=query_spec.get("intent", ""),
        difficulty=query_spec.get("difficulty", ""),
        expected_matters=expected_matters,
        expected_documents=expected_docs,
        retrieved_matters=list(dict.fromkeys(retrieved_matters)),  # dedup preserving order
        retrieved_documents=list(dict.fromkeys(retrieved_docs)),
        latency_ms=round(elapsed, 1),
        result_count=len(hits),
        recall_at_5=_recall_at_k(retrieved, expected, 5),
        recall_at_10=_recall_at_k(retrieved, expected, 10),
        recall_at_50=_recall_at_k(retrieved, expected, 50),
        mrr=_mrr(retrieved, expected),
        ndcg_at_10=_ndcg_at_k(retrieved, expected, 10),
        precision_at_5=_precision_at_k(retrieved, expected, 5),
    )


def run_evaluation(
    retrieve_fn,
    benchmark_path: str | Path = BENCHMARK_PATH,
    query_id: str | None = None,
    engine_version: str = "current",
) -> EvalSummary:
    """Run the full evaluation benchmark."""
    with open(benchmark_path) as f:
        benchmark = json.load(f)

    queries = benchmark["queries"]
    if query_id:
        queries = [q for q in queries if q["id"] == query_id]

    results: list[QueryResult] = []
    for q in queries:
        result = evaluate_query(q, retrieve_fn)
        results.append(result)

    # Separate queries with and without expected results
    evaluable = [r for r in results if r.expected_documents or r.expected_matters]
    skipped = [r for r in results if not r.expected_documents and not r.expected_matters]

    # Compute aggregates over evaluable queries only
    latencies = [r.latency_ms for r in results]
    zero_results = sum(1 for r in results if r.result_count == 0)

    summary = EvalSummary(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        engine_version=engine_version,
        total_queries=len(queries),
        evaluated_queries=len(evaluable),
        skipped_queries=len(skipped),
        p50_latency_ms=_percentile(latencies, 50),
        p95_latency_ms=_percentile(latencies, 95),
        p99_latency_ms=_percentile(latencies, 99),
        zero_result_pct=round(zero_results / len(results) * 100, 1) if results else 0,
    )

    if evaluable:
        summary.avg_recall_at_5 = round(sum(r.recall_at_5 for r in evaluable) / len(evaluable), 4)
        summary.avg_recall_at_10 = round(sum(r.recall_at_10 for r in evaluable) / len(evaluable), 4)
        summary.avg_recall_at_50 = round(sum(r.recall_at_50 for r in evaluable) / len(evaluable), 4)
        summary.avg_mrr = round(sum(r.mrr for r in evaluable) / len(evaluable), 4)
        summary.avg_ndcg_at_10 = round(sum(r.ndcg_at_10 for r in evaluable) / len(evaluable), 4)
        summary.avg_precision_at_5 = round(sum(r.precision_at_5 for r in evaluable) / len(evaluable), 4)

    # Breakdown by intent
    by_intent: dict[str, list[QueryResult]] = {}
    for r in evaluable:
        by_intent.setdefault(r.intent, []).append(r)
    for intent, group in by_intent.items():
        summary.by_intent[intent] = {
            "count": len(group),
            "avg_recall_at_10": round(sum(r.recall_at_10 for r in group) / len(group), 4),
            "avg_mrr": round(sum(r.mrr for r in group) / len(group), 4),
            "avg_latency_ms": round(sum(r.latency_ms for r in group) / len(group), 1),
        }

    # Breakdown by difficulty
    by_difficulty: dict[str, list[QueryResult]] = {}
    for r in evaluable:
        by_difficulty.setdefault(r.difficulty, []).append(r)
    for diff, group in by_difficulty.items():
        summary.by_difficulty[diff] = {
            "count": len(group),
            "avg_recall_at_10": round(sum(r.recall_at_10 for r in group) / len(group), 4),
            "avg_mrr": round(sum(r.mrr for r in group) / len(group), 4),
        }

    # Attach individual results
    summary.query_results = [
        {
            "id": r.query_id,
            "query": r.query[:80],
            "intent": r.intent,
            "difficulty": r.difficulty,
            "result_count": r.result_count,
            "recall@5": r.recall_at_5,
            "recall@10": r.recall_at_10,
            "mrr": r.mrr,
            "ndcg@10": r.ndcg_at_10,
            "latency_ms": r.latency_ms,
        }
        for r in results
    ]

    return summary


def save_results(summary: EvalSummary, label: str | None = None) -> Path:
    """Save evaluation results to disk for comparison."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    name = label or f"eval_{summary.timestamp.replace(':', '-')}"
    path = RESULTS_DIR / f"{name}.json"
    with open(path, "w") as f:
        json.dump(summary.__dict__, f, indent=2, default=str)
    return path


def print_summary(summary: EvalSummary) -> None:
    """Print a human-readable evaluation summary."""
    print("\n" + "=" * 70)
    print(f"  RETRIEVAL EVALUATION — {summary.engine_version}")
    print(f"  {summary.timestamp}")
    print("=" * 70)
    print(f"\n  Queries: {summary.total_queries} total, "
          f"{summary.evaluated_queries} evaluated, "
          f"{summary.skipped_queries} skipped (no expected docs)")
    print(f"  Zero-result: {summary.zero_result_pct}%")
    print()
    print("  ── Quality Metrics (evaluable queries only) ──")
    print(f"  Recall@5:     {summary.avg_recall_at_5:.4f}")
    print(f"  Recall@10:    {summary.avg_recall_at_10:.4f}")
    print(f"  Recall@50:    {summary.avg_recall_at_50:.4f}")
    print(f"  MRR:          {summary.avg_mrr:.4f}")
    print(f"  NDCG@10:      {summary.avg_ndcg_at_10:.4f}")
    print(f"  Precision@5:  {summary.avg_precision_at_5:.4f}")
    print()
    print("  ── Latency ──")
    print(f"  P50:  {summary.p50_latency_ms:.0f} ms")
    print(f"  P95:  {summary.p95_latency_ms:.0f} ms")
    print(f"  P99:  {summary.p99_latency_ms:.0f} ms")

    if summary.by_intent:
        print()
        print("  ── By Intent ──")
        for intent, metrics in summary.by_intent.items():
            print(f"  {intent:20s}  R@10={metrics['avg_recall_at_10']:.4f}  "
                  f"MRR={metrics['avg_mrr']:.4f}  "
                  f"latency={metrics['avg_latency_ms']:.0f}ms  "
                  f"(n={metrics['count']})")

    if summary.by_difficulty:
        print()
        print("  ── By Difficulty ──")
        for diff, metrics in summary.by_difficulty.items():
            print(f"  {diff:10s}  R@10={metrics['avg_recall_at_10']:.4f}  "
                  f"MRR={metrics['avg_mrr']:.4f}  "
                  f"(n={metrics['count']})")

    print()
    print("  ── Per-Query Results ──")
    for qr in summary.query_results:
        status = "✓" if qr["recall@10"] > 0 else "✗" if qr.get("result_count", 0) > 0 else "∅"
        print(f"  {status} {qr['id']:10s} {qr['intent']:20s} "
              f"R@10={qr['recall@10']:.2f} MRR={qr['mrr']:.2f} "
              f"{qr['latency_ms']:>6.0f}ms  {qr['query']}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run retrieval evaluation benchmark")
    parser.add_argument("--query-id", help="Run a single query by ID")
    parser.add_argument("--engine", default="current", help="Engine version label")
    parser.add_argument("--save", action="store_true", help="Save results to disk")
    parser.add_argument("--label", help="Label for saved results")
    args = parser.parse_args()

    # Import the retrieval function
    try:
        from app.db.connection import connect
        from app.retrieval.engine import retrieve

        def retrieve_fn(query: str):
            with connect() as conn:
                return retrieve(conn, query)
    except ImportError:
        print("Error: Run from the legal-memory-retrieval directory")
        sys.exit(1)

    summary = run_evaluation(
        retrieve_fn,
        query_id=args.query_id,
        engine_version=args.engine,
    )
    print_summary(summary)

    if args.save:
        path = save_results(summary, args.label)
        print(f"\nResults saved to: {path}")
