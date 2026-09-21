# Harbour retrieval benchmark

n=191 k=20

| Metric | Score |
| ------ | ----: |
| recall@5 | 0.7825 |
| recall@10 | 0.8659 |
| recall@20 | 0.8872 |
| hit@5 | 0.9686 |
| hit@10 | 1.0000 |
| mrr | 0.9365 |
| ndcg@10 | 0.8691 |

## By type

| Type | n | R@10 | Hit@10 | MRR |
| ---- | -: | ---: | -----: | --: |
| argument | 170 | 0.8726 | 1.0000 | 0.9287 |
| client_matter | 21 | 0.8114 | 1.0000 | 1.0000 |

Cold p50 26.4 ms · p95 101.3 ms
Matter scope resolved 1.0000 (n=191, median document universe 6)
Stage latency ms: {"parallel_wall_ms": {"n": 191, "p50": 22.4, "p95": 95.6}, "bm25": {"n": 191, "p50": 15.5, "p95": 80.7}, "vector": {"n": 191, "p50": 14.4, "p95": 29.2}, "matter_scope_ms": {"n": 191, "p50": 2.1, "p95": 2.6}}
Immediate cache repeat p50 0.8 ms (12/12 hits). This is not an end-of-run warm number.

Intents: {"matter_research": 191}

Channel nonzero rate: {"argument_scope": 0.8901, "bm25": 0.9948, "final": 1.0, "graph_seed": 1.0, "hierarchical": 0.3194, "matter_scope": 1.0, "metadata": 1.0, "vector": 0.9843}
