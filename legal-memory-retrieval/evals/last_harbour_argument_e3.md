# Harbour retrieval benchmark

n=170 k=20

| Metric | Score |
| ------ | ----: |
| recall@5 | 0.7854 |
| recall@10 | 0.8654 |
| recall@20 | 0.9066 |
| hit@5 | 0.9765 |
| hit@10 | 1.0000 |
| mrr | 0.9101 |
| ndcg@10 | 0.8501 |

## By type

| Type | n | R@10 | Hit@10 | MRR |
| ---- | -: | ---: | -----: | --: |
| argument | 170 | 0.8654 | 1.0000 | 0.9101 |

Cold p50 564.7 ms · p95 812.6 ms
Matter scope resolved 1.0000 (n=170, median document universe 6.0)
Stage latency ms: {"rerank": {"n": 170, "p50": 522.4, "p95": 711.7}, "parallel_wall_ms": {"n": 170, "p50": 32.5, "p95": 111.8}, "bm25": {"n": 170, "p50": 24.1, "p95": 108.1}, "vector": {"n": 170, "p50": 21.7, "p95": 47.0}, "matter_scope_ms": {"n": 170, "p50": 6.1, "p95": 10.5}}
Immediate cache repeat p50 1.8 ms (12/12 hits). This is not an end-of-run warm number.

Intents: {"matter_research": 170}

Channel nonzero rate: {"argument_scope": 1.0, "bm25": 1.0, "final": 1.0, "graph_seed": 1.0, "hierarchical": 0.2412, "matter_scope": 1.0, "metadata": 1.0, "vector": 0.9882}
