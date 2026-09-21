# Harbour retrieval benchmark

n=307 k=20

| Metric | Score |
| ------ | ----: |
| recall@5 | 0.9562 |
| recall@10 | 0.9711 |
| recall@20 | 0.9721 |
| hit@5 | 0.9935 |
| hit@10 | 0.9935 |
| mrr | 0.9542 |
| ndcg@10 | 0.9587 |

## By type

| Type | n | R@10 | Hit@10 | MRR |
| ---- | -: | ---: | -----: | --: |
| argument | 170 | 1.0000 | 1.0000 | 1.0000 |
| client_matter | 21 | 0.8096 | 1.0000 | 1.0000 |
| document_title | 48 | 0.9583 | 0.9583 | 0.9444 |
| exact | 36 | 1.0000 | 1.0000 | 1.0000 |
| negative | 4 | 1.0000 | 1.0000 | 1.0000 |
| related_matter | 24 | 0.9272 | 1.0000 | 0.5465 |
| semantic | 4 | 0.7188 | 1.0000 | 0.8750 |

Cold p50 55.1 ms · p95 1668.8 ms
Matter scope resolved 0.7860 (n=243, median document universe 4)
Stage latency ms: {"rerank": {"n": 8, "p50": 657.4, "p95": 10434.6}, "parallel_wall_ms": {"n": 307, "p50": 49.9, "p95": 1651.1}, "bm25": {"n": 307, "p50": 39.6, "p95": 1650.9}, "vector": {"n": 247, "p50": 15.9, "p95": 63.2}, "matter_scope_ms": {"n": 243, "p50": 2.7, "p95": 4.2}}
Immediate cache repeat p50 1.3 ms (12/12 hits). This is not an end-of-run warm number.

Intents: {"exact_lookup": 36, "graph_reasoning": 24, "matter_research": 243, "semantic": 4}

Channel nonzero rate: {"argument_scope": 0.5537, "bm25": 0.9967, "final": 1.0, "graph_seed": 0.7003, "hierarchical": 0.1987, "matter_scope": 0.6221, "metadata": 0.7394, "title_match": 0.1466, "vector": 0.7883}
