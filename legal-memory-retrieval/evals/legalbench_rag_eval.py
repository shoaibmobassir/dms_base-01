"""LegalBench-RAG retrieval eval: character-span precision and recall @k (plan 14, A2).

For each query the engine retrieves top-k chunks; each chunk is located in its source file.
Scores follow the benchmark's definition, per query then averaged:

  recall@k    = gold characters covered by the top-k chunks / gold characters
  precision@k = gold characters covered / characters in the top-k chunks

Runs in-process against the *benchmark* database prepared by legalbench_rag_prepare.py
(same engine call as evals/harbour_retrieval_eval.py). It refuses the firm database.

    DATABASE_URL=postgresql://…/legalbench_rag REDIS_URL=redis://localhost:6380/9 \\
        python evals/legalbench_rag_eval.py --prepared data/benchmarks/legalbenchrag_prepared
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

OUT = ROOT / "evals"
KS = (1, 2, 4, 8, 16, 32, 64)

Interval = tuple[int, int]


def union(spans: list[Interval]) -> list[Interval]:
    merged: list[Interval] = []
    for s, e in sorted(x for x in spans if x[1] > x[0]):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def length(spans: list[Interval]) -> int:
    return sum(e - s for s, e in spans)


def overlap(a: list[Interval], b: list[Interval]) -> int:
    """Characters shared by two already-merged interval lists."""
    i = j = total = 0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        total += max(0, hi - lo)
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return total


def span_scores(retrieved: list[tuple[str, int, int]], gold: list[tuple[str, int, int]]) -> tuple[float, float]:
    """(precision, recall) over characters; spans are (file, start, end)."""
    by_file_r: dict[str, list[Interval]] = defaultdict(list)
    by_file_g: dict[str, list[Interval]] = defaultdict(list)
    for f, s, e in retrieved:
        by_file_r[f].append((s, e))
    for f, s, e in gold:
        by_file_g[f].append((s, e))
    r_len = g_len = hit = 0
    for f in set(by_file_r) | set(by_file_g):
        r, g = union(by_file_r.get(f, [])), union(by_file_g.get(f, []))
        r_len, g_len, hit = r_len + length(r), g_len + length(g), hit + overlap(r, g)
    return (hit / r_len if r_len else 0.0), (hit / g_len if g_len else 0.0)


class Locator:
    """Chunk text → (file, start, end) in the original .txt the benchmark's spans refer to."""

    def __init__(self, corpus_texts: dict[str, str]):
        self.texts = corpus_texts
        self.misses = 0

    def locate(self, file_path: str, chunk: str) -> tuple[str, int, int] | None:
        text = self.texts.get(file_path)
        if text is None or not chunk:
            self.misses += 1
            return None
        at = text.find(chunk)
        if at < 0:  # chunk text was whitespace-normalised somewhere; anchor on its first line
            head = chunk.strip().split("\n", 1)[0][:200]
            at = text.find(head) if head else -1
            if at < 0:
                self.misses += 1
                return None
        return file_path, at, at + len(chunk)


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))] if ordered else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepared", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="comma-separated benchmark names")
    ap.add_argument("--tag", default="legalbench_rag")
    args = ap.parse_args()

    from app.config import settings
    from evals.legalbench_rag_prepare import assert_bench_env

    assert_bench_env(settings.database_url, "postgresql://x/legal_memory")
    from app.db.connection import connect
    from app.retrieval.engine import retrieve

    doc_map: dict[str, str] = json.loads((args.prepared / "doc_map.json").read_text())
    texts = {}
    for line in (args.prepared / "documents.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        texts[d["source_path"]] = d["text"]
    loc = Locator(texts)
    rows = [json.loads(l) for l in (args.prepared / "queries.jsonl").read_text().splitlines() if l.strip()]
    if args.only:
        rows = [r for r in rows if r["benchmark"] in set(args.only.split(","))]
    if args.limit:
        rows = rows[: args.limit]

    per_query: list[dict] = []
    with connect() as conn:
        for row in rows:
            t0 = time.perf_counter()
            hits, _lat = retrieve(conn, row["query"], member_id=None, k=max(KS))
            ms = (time.perf_counter() - t0) * 1000
            spans = [loc.locate(doc_map.get(h.get("document_id") or "", ""), h.get("text") or "") for h in hits]
            spans = [s for s in spans if s]
            gold = [(s["file_path"], s["span"][0], s["span"][1]) for s in row["snippets"]]
            gold_files = {g[0] for g in gold}
            scores = {}
            for k in KS:
                p, r = span_scores(spans[:k], gold)
                scores[f"p@{k}"], scores[f"r@{k}"] = p, r
                scores[f"doc_hit@{k}"] = float(any(s[0] in gold_files for s in spans[:k]))
            per_query.append({"id": row["id"], "benchmark": row["benchmark"], "ms": ms, "n_hits": len(hits), **scores})

    def block(rs: list[dict]) -> dict:
        out = {"n": len(rs)}
        for key in [f"{m}@{k}" for k in KS for m in ("p", "r", "doc_hit")]:
            out[key] = round(statistics.mean(r[key] for r in rs), 4) if rs else None
        ms = [r["ms"] for r in rs]
        out["p50_ms"], out["p95_ms"] = round(_pct(ms, 0.5), 1), round(_pct(ms, 0.95), 1)
        return out

    summary = {"overall": block(per_query),
               "by_benchmark": {b: block([r for r in per_query if r["benchmark"] == b])
                                for b in sorted({r["benchmark"] for r in per_query})},
               "locate_misses": loc.misses}
    (OUT / f"last_{args.tag}.json").write_text(json.dumps({"summary": summary, "results": per_query}, indent=1))
    lines = [f"# LegalBench-RAG retrieval ({args.tag})", "", f"n={len(per_query)} · chunk locate misses {loc.misses}", "",
             "| Benchmark | n | P@1 | R@1 | P@8 | R@8 | R@16 | R@64 | doc hit@8 | p50 ms | p95 ms |",
             "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for name, b in [("overall", summary["overall"]), *summary["by_benchmark"].items()]:
        lines.append(f"| {name} | {b['n']} | {b['p@1']} | {b['r@1']} | {b['p@8']} | {b['r@8']} | {b['r@16']} | "
                     f"{b['r@64']} | {b['doc_hit@8']} | {b['p50_ms']} | {b['p95_ms']} |")
    (OUT / f"last_{args.tag}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
