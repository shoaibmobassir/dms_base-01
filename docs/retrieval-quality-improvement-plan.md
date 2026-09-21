# Combined Harbour retrieval plan

**Status:** Adopted 2026-09-14. This file is the only retrieval-quality plan. An earlier draft that added an argument FTS channel, contextual embeddings, hash partitions, sampled graphs, and a bloom cache was rejected. Those experiments target the wrong stage and can regress scores already earned.

**Objective:** Improve Harbour argument retrieval without retuning frozen fusion, and keep the path viable at millions of documents by scoping before rank and measuring named stages.

## Verdict

Argument ranking is the remaining gap. Related-matter Hit@10 must stay 1.0. Million-document work needs bounded metrics. The failure is not missing embeddings or fusion weights.

Harbour argument questions are `Which documents support our argument on {matter.title}?`. They route as `matter_research`. Hard scope ILIKE-matches the full boilerplate, not the title, so those rows fall back to unscoped hybrid search. Evidence from the 2026-09-12 full run: `matter_scope` nonzero rate **0.0684 = 21/307**, exactly the client-matter rows whose prefixes already strip.

That miss is also the scale bug. `MATTER_SCOPE=hard` exists so HNSW and GIN never scan millions of chunks. Partitioning, bloom filters, and sampled graphs do not fix a resolver that returns zero matters.

**Adopted (narrowed):** bounded Prometheus labels (`intent`, `scoped`, `tier`); a slow-query counter that does not store query text; channel attribution from the existing diagnose harness; an argument-table lookup only after matter scope succeeds, and only if gold is still missing.

**Not adopted:** keyword `argument_search` intent that changes fusion weights; FTS over `issue` / `position` against the Harbour template; contextual `embedding_arg` plus IVFFlat; hash-partitioned chunks; sampled graph expansion; bloom-filter cache; adaptive tracing that samples on latency that has not happened yet; live Prometheus recall (production has no gold); traffic A/B (scoreboard is offline Harbour n=307); new dependencies (`mmh3`, `bitarray`).

## Why the rejected experiments fail this corpus

- **Argument FTS channel.** Harbour questions do not contain `issue`, `position`, or `argument` prose. `plainto_tsquery` on that text is the same AND-killer already removed from BM25. A sketch that passes `member_id` where an ACL predicate belongs would also skip permissions.
- **Contextual embeddings.** C7.4 / C7.5 already showed chunk vectors and evidence cross-encoder do not rank legal stance here. A second 384-d column cannot invent a matter id the resolver missed.
- **Hash partitions.** Live corpus is 3,081 documents / 170 matters / 36,191 chunks. `matter_id = ANY(...)` only prunes if the resolver succeeded. Claimed p95 ≤ 500 ms at 10M documents contradicts a cross-encoder-bound p50 of about 1.66 s. Partition only if `EXPLAIN ANALYZE` shows a sequential scan that a matter filter does not already avoid.
- **Sampled graph expansion.** Related-matter just reached Hit@10 1.0. Random edge sampling drops neighbours. Stored edges are matter-to-matter, not document-to-document.
- **Bloom cache / 40% hit rate.** The 0/12 repeat was a 509 s run versus a 5-minute TTL, not an 8% product hit rate. A still-cached query was 1.3 ms. Cache keys already include `index_version`, `knowledge_version`, and `permission_version`.
- **Adaptive sampler.** `should_sample` runs at span start. A slow flag set after retrieve cannot raise that trace’s sample rate.
- **Live recall alert.** Recall needs labelled gold. That metric belongs in `evals/last_harbour_retrieval.json`, not Prometheus.

## Baseline numbers

Full Harbour run: n=307, k=20, 509 s. `FUSION_POLICY` and `MATTER_SCOPE` were not changed.

- Overall R@10 **0.6154** / Hit@10 **0.7231** moved because related-matter routing was already fixed (24 rows, Hit@10 1.0).
- Argument is 170/307 and unchanged: R@10 **0.4209**, Hit@10 **0.5647**, MRR **0.4512**.
- Exact, client-matter, and negative stay Hit@10 **1.0**. Related-matter R@10 **0.9272** is capped by two hub seeds (79 neighbours, channel limit 50). Do not retune fusion for that.
- Secondary gap: `document_title` Hit@10 **0.7708** (n=48). Same boilerplate class as argument.
- Cold p50 / p95 **1659 / 2341 ms** is the cross-encoder on about 100 candidates, not pgvector or FTS.

Gold for argument rows is `arguments.supporting_documents` (`legal-memory-retrieval/evals/build_harbour_benchmark.py`). The `arguments` table is browsable and unused in retrieval. Apex `argument_retrieval` is a later issue-bank problem. Do not mix the two.

## Freeze

- `FUSION_POLICY=p55_repair_ce_protect`. Do not edit `_REPAIR_WEIGHTS`. A new channel, if any, gets a typed weight on its own planner branch.
- `MATTER_SCOPE=hard`.
- Production evidence cross-encoder / C7.5 stays off. Embeddings stay MiniLM 384-d behind `app/embeddings`.
- ACL in SQL before ranking.
- No DistilBERT, online channel dropping, OpenSearch, read replicas, pool ×6, retrieval materialized views, graph path-count fusion, Kafka, or Neo4j.
- Primary scoreboard: Harbour n=307. Apex `dataset.jsonl` is a different corpus and is not the live index.
- No new dependencies. Ablations are environment variables plus eval, not a traffic split.

## Gates

Primary, argument n=170:

- `matter_scope` rate from about 0 to **≥ 0.95**
- Hit@10 **0.5647 → ≥ 0.85**
- R@10 **0.4209 → ≥ 0.70** (gold is supporting documents, not every matter document)

