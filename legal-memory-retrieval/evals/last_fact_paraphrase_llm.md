# Harbour retrieval benchmark

n=18 k=20

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
| fact_ambiguous | 8 | 1.0000 | 1.0000 | 1.0000 |
| fact_unique | 8 | 1.0000 | 1.0000 | 1.0000 |
| negative | 2 | 1.0000 | 1.0000 | 1.0000 |

Cold p50 24.4 ms · p95 8363.7 ms
Matter scope resolved 0.8889 (n=18, median document universe 3.5)
Stage latency ms: {"rerank": {"n": 2, "p50": 400.7, "p95": 9888.0}, "parallel_wall_ms": {"n": 18, "p50": 17.7, "p95": 745.6}, "bm25": {"n": 18, "p50": 17.6, "p95": 745.5}, "vector": {"n": 18, "p50": 15.2, "p95": 35.7}, "matter_scope_ms": {"n": 18, "p50": 5.2, "p95": 19.3}}
Immediate cache repeat p50 1.7 ms (12/12 hits). This is not an end-of-run warm number.

Intents: {"matter_research": 18}

Channel nonzero rate: {"argument_scope": 0.8889, "bm25": 1.0, "final": 1.0, "graph_seed": 0.8889, "matter_scope": 0.8889, "metadata": 0.8889, "party_span": 0.8889, "vector": 0.9444}
