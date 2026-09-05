# P5.6-C1 Holder-Matter Resolution

Metric: **HolderCoverage@K** = |holders ∩ top-K| / |holders|

| Variant | Cov@5 | Cov@10 | Cov@20 | Cov@50 | Cov@100 | Hit@20 | % reach Cov≥0.9 |
| ------- | ----: | -----: | -----: | -----: | ------: | -----: | --------------: |
| vector | 0.029 | 0.057 | 0.100 | 0.100 | 0.100 | 0.571 | 0.00 |
| lexical | 0.043 | 0.100 | 0.219 | 0.543 | 0.871 | 0.857 | 0.71 |
| lexical_struct | 0.057 | 0.114 | 0.248 | 0.557 | 0.871 | 1.000 | 0.71 |
| vector_struct | 0.014 | 0.057 | 0.129 | 0.129 | 0.129 | 0.571 | 0.00 |
| hybrid | 0.014 | 0.043 | 0.157 | 0.467 | 0.857 | 0.571 | 0.71 |
| hybrid_struct | 0.014 | 0.043 | 0.186 | 0.538 | 0.886 | 0.714 | 0.71 |

SEMANTIC_DOC_RESOLVE remains **off**.
