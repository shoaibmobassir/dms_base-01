# Harbour retrieval benchmark

n=333 k=20

| Metric | Score |
| ------ | ----: |
| recall@5 | 0.9628 |
| recall@10 | 0.9759 |
| recall@20 | 0.9777 |
| hit@5 | 0.9910 |
| hit@10 | 0.9940 |
| mrr | 0.9238 |
| ndcg@10 | 0.9384 |

## By type

| Type | n | R@10 | Hit@10 | MRR |
| ---- | -: | ---: | -----: | --: |
| client_name | 21 | 0.7917 | 1.0000 | 0.9683 |
| document_name | 40 | 0.9500 | 0.9500 | 0.6792 |
| matter_code | 34 | 1.0000 | 1.0000 | 1.0000 |
| matter_name | 170 | 1.0000 | 1.0000 | 1.0000 |
| negative | 4 | 1.0000 | 1.0000 | 1.0000 |
| paraphrase | 40 | 1.0000 | 1.0000 | 1.0000 |
| related_matter | 24 | 0.9314 | 1.0000 | 0.5049 |

Cold p50 26.2 ms · p95 2269.2 ms
Matter scope resolved 0.8576 (n=309, median document universe 4)
Stage latency ms: {"rerank": {"n": 44, "p50": 618.1, "p95": 939.1}, "parallel_wall_ms": {"n": 333, "p50": 21.4, "p95": 1615.3}, "bm25": {"n": 333, "p50": 16.9, "p95": 1615.2}, "vector": {"n": 275, "p50": 16.2, "p95": 54.5}, "matter_scope_ms": {"n": 309, "p50": 2.7, "p95": 8.5}}
Immediate cache repeat p50 2.0 ms (12/12 hits). This is not an end-of-run warm number.

Intents: {"graph_reasoning": 24, "matter_research": 309}

Channel nonzero rate: {"argument_scope": 0.1201, "bm25": 0.8949, "final": 1.0, "graph_seed": 0.8679, "hierarchical": 0.1832, "matter_scope": 0.7958, "metadata": 0.7958, "vector": 0.7658}
