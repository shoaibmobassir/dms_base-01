# Harbour retrieval benchmark

n=48 k=20

| Metric | Score |
| ------ | ----: |
| recall@5 | 0.9583 |
| recall@10 | 0.9583 |
| recall@20 | 0.9583 |
| hit@5 | 0.9583 |
| hit@10 | 0.9583 |
| mrr | 0.9444 |
| ndcg@10 | 0.9479 |

## By type

| Type | n | R@10 | Hit@10 | MRR |
| ---- | -: | ---: | -----: | --: |
| document_title | 48 | 0.9583 | 0.9583 | 0.9444 |

Cold p50 1556.1 ms · p95 1827.1 ms
Matter scope resolved 0.0000 (n=48, median document universe 0.0)
Stage latency ms: {"parallel_wall_ms": {"n": 48, "p50": 1548.8, "p95": 1820.3}, "bm25": {"n": 48, "p50": 1548.6, "p95": 1820.2}, "vector": {"n": 48, "p50": 58.4, "p95": 81.6}, "matter_scope_ms": {"n": 48, "p50": 3.2, "p95": 4.7}}
Immediate cache repeat p50 0.8 ms (12/12 hits). This is not an end-of-run warm number.

Intents: {"matter_research": 48}

Channel nonzero rate: {"bm25": 1.0, "final": 1.0, "title_match": 0.9375, "vector": 1.0}