Must not regress: exact, client_matter, negative, and related_matter Hit@10 **1.0**.

Secondary: `document_title` Hit@10 **0.7708 → ≥ 0.90**.

Latency: cold p50 stays inside the about-2 s north star. After scope works, p50 should fall. A quality change that adds ≥ 150 ms p50 without a typed skip-CE ablation is a fail.

Paraphrase holdout: 20 non-templated questions so prefix strip does not overfit the Harbour template.

Stop the sequence when the argument gates pass. Do not stack the next experiment in the same change.

## Phase 0 — Measure named stages (no ranking change)

Instrument `legal-memory-retrieval/evals/harbour_retrieval_eval.py` for p50/p95 of `rerank`, `parallel_wall_ms`, `bm25`, `vector`, and `matter_scope_ms`; fraction of rows with `matter_count > 0`; median `document_universe`. Keep the immediate 12-query cache repeat. Do not report the end of a long run as a warm hit. L3 TTL follows `settings.cache_ttl_seconds`.

Prometheus (`app/observability/metrics.py`), bounded labels only:

- latency histogram labelled `intent` and `scoped`
- stage histograms for `understand`, `matter_scope`, `parallel_wall`, `fusion`, `rerank`, with buckets past 2 s
- counters: `matter_scope_resolved_total`, `matter_scope_unscoped_total`, cache hits by `tier` (`l1` / `l3`)
- `retrieval_slow_queries_total` when end-to-end exceeds 2 s — increment only, do not store query text
- pool `requests_waiting` from existing `pool_stats()`

No labels for query text, document id, or matter id.

Tracing: optional OTLP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set; keep the console exporter. No adaptive sampler until a collector exists.

One `EXPLAIN ANALYZE` snapshot of HNSW and GIN with and without a `matter_id` filter. No index knob changes in this phase. Partitioning, replicas, and pool ×6 wait until that snapshot or pool wait says otherwise.

## Phase 1 — Diagnose the argument slice (still no ranking change)

Point `evals/retrieval_diagnose.py` at `evals/harbour_benchmark.jsonl --types argument`.

Report `relevant_drop_stages` and which channels already contain gold. Gold absent from the pool is a named stage, not a fusion miss.

Hypothesis: gold matter never enters `matter_scope`; gold documents sometimes appear via title BM25 and rank outside k. Fix the named stage only.

## Phase 2 — Typed quality experiments

Each experiment: Harbour argument subset first, then full n=307. Append `legal-memory-retrieval/docs/CHANGELOG.md` with argument R@10 / Hit@10, matter-scope rate, stage p50/p95, and the freeze line.

### E1 — Strip boilerplate

Add to `_STRIP_PREFIXES` in `app/query/understand.py`:

- `which documents support our argument on`
- `find the document titled`

Needle becomes the title. Hard ILIKE can resolve. BM25 and vector run inside the matter. Fusion weights untouched. Intent stays `matter_research`.

Add a metric label only (`argument_support` / `document_title` / `other`) on the latency dict. Do not return a new `argument_search` intent.

### E2 — Resolver robustness, only if E1 misses

If punctuation or em-dashes still miss ILIKE: token/OR title match, or `MATTER_RESOLVER=lexical` only for `matter_research`. Cap `limit=20`. Gate on median `document_universe`, not recall alone.

### E3 — Scoped argument lookup, only if gold is still missing after scope

After hard scope, look up `supporting_documents` for the resolved matter ids, join documents and chunks, and apply the existing permission predicate in SQL. Weight lives on that planner branch only. Do not FTS `issue` / `position` against the Harbour template. Do not re-embed. If this ships, write `docs/legal/IP_ORIGIN_RECORD.md` first: product requirement only, no Mike source, no new dependencies.

### E4 — Skip cross-encoder when a matter resolved

If matter ids are set and intent is `matter_research`, skip rerank. Adopt only if argument Hit@10 does not fall more than 2 points and p50 drops. Ablation flag: `SCOPED_MATTER_RERANK=skip`. Default stays rerank-on until that measurement.

## Explicitly out

- Global RRF retune, C7.5 evidence cross-encoder, BGE, GraphRAG, C7.6 evidence aggregation
- Contextual argument embeddings and a second vector column
- Chunk hash partitioning, IVFFlat, sampled graph walks
- Bloom filters, DistilBERT, OpenSearch (swap trigger about 100k chunks; corpus is 36k)
- Grafana and 10M synthetic load tests until someone asks and the series exist
- Baking `to_tsvector(title)` into `chunks.tsv` unless the EXPLAIN baseline shows it in p95

## What scales to millions of documents

1. Resolve a small matter universe, then run HNSW, GIN, and ACL inside it.
2. Keep the cross-encoder O(candidates). A GPU or smaller reranker only if skip-CE fails and scoped p50 is still above 2 s.
3. Corpus growth should show up in vector and BM25 wall-clock, not in the cross-encoder, if scope is working. A rising unscoped counter is the page to fix, not a partition migration.
4. Invalidate cache by version bump, not Redis SCAN, once key cardinality is high.
5. Replicas and a larger pool only if `requests_waiting` shows saturation. Current pool 4–20 matches about 5 concurrent requests times about 4 channels.

## Measurement (from `legal-memory-retrieval/`)

```bash
python evals/harbour_retrieval_eval.py
python evals/retrieval_diagnose.py --dataset evals/harbour_benchmark.jsonl --types argument
pytest tests/test_understand.py tests/test_harbour_benchmark.py tests/test_matter_resolver.py
```

Claim a win only with Harbour numbers in CHANGELOG. Do not claim a percentage lift or p95 ≤ 500 ms at 10M documents without that run.
