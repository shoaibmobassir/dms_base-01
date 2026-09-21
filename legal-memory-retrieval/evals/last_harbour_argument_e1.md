# Harbour retrieval benchmark

n=170 k=20

| Metric | Score |
| ------ | ----: |
| recall@5 | 0.6271 |
| recall@10 | 0.6976 |
| recall@20 | 0.7329 |
| hit@5 | 0.9000 |
| hit@10 | 0.9353 |
| mrr | 0.7927 |
| ndcg@10 | 0.6902 |

## By type

| Type | n | R@10 | Hit@10 | MRR |
| ---- | -: | ---: | -----: | --: |
| argument | 170 | 0.6976 | 0.9353 | 0.7927 |

Cold p50 626.3 ms · p95 865.8 ms
Matter scope resolved 0.0000 (n=0, median document universe 0.0)
Stage latency ms: {"rerank": {"n": 170, "p50": 580.4, "p95": 782.4}, "parallel_wall_ms": {"n": 170, "p50": 36.1, "p95": 116.3}, "bm25": {"n": 170, "p50": 25.2, "p95": 115.2}, "vector": {"n": 170, "p50": 25.2, "p95": 70.1}, "matter_scope_ms": {"n": 170, "p50": 6.7, "p95": 11.1}}
Immediate cache repeat p50 1.9 ms (12/12 hits). This is not an end-of-run warm number.

Intents: {"matter_research": 170}

Channel nonzero rate: {"bm25": 1.0, "final": 1.0, "graph_seed": 1.0, "hierarchical": 0.2412, "matter_scope": 1.0, "metadata": 1.0, "vector": 0.9882}
