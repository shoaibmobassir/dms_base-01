# Harbour retrieval benchmark

n=307 k=20

| Metric | Score |
| ------ | ----: |
| recall@5 | 0.9293 |
| recall@10 | 0.9439 |
| recall@20 | 0.9450 |
| hit@5 | 0.9674 |
| hit@10 | 0.9674 |
| mrr | 0.9260 |
| ndcg@10 | 0.9302 |

## By type

| Type | n | R@10 | Hit@10 | MRR |
| ---- | -: | ---: | -----: | --: |
| argument | 170 | 0.9765 | 0.9765 | 0.9765 |
| client_matter | 21 | 0.7102 | 0.9048 | 0.9048 |
| document_title | 48 | 0.9583 | 0.9583 | 0.9444 |
| exact | 36 | 0.9444 | 0.9444 | 0.9444 |
| negative | 4 | 1.0000 | 1.0000 | 1.0000 |
| related_matter | 24 | 0.9272 | 1.0000 | 0.5465 |
| semantic | 4 | 0.6562 | 1.0000 | 0.7083 |

Cold p50 134.2 ms · p95 1511.4 ms
Matter scope resolved 0.7654 (n=243, median document universe 4)
Stage latency ms: {"rerank": {"n": 13, "p50": 1111.2, "p95": 4715.5}, "parallel_wall_ms": {"n": 307, "p50": 115.7, "p95": 1025.6}, "bm25": {"n": 307, "p50": 67.0, "p95": 917.1}, "vector": {"n": 247, "p50": 52.4, "p95": 608.5}, "matter_scope_ms": {"n": 243, "p50": 4.2, "p95": 27.6}}
Immediate cache repeat p50 3.4 ms (12/12 hits). This is not an end-of-run warm number.

Intents: {"exact_lookup": 36, "graph_reasoning": 24, "matter_research": 243, "semantic": 4}

Channel nonzero rate: {"argument_scope": 0.5407, "bm25": 0.9967, "final": 1.0, "graph_seed": 0.684, "hierarchical": 0.1922, "matter_scope": 0.6059, "metadata": 0.7166, "party_span": 0.0033, "title_match": 0.1466, "vector": 0.785}
