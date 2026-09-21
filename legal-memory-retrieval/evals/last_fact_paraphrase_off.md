# Harbour retrieval benchmark

n=18 k=20

| Metric | Score |
| ------ | ----: |
| recall@5 | 0.9556 |
| recall@10 | 0.9556 |
| recall@20 | 0.9667 |
| hit@5 | 1.0000 |
| hit@10 | 1.0000 |
| mrr | 0.9556 |
| ndcg@10 | 0.9517 |

## By type

| Type | n | R@10 | Hit@10 | MRR |
| ---- | -: | ---: | -----: | --: |
| fact_ambiguous | 8 | 1.0000 | 1.0000 | 1.0000 |
| fact_unique | 8 | 0.9000 | 1.0000 | 0.9000 |
| negative | 2 | 1.0000 | 1.0000 | 1.0000 |

Cold p50 33.3 ms · p95 1047.7 ms
Matter scope resolved 0.8333 (n=18, median document universe 3.0)
Stage latency ms: {"rerank": {"n": 3, "p50": 381.9, "p95": 9384.1}, "parallel_wall_ms": {"n": 18, "p50": 25.7, "p95": 665.0}, "bm25": {"n": 18, "p50": 17.3, "p95": 664.8}, "vector": {"n": 18, "p50": 23.4, "p95": 241.8}, "matter_scope_ms": {"n": 18, "p50": 5.5, "p95": 17.5}}
Immediate cache repeat p50 2.1 ms (12/12 hits). This is not an end-of-run warm number.

Intents: {"matter_research": 18}

Channel nonzero rate: {"argument_scope": 0.8333, "bm25": 1.0, "final": 1.0, "graph_seed": 0.8333, "matter_scope": 0.8333, "metadata": 0.8333, "party_span": 0.8889, "vector": 0.9444}
