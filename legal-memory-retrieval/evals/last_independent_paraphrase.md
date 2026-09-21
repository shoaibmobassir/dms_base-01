# Harbour retrieval benchmark

n=40 k=20

| Metric | Score |
| ------ | ----: |
| recall@5 | 1.0000 |
| recall@10 | 1.0000 |
| recall@20 | 1.0000 |
| hit@5 | 1.0000 |
| hit@10 | 1.0000 |
| mrr | 1.0000 |
| ndcg@10 | 1.0000 |

## By type

| Type | n | R@10 | Hit@10 | MRR |
| ---- | -: | ---: | -----: | --: |
| paraphrase | 40 | 1.0000 | 1.0000 | 1.0000 |

Cold p50 39.1 ms · p95 314.0 ms
Matter scope resolved 1.0000 (n=40, median document universe 6.0)
Stage latency ms: {"parallel_wall_ms": {"n": 40, "p50": 33.2, "p95": 189.1}, "bm25": {"n": 40, "p50": 30.3, "p95": 181.4}, "vector": {"n": 40, "p50": 31.8, "p95": 151.8}, "matter_scope_ms": {"n": 40, "p50": 3.5, "p95": 7.1}}
Immediate cache repeat p50 0.8 ms (12/12 hits). This is not an end-of-run warm number.

Intents: {"matter_research": 40}

Channel nonzero rate: {"argument_scope": 1.0, "bm25": 1.0, "final": 1.0, "graph_seed": 1.0, "matter_scope": 1.0, "metadata": 1.0, "vector": 1.0}
