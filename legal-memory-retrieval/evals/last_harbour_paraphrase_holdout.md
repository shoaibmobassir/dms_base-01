# Harbour retrieval benchmark

n=20 k=20

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
| argument | 20 | 1.0000 | 1.0000 | 1.0000 |

Cold p50 30.6 ms · p95 234.5 ms
Matter scope resolved 1.0000 (n=20, median document universe 5.0)
Stage latency ms: {"parallel_wall_ms": {"n": 20, "p50": 23.5, "p95": 227.9}, "bm25": {"n": 20, "p50": 20.5, "p95": 227.8}, "vector": {"n": 20, "p50": 18.3, "p95": 29.4}, "matter_scope_ms": {"n": 20, "p50": 3.3, "p95": 7.0}}
Immediate cache repeat p50 1.3 ms (12/12 hits). This is not an end-of-run warm number.

Intents: {"matter_research": 20}

Channel nonzero rate: {"argument_scope": 1.0, "bm25": 1.0, "final": 1.0, "graph_seed": 1.0, "matter_scope": 1.0, "metadata": 1.0, "vector": 1.0}
